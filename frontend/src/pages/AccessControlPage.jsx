import { useCallback, useEffect, useState } from 'react';
import { accessGrantsApi } from '../api/accessGrants';
import { asArray, expectArray } from '../api/shape';
import SectionState, { failedSection, loadingSection, readySection } from '../components/ui/SectionState';
import { useAuth } from '../context/AuthContext';

const SCOPE_OPTIONS = [
  'documents:read',
  'documents:write',
  'timeline:read',
  'summaries:read',
  'labs:read',
  'medications:read',
  'audit:read',
];

const noProfile = () => new Error('this account has no linked patient profile');

export default function AccessControlPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;
  const [grants, setGrants] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  // Grants and audit logs load independently: one failing request is reported
  // as that section's failure instead of hiding both behind one error.
  const [grantsState, setGrantsState] = useState(loadingSection);
  const [logsState, setLogsState] = useState(loadingSection);
  const [granteeEmail, setGranteeEmail] = useState('');
  const [grantType, setGrantType] = useState('navigator');
  const [scopes, setScopes] = useState(['documents:read']);
  const [expiryDate, setExpiryDate] = useState('');
  const [error, setError] = useState('');

  const loadGrants = useCallback(async () => {
    if (!patientId) {
      setGrantsState(failedSection(noProfile()));
      return;
    }
    setGrantsState(loadingSection());
    try {
      // A non-array success is a failure, not "you have no grants".
      const list = expectArray(await accessGrantsApi.list(), 'your access grants');
      setGrants(list);
      setGrantsState(readySection());
    } catch (err) {
      // Previously loaded grants stay on screen, marked as stale.
      setGrantsState(failedSection(err));
    }
  }, [patientId]);

  const loadAuditLogs = useCallback(async () => {
    if (!patientId) {
      setLogsState(failedSection(noProfile()));
      return;
    }
    setLogsState(loadingSection());
    try {
      const logs = expectArray(
        await accessGrantsApi.listAuditLogs(patientId),
        'the sharing audit log'
      );
      setAuditLogs(logs);
      setLogsState(readySection());
    } catch (err) {
      setLogsState(failedSection(err));
    }
  }, [patientId]);

  const loadData = useCallback(async () => {
    await Promise.all([loadGrants(), loadAuditLogs()]);
  }, [loadGrants, loadAuditLogs]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const toggleScope = (scope) => {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((item) => item !== scope) : [...prev, scope]
    );
  };

  const handleCreateGrant = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await accessGrantsApi.create({
        grantee_email: granteeEmail,
        grant_type: grantType,
        scopes,
        // Optional: the backend may ignore or reject unsupported fields.
        expires_at: expiryDate || null,
      });
      setGranteeEmail('');
      setExpiryDate('');
      await loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRevoke = async (grantId) => {
    setError('');
    try {
      await accessGrantsApi.revoke(grantId);
      await loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">Explicit Consent &amp; Access Control</h1>
        <p className="mt-1 text-sm text-slate-600">
          Only users with an active grant can view your records. Family links alone never grant
          access, and revocation takes effect immediately.
        </p>

        {error && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleCreateGrant} className="mt-5 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="grant-email" className="block text-sm font-medium text-slate-700">
                Grantee Email
              </label>
              <input
                id="grant-email"
                type="email"
                required
                value={granteeEmail}
                onChange={(e) => setGranteeEmail(e.target.value)}
                placeholder="navigator@bridgecare.local"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="grant-type" className="block text-sm font-medium text-slate-700">
                Grant Type
              </label>
              <select
                id="grant-type"
                value={grantType}
                onChange={(e) => setGrantType(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="navigator">Doctor / Navigator</option>
                <option value="family">Family Member</option>
              </select>
            </div>
            <div>
              <label htmlFor="grant-expiry" className="block text-sm font-medium text-slate-700">
                Access expiry (optional)
              </label>
              <input
                id="grant-expiry"
                type="date"
                value={expiryDate}
                min={new Date().toLocaleDateString('en-CA')}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-slate-500">
                Leave blank for access that lasts until you revoke it.
              </p>
            </div>
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700">Allowed Scopes</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {SCOPE_OPTIONS.map((scope) => (
                <label
                  key={scope}
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700"
                >
                  <input
                    type="checkbox"
                    checked={scopes.includes(scope)}
                    onChange={() => toggleScope(scope)}
                  />
                  {scope}
                </label>
              ))}
            </div>
          </div>

          <button
            type="submit"
            disabled={scopes.length === 0}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            Grant Scoped Access
          </button>
        </form>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Access Grants</h2>
        <SectionState state={grantsState} label="your access grants" onRetry={loadGrants} />
        {grantsState.status === 'error' && grants.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Showing grants loaded earlier; the latest refresh failed.
          </p>
        )}
        {grantsState.status === 'ready' && grants.length === 0 && (
          <p className="mt-3 text-sm text-slate-500">No access grants created yet.</p>
        )}
        {grants.length > 0 && (
          <div className="mt-4 divide-y divide-slate-200">
            {grants.map((grant) => {
              const expired =
                typeof grant.expires_at === 'string' &&
                grant.expires_at !== '' &&
                grant.expires_at < new Date().toLocaleDateString('en-CA');
              const effectiveStatus = expired && grant.status === 'active' ? 'expired' : grant.status;
              const grantScopes = asArray(grant.scopes);
              return (
                <div
                  key={grant.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
                >
                  <div>
                    <p className="font-medium text-slate-900">
                      {grant.grantee_name || 'Unnamed grantee'} ({grant.grantee_email || 'no email reported'})
                    </p>
                    <p className="text-xs text-slate-500">
                      Type: {grant.grant_type || 'not reported'} · Scopes:{' '}
                      {grantScopes.join(', ') || 'none'} · Status:{' '}
                      <span className="font-semibold">{effectiveStatus || 'not reported'}</span>
                    </p>
                    <p className="text-xs text-slate-500">
                      {grant.expires_at
                        ? `Expires ${new Date(grant.expires_at).toLocaleDateString('en-IN', {
                            year: 'numeric',
                            month: 'short',
                            day: 'numeric',
                          })}`
                        : 'No expiry set — access lasts until revoked'}
                    </p>
                    {expired && (
                      <p className="mt-1 text-xs font-semibold text-amber-700">
                        Past expiry: this grant no longer authorizes access. The backend must enforce
                        this; expiry is displayed, never assumed.
                      </p>
                    )}
                  </div>
                  {grant.status === 'active' && !expired && (
                    <button
                      type="button"
                      onClick={() => handleRevoke(grant.id)}
                      className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100"
                    >
                      Revoke Immediately
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Audit Log</h2>
        <SectionState state={logsState} label="the sharing audit log" onRetry={loadAuditLogs} />
        {logsState.status === 'error' && auditLogs.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Showing activity loaded earlier; the latest refresh failed.
          </p>
        )}
        {logsState.status === 'ready' && auditLogs.length === 0 && (
          <p className="mt-3 text-sm text-slate-500">No sharing activity recorded yet.</p>
        )}
        {auditLogs.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="border-b border-slate-200 text-slate-500">
                <tr>
                  <th scope="col" className="py-2 pr-4">
                    Action
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    Resource
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    Timestamp
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {auditLogs.map((log) => (
                  <tr key={log.id}>
                    <td className="py-2 pr-4 font-medium text-slate-900">{log.action || '—'}</td>
                    <td className="py-2 pr-4">
                      {log.resource_type || '—'}{' '}
                      {typeof log.resource_id === 'string' && log.resource_id
                        ? `(${log.resource_id.slice(0, 8)})`
                        : ''}
                    </td>
                    <td className="py-2 pr-4">{new Date(log.created_at).toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
