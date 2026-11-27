import { Component } from 'react';

/**
 * Route-level render-error boundary.
 *
 * A malformed API payload that survives the shape guards must not blank the
 * whole application: the failing screen is replaced by this fallback while the
 * shell, session and other routes keep working. Keyed on the pathname by App so
 * navigating away clears the error state.
 */
export default class RouteErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div role="alert" className="mx-auto max-w-2xl space-y-3 rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
        <h1 className="text-lg font-semibold text-red-900">This screen could not be displayed</h1>
        <p>
          Something in this page failed to render. Nothing was saved or changed by this error.
        </p>
        <p className="break-words rounded-lg bg-white/70 px-3 py-2 font-mono text-xs">
          {this.state.error?.message || String(this.state.error)}
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800"
          >
            Try this screen again
          </button>
          <a
            href="/dashboard"
            className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-800 hover:bg-red-100"
          >
            Go to my dashboard
          </a>
        </div>
      </div>
    );
  }
}
