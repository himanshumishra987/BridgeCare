import { Loader2 } from 'lucide-react';
import { isUnsupportedEndpoint } from '../../api/client';

/**
 * One section's loading, unavailable or error state.
 *
 * Kept shared so every page classifies a failed request the same way instead of
 * rendering it as an empty record. `state` is `{ status, error, httpStatus }`
 * where status is 'loading' | 'ready' | 'unavailable' | 'error'. `ready` renders
 * nothing here because the page owns that markup.
 */

export const loadingSection = () => ({ status: 'loading', error: '', httpStatus: null });

export const readySection = () => ({ status: 'ready', error: '', httpStatus: null });

/**
 * HTTP 501 is the only signal read as "the backend has not implemented this".
 * A 404 is a failure, including on a list endpoint, until the backend confirms
 * a different meaning. See api/client.js for the proposed status contract.
 */
export function failedSection(err) {
  return {
    status: isUnsupportedEndpoint(err) ? 'unavailable' : 'error',
    error: err?.message || 'unknown error',
    httpStatus: err?.status ?? null,
  };
}

export default function SectionState({ state, label, onRetry }) {
  if (state.status === 'loading') {
    return (
      <p role="status" className="mt-3 flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading {label}…
      </p>
    );
  }

  if (state.status === 'unavailable') {
    return (
      <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <strong>Not available yet.</strong> The server reported that {label} is not implemented
        (HTTP 501), so nothing is shown. This is not the same as an empty record.
      </p>
    );
  }

  if (state.status === 'error') {
    return (
      <div
        role="alert"
        className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        Could not load {label}: {state.error}{' '}
        {onRetry && (
          <button type="button" onClick={onRetry} className="font-semibold underline">
            Retry
          </button>
        )}
        {state.httpStatus === 404 && (
          <p className="mt-1 text-xs text-red-800">
            The server answered 404. For a list endpoint that can mean the route is not registered
            or that no records exist, so it is shown as a failure until the backend confirms which.
          </p>
        )}
      </div>
    );
  }

  return null;
}
