import { useCallback, useEffect, useState } from 'react';
import { Clock, Eye, Shield, Users } from 'lucide-react';
import { familyApi } from '../../api/family';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import StatusBadge from '../../components/ui/StatusBadge';
import { useAuth } from '../../context/AuthContext';

const SCOPE_OPTIONS = [
  'documents:read',
  'timeline:read',
  'summaries:read',
  'labs:read',
  'medications:read',
];

export default function FamilyHealthPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [members, setMembers] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  // Consent request form
  const [email, setEmail] = useState('');
  const [scopes, setScopes] = useState(['documents:read']);
  const [expiryDate, setExpiryDate] = useState('');
  const [requesting, setRequesting] = useState(false);

  // Preview scope filter
  const [previewMember, setPreviewMember] = useState(null);

  const load = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    setError('');
    try {
      const [mem, hist] = await Promise.all([
        familyApi.getMembers(patientId).catch(() => []),
        familyApi.getSharingHistory(patientId).catch(() => []),
      ]);
      setMembers(Array.isArray(mem) ? mem : []);
      setHistory(Array.isArray(hist) ? hist : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => { load(); }, [load]);

  const toggleScope = (scope) =>
    setScopes((prev) => (prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]));

  const handleRequest = async (e) => {
    e.preventDefault();
    if (!email || scopes.length === 0) return;
    setRequesting(true);
    setMsg('');
    setError('');
    try {
      await familyApi.requestConsent(patientId, { email, scopes, expires_at: expiryDate || undefined });
      setEmail('');
      setExpiryDate('');
      setMsg('Consent request sent successfully.');
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setRequesting(false);
    }
  };

  const handleRevoke = async (grantId) => {
    setError('');
    try {
      await familyApi.revokeAccess(grantId);
      setMsg('Access revoked immediately.');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Family Health"
        subtitle="Manage family access — explicit consent is always required; family relationships alone never grant access to records."
      />

      <ErrorBanner message={error} onDismiss={() => setError('')} />
      {msg && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{msg}</div>
      )}

      {/* Consent request form */}
      <SectionCard>
        <h2 className="text-lg font-semibold text-slate-900">Share with a Family Member</h2>
        <form onSubmit={handleRequest} className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-slate-700">Family member email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="family@example.com"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Access expiry (optional)</label>
              <input
                type="date"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-700">Permitted scopes</p>
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
            disabled={requesting || scopes.length === 0}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {requesting ? 'Sending…' : 'Send Consent Request'}
          </button>
        </form>
      </SectionCard>

      {/* Members */}
      <SectionCard>
        <h2 className="text-lg font-semibold text-slate-900">Family Members with Access</h2>
        {loading ? (
          <LoadingSpinner />
        ) : members.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No family access grants yet"
            description="Use the form above to share your records with a family member."
          />
        ) : (
          <div className="mt-4 divide-y divide-slate-100">
            {members.map((m) => (
              <div key={m.grant_id || m.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div>
                  <p className="font-semibold text-slate-900">{m.name || m.email}</p>
                  <p className="text-xs text-slate-500">
                    Scopes: {(m.scopes || []).join(', ')}
                  </p>
                  {m.expires_at && (
                    <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                      <Clock className="h-3 w-3" />
                      Expires {new Date(m.expires_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={m.status} />
                  <button
                    type="button"
                    onClick={() => setPreviewMember(previewMember?.id === m.id ? null : m)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    Preview
                  </button>
                  {m.status === 'active' && (
                    <button
                      type="button"
                      onClick={() => handleRevoke(m.grant_id || m.id)}
                      className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100"
                    >
                      Revoke
                    </button>
                  )}
                </div>

                {/* Consent-aware preview */}
                {previewMember?.id === m.id && (
                  <div className="w-full mt-2 rounded-xl border border-brand-200 bg-brand-50 p-3">
                    <p className="text-xs font-semibold text-brand-800 flex items-center gap-1">
                      <Shield className="h-3.5 w-3.5" /> This member can only see:
                    </p>
                    <ul className="mt-1 list-disc pl-4 text-xs text-brand-700 space-y-0.5">
                      {(m.scopes || []).map((s) => <li key={s}>{s}</li>)}
                    </ul>
                    <p className="mt-2 text-xs text-brand-600">
                      Records outside these scopes are completely hidden from their view.
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Sharing audit history */}
      {history.length > 0 && (
        <SectionCard>
          <h2 className="text-lg font-semibold text-slate-900">Sharing Activity</h2>
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-4 py-2">Action</th>
                  <th className="px-4 py-2">Resource</th>
                  <th className="px-4 py-2">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.map((log) => (
                  <tr key={log.id}>
                    <td className="px-4 py-2 font-medium text-slate-800">{log.action}</td>
                    <td className="px-4 py-2">{log.resource_type}</td>
                    <td className="px-4 py-2">{new Date(log.created_at).toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
