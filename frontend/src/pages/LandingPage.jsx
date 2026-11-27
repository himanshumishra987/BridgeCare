import { Link } from 'react-router-dom';
import { ArrowRight, FileCheck2, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getHomePathForRole } from '../components/RouteGuards';

export default function LandingPage() {
  const { user } = useAuth();

  return (
    <div className="min-h-screen bg-gradient-to-b from-brand-50 via-white to-slate-50">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <span className="text-xl font-bold tracking-tight text-brand-700">BridgeCare</span>
        <div className="flex items-center gap-3">
          {user ? (
            <Link
              to={getHomePathForRole(user.role)}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              Open Portal
            </Link>
          ) : (
            <>
              <Link
                to="/login"
                className="rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                Sign in
              </Link>
              <Link
                to="/register"
                className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
              >
                Get Started
              </Link>
            </>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-12 sm:px-6 lg:py-20">
        <div className="text-center">
          <span className="inline-flex items-center rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-900">
            BioForge 2026 · PS1 Foundation
          </span>
          <h1 className="mt-4 text-3xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            Organise scattered medical records with privacy &amp; human oversight
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base text-slate-600 sm:text-lg">
            BridgeCare brings patient documents, explicit consent controls, and role-based clinical
            review into one structured personal health record platform.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link
              to="/register"
              className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
            >
              Create Patient or Navigator Account
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              to="/login"
              className="rounded-xl border border-slate-300 bg-white px-6 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Sign in to existing portal
            </Link>
          </div>
        </div>

        <div className="mt-16 grid gap-6 sm:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <LockKeyhole className="h-6 w-6 text-brand-600" />
            <h2 className="mt-3 text-base font-semibold text-slate-900">Explicit Consent Core</h2>
            <p className="mt-2 text-sm text-slate-600">
              Every patient-data endpoint enforces scoped, revocable access grants and full audit
              logging. Family relationships never grant access automatically.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <FileCheck2 className="h-6 w-6 text-brand-600" />
            <h2 className="mt-3 text-base font-semibold text-slate-900">Secure Upload Vault</h2>
            <p className="mt-2 text-sm text-slate-600">
              PDFs and images are validated by MIME and magic bytes, stored outside the web root,
              and served only through authenticated endpoints.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <ShieldCheck className="h-6 w-6 text-brand-600" />
            <h2 className="mt-3 text-base font-semibold text-slate-900">Plug-and-Play Modules</h2>
            <p className="mt-2 text-sm text-slate-600">
              Nine planned clinical, biomarker, medication, and assistance modules plug cleanly into
              the shared module registry.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
