import { useState } from 'react';
import { Link } from 'react-router-dom';
import { apiRequest } from '../api/client';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const data = await apiRequest('/auth/password-recovery', {
        method: 'POST',
        body: JSON.stringify({ email }),
      });
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <Link to="/login" className="text-sm font-semibold text-brand-700">
          ← Back to Sign in
        </Link>
        <h1 className="mt-4 text-2xl font-bold text-slate-900">Password recovery</h1>
        <p className="mt-1 text-sm text-slate-600">
          Email delivery is stubbed in the foundation build.
        </p>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        {result && (
          <div className="mt-4 rounded-lg border border-brand-200 bg-brand-50 p-3 text-sm text-brand-900">
            <p>{result.message}</p>
            {result.dev_reset_token && (
              <p className="mt-1 font-mono text-xs">Dev stub token: {result.dev_reset_token}</p>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="forgot-email" className="block text-sm font-medium text-slate-700">
              Account email
            </label>
            <input
              id="forgot-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {submitting ? 'Submitting...' : 'Request recovery'}
          </button>
        </form>
      </div>
    </div>
  );
}
