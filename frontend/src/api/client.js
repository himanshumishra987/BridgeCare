/** Only ever used by a development server. Never a production default. */
const DEV_API_BASE_URL = 'http://localhost:8000/api/v1';

const LOOPBACK_HOST = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\|\/|$)/i;

/**
 * A production bundle must never fall back to a developer machine: a build that
 * silently calls localhost:8000 looks like an empty product instead of a
 * misconfiguration. Dev keeps the convenient fallback.
 */
function resolveBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();

  if (configured) {
    if (import.meta.env.PROD && LOOPBACK_HOST.test(configured)) {
      throw new Error(
        'VITE_API_BASE_URL points at a loopback host in a production build. ' +
          'Set it to the deployed API origin (see frontend/.env.production.example).'
      );
    }
    return configured.replace(/\/+$/, '');
  }

  if (import.meta.env.DEV) return DEV_API_BASE_URL;

  throw new Error(
    'VITE_API_BASE_URL is not set. A production build refuses to fall back to localhost; ' +
      'set it to the deployed API origin (see frontend/.env.production.example).'
  );
}

export const API_BASE_URL = resolveBaseUrl();

const STORAGE_KEYS = {
  accessToken: 'bridgecare_access_token',
  refreshToken: 'bridgecare_refresh_token',
};

/** Default timeout for a normal API call. Slow operations can pass `timeoutMs`. */
export const DEFAULT_TIMEOUT_MS = 30000;

/** Refresh must not hang either; the UI needs an answer to redirect on failure. */
const REFRESH_TIMEOUT_MS = 15000;

/** Fired after stored tokens are cleared because a refresh failed. */
export const SESSION_EXPIRED_EVENT = 'bridgecare:session-expired';

let sessionExpiredNotified = false;

export function getStoredTokens() {
  return {
    accessToken: localStorage.getItem(STORAGE_KEYS.accessToken),
    refreshToken: localStorage.getItem(STORAGE_KEYS.refreshToken),
  };
}

export function setStoredTokens(accessToken, refreshToken) {
  if (accessToken) localStorage.setItem(STORAGE_KEYS.accessToken, accessToken);
  if (refreshToken) localStorage.setItem(STORAGE_KEYS.refreshToken, refreshToken);
  // A new session can expire again and must notify again.
  sessionExpiredNotified = false;
}

export function clearStoredTokens() {
  localStorage.removeItem(STORAGE_KEYS.accessToken);
  localStorage.removeItem(STORAGE_KEYS.refreshToken);
}

function announceSessionExpired() {
  if (sessionExpiredNotified) return;
  sessionExpiredNotified = true;
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
  }
}

let refreshPromise = null;

async function performRefresh() {
  const { refreshToken } = getStoredTokens();
  if (!refreshToken) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: controller.signal,
    });
    if (!res.ok) {
      clearStoredTokens();
      return null;
    }
    const data = await res.json();
    setStoredTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch {
    clearStoredTokens();
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function refreshAccessToken() {
  if (!refreshPromise) {
    // Single-flight: concurrent 401s share one refresh request.
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

/**
 * One place that owns the base URL, auth header, timeout and 401 refresh.
 * Returns the raw Response so JSON and blob callers share the same behaviour.
 */
async function sendRequest(path, options = {}, retryOn401 = true) {
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    headers: extraHeaders,
    signal: externalSignal,
    ...rest
  } = options;

  const { accessToken } = getStoredTokens();
  const isFormData = rest.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(extraHeaders || {}),
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener('abort', forwardAbort);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers,
      signal: controller.signal,
    });

    if (response.status === 401 && retryOn401 && !path.startsWith('/auth/')) {
      const newAccessToken = await refreshAccessToken();
      if (newAccessToken) {
        return sendRequest(path, options, false);
      }
      // Refresh failed: the session is over, so tell AuthContext.
      announceSessionExpired();
    }

    return response;
  } catch (err) {
    if (timedOut) {
      const timeoutError = new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)} seconds`
      );
      timeoutError.name = 'TimeoutError';
      timeoutError.code = 'REQUEST_TIMEOUT';
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener('abort', forwardAbort);
  }
}

export async function apiRequest(path, options = {}, retryOn401 = true) {
  const response = await sendRequest(path, options, retryOn401);

  if (response.status === 204) {
    return null;
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      typeof data?.detail === 'string' && data.detail
        ? data.detail
        : `Request failed (${response.status})`;
    const err = new Error(message);
    err.status = response.status;
    err.payload = data;
    throw err;
  }
  return data;
}

/**
 * Error classification, using standard HTTP status semantics only.
 *
 * CONTRACT STATUS: proposed. The backend has not confirmed which status it uses
 * for a capability it has not built. Until it does, the frontend relies on the
 * ordinary meanings below and refuses to guess beyond them.
 *
 * - 501 Not Implemented: the backend explicitly says the capability does not
 *   exist. This is the only signal treated as "not available yet".
 * - 404 Not Found: the resource is absent. On a list endpoint that is ambiguous
 *   with an unregistered route, so callers report it as a failure rather than as
 *   "unavailable" or "empty". A single-resource GET may treat it as "no record".
 */
export function isUnsupportedEndpoint(err) {
  return err?.status === 501;
}

export function isMissingResource(err) {
  return err?.status === 404;
}

/** Fetch a protected file as a Blob, through the same client rules as apiRequest. */
export async function getAuthorizedBlob(path, options = {}) {
  const response = await sendRequest(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message =
      typeof payload?.detail === 'string' && payload.detail
        ? payload.detail
        : `Download failed (${response.status})`;
    const err = new Error(message);
    err.status = response.status;
    err.payload = payload;
    throw err;
  }
  return response.blob();
}

export async function downloadAuthorizedFile(path, fallbackFilename, options = {}) {
  const blob = await getAuthorizedBlob(path, options);
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fallbackFilename || 'document';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
