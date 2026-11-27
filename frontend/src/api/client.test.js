import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_TIMEOUT_MS,
  SESSION_EXPIRED_EVENT,
  apiRequest,
  getAuthorizedBlob,
  isMissingResource,
  isUnsupportedEndpoint,
} from './client';

const BASE = 'http://localhost:8000/api/v1';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

let fetchMock;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  localStorage.clear();
});

describe('apiRequest', () => {
  it('sends the bearer token and returns parsed JSON', async () => {
    localStorage.setItem('bridgecare_access_token', 'token-1');
    fetchMock.mockResolvedValueOnce(json({ id: 'p1' }));

    const data = await apiRequest('/patients/p1/insurance/policies');

    expect(data).toEqual({ id: 'p1' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/patients/p1/insurance/policies`);
    expect(init.headers.Authorization).toBe('Bearer token-1');
    expect(init.headers['Content-Type']).toBe('application/json');
  });

  it('returns null for 204 and does not try to parse a body', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(apiRequest('/patients/p1/reminders/m1')).resolves.toBeNull();
  });

  it('attaches status and payload to HTTP errors and keeps the detail message', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Policy not found' }, 404));

    const error = await apiRequest('/patients/p1/insurance/policies/x').catch((err) => err);

    expect(error).toBeInstanceOf(Error);
    expect(error.message).toBe('Policy not found');
    expect(error.status).toBe(404);
    expect(error.payload).toEqual({ detail: 'Policy not found' });
    expect(isMissingResource(error)).toBe(true);
    // A 404 (and even a "not found" detail string) is never read as an
    // unsupported capability.
    expect(isUnsupportedEndpoint(error)).toBe(false);
  });

  it('falls back to a status message when the error body is not useful', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: ['invalid'] }, 422));

    const error = await apiRequest('/patients/p1/insurance/policies').catch((err) => err);

    expect(error.message).toBe('Request failed (422)');
    expect(error.status).toBe(422);
    expect(isMissingResource(error)).toBe(false);
    expect(isUnsupportedEndpoint(error)).toBe(false);
  });

  it('treats only 501 as an explicitly unsupported capability', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Not Implemented' }, 501));

    const error = await apiRequest('/patients/p1/insurance/policies').catch((err) => err);

    expect(isUnsupportedEndpoint(error)).toBe(true);
    expect(isMissingResource(error)).toBe(false);
  });

  it('does not set a JSON content type for FormData bodies', async () => {
    const body = new FormData();
    body.append('file', new Blob(['x']), 'policy.pdf');
    fetchMock.mockResolvedValueOnce(json({ document_id: 'd1' }));

    await apiRequest('/patients/p1/insurance/policies/extract', { method: 'POST', body });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['Content-Type']).toBeUndefined();
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('aborts and reports a timeout when the server does not answer', async () => {
    fetchMock.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => {
            reject(Object.assign(new Error('Aborted'), { name: 'AbortError' }));
          });
        })
    );

    const error = await apiRequest('/patients/p1/slow', { timeoutMs: 5 }).catch((err) => err);

    expect(error.code).toBe('REQUEST_TIMEOUT');
    expect(error.name).toBe('TimeoutError');
  });

  it('exposes a default timeout so a hung upload cannot hold the UI forever', () => {
    expect(DEFAULT_TIMEOUT_MS).toBeGreaterThan(0);
  });
});

describe('401 refresh', () => {
  beforeEach(() => {
    localStorage.setItem('bridgecare_access_token', 'old-token');
    localStorage.setItem('bridgecare_refresh_token', 'refresh-1');
  });

  it('refreshes once for concurrent 401s and retries with the new token', async () => {
    let refreshCalls = 0;
    fetchMock.mockImplementation(async (url, init) => {
      if (url === `${BASE}/auth/refresh`) {
        refreshCalls += 1;
        return json({ access_token: 'new-token', refresh_token: 'refresh-2' });
      }
      if (init.headers.Authorization === 'Bearer old-token') {
        return json({ detail: 'Token expired' }, 401);
      }
      return json({ ok: true });
    });

    const [a, b] = await Promise.all([apiRequest('/patients/p1/x'), apiRequest('/patients/p1/y')]);

    expect(a).toEqual({ ok: true });
    expect(b).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(localStorage.getItem('bridgecare_access_token')).toBe('new-token');
    expect(localStorage.getItem('bridgecare_refresh_token')).toBe('refresh-2');
    // original + retry each, plus the single refresh
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it('never refreshes for an /auth/ path and surfaces the 401', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Bad credentials' }, 401));

    const error = await apiRequest('/auth/login', { method: 'POST', body: '{}' }).catch((e) => e);

    expect(error.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clears tokens and announces session expiry when refresh fails, once', async () => {
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);

    fetchMock.mockImplementation(async (url) => {
      if (url === `${BASE}/auth/refresh`) return json({ detail: 'Refresh expired' }, 401);
      return json({ detail: 'Token expired' }, 401);
    });

    await expect(apiRequest('/patients/p1/x')).rejects.toThrow('Token expired');
    await expect(apiRequest('/patients/p1/y')).rejects.toThrow('Token expired');

    expect(localStorage.getItem('bridgecare_access_token')).toBeNull();
    expect(localStorage.getItem('bridgecare_refresh_token')).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
  });
});

describe('getAuthorizedBlob', () => {
  it('fetches a protected file with the auth header and returns a Blob', async () => {
    localStorage.setItem('bridgecare_access_token', 'token-1');
    fetchMock.mockResolvedValueOnce(
      new Response(new Blob(['pdf-bytes'], { type: 'application/pdf' }), { status: 200 })
    );

    const blob = await getAuthorizedBlob('/patients/p1/documents/d1/download', { timeoutMs: 60000 });

    expect(blob).toBeInstanceOf(Blob);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/patients/p1/documents/d1/download`);
    expect(init.headers.Authorization).toBe('Bearer token-1');
  });

  it('throws a status-bearing error when the download is refused', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Forbidden' }, 403));

    const error = await getAuthorizedBlob('/patients/p1/documents/d1/download').catch((e) => e);

    expect(error.status).toBe(403);
    expect(error.message).toBe('Forbidden');
  });
});
