import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileUp, Shield, UserCheck } from 'lucide-react';
import { accessGrantsApi } from '../api/accessGrants';
import { documentsApi } from '../api/documents';
import { useAuth } from '../context/AuthContext';
import { MODULE_REGISTRY } from '../modules/registry';

export default function PatientDashboard() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;
  const [docCount, setDocCount] = useState(0);
  const [grantCount, setGrantCount] = useState(0);
  const [statsError, setStatsError] = useState('');

  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    Promise.allSettled([documentsApi.list(patientId), accessGrantsApi.list()]).then(
      ([docs, grants]) => {
        if (cancelled) return;
        // A failed count is reported, never shown as a confident zero.
        const failed = [docs, grants].filter((r) => r.status === 'rejected');
        if (failed.length > 0) {
          setStatsError('Some dashboard counts could not be loaded.');
        } else {
          setStatsError('');
        }
        if (docs.status === 'fulfilled' && Array.isArray(docs.value)) {
          setDocCount(docs.value.length);
        }
        if (grants.status === 'fulfilled' && Array.isArray(grants.value)) {
          setGrantCount(grants.value.filter((g) => g.status === 'active').length);
        }
      }
    );
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold text-slate-900">Welcome, {user?.name}</h1>
        <p className="mt-1 text-sm text-slate-600">
          Patient Portal · Foundation ready for document upload, explicit consent, and audit logs.
        </p>

        {statsError && (
          <p role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {statsError}
          </p>
        )}

        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          <Link
            to="/patient/documents"
            className="rounded-xl border border-slate-200 p-4 transition hover:border-brand-500"
          >
            <FileUp className="h-5 w-5 text-brand-600" />
            <p className="mt-2 text-2xl font-bold text-slate-900">{docCount}</p>
            <p className="text-sm text-slate-600">Uploaded Documents</p>
          </Link>

          <Link
            to="/patient/access"
            className="rounded-xl border border-slate-200 p-4 transition hover:border-brand-500"
          >
            <Shield className="h-5 w-5 text-brand-600" />
            <p className="mt-2 text-2xl font-bold text-slate-900">{grantCount}</p>
            <p className="text-sm text-slate-600">Active Access Grants</p>
          </Link>

          <Link
            to="/profile/setup"
            className="rounded-xl border border-slate-200 p-4 transition hover:border-brand-500"
          >
            <UserCheck className="h-5 w-5 text-brand-600" />
            <p className="mt-2 text-lg font-bold text-slate-900">
              {user?.profile_completed ? 'Complete' : 'Needs Setup'}
            </p>
            <p className="text-sm text-slate-600">Profile Status</p>
          </Link>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Planned Module Slots</h2>
            <p className="text-sm text-slate-600">
              Loaded from <code>src/modules/registry.js</code>. Modules appear in navigation once
              implemented and enabled.
            </p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
            {MODULE_REGISTRY.filter((m) => m.enabled).length} / {MODULE_REGISTRY.length} Enabled
          </span>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {MODULE_REGISTRY.map((mod) => (
            <div key={mod.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-500">
                  Module {mod.number} · {mod.category}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 font-medium ${
                    mod.enabled
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-slate-200 text-slate-700'
                  }`}
                >
                  {mod.enabled ? 'Enabled' : 'Not started'}
                </span>
              </div>
              <h3 className="mt-2 text-sm font-semibold text-slate-900">{mod.title}</h3>
              <p className="mt-1 text-xs text-slate-600">{mod.description}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
