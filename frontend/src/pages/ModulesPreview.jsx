import { Component } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AuthContext } from '../context/AuthContext';
import { MODULE_REGISTRY } from '../modules/registry';

// Development preview only: a pretend patient, visible to preview pages alone
const unavailable = async () => {
  throw new Error('Not available in preview mode.');
};
const PREVIEW_AUTH = {
  user: {
    id: 'preview',
    name: 'Preview Patient',
    role: 'patient',
    profile_completed: true,
    patient_profile: { id: 'preview' },
  },
  loading: false,
  login: unavailable,
  register: unavailable,
  updateProfile: unavailable,
  logout: async () => {},
  reloadUser: async () => {},
};

// Extra previews that work with records kept in browser memory
const EXTRA_LINKS = {
  'holistic-health': { to: '/preview/holistic', text: 'Try adding records (no backend needed)' },
  'insurance-info': { to: '/preview/insurance', text: 'New Medical Card page' },
};

class PageErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        This page crashed: {this.state.error.message}
      </p>
    );
  }
}

export default function ModulesPreview() {
  const { moduleId } = useParams();
  const selected = MODULE_REGISTRY.find((m) => m.id === moduleId);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-5xl space-y-4">
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          Preview mode: no sign-in. Without a backend, errors and empty sections are expected.
        </p>

        {moduleId ? (
          <>
            <Link to="/preview" className="text-sm font-semibold text-brand-700">← All features</Link>
            {selected?.component ? (
              <AuthContext.Provider value={PREVIEW_AUTH}>
                <PageErrorBoundary key={selected.id}>
                  <selected.component />
                </PageErrorBoundary>
              </AuthContext.Provider>
            ) : (
              <p className="text-sm text-slate-600">No feature with this address.</p>
            )}
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold text-slate-900">All features</h1>
            <ul className="grid gap-3 sm:grid-cols-2">
              {MODULE_REGISTRY.map((m) => (
                <li key={m.id} className="rounded-xl border border-slate-200 bg-white p-4">
                  <Link to={`/preview/${m.id}`} className="font-semibold text-brand-700 hover:underline">
                    {m.number}. {m.title}
                  </Link>
                  <p className="mt-1 text-sm text-slate-600">{m.description}</p>
                  {EXTRA_LINKS[m.id] && (
                    <Link to={EXTRA_LINKS[m.id].to} className="mt-2 block text-sm font-medium text-brand-700 underline">
                      {EXTRA_LINKS[m.id].text}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
