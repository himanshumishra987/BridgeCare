import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getHomePathForRole } from '../components/RouteGuards';
import RoleSelect, { ROLES } from '../components/RoleSelect';

const TEST_ACCOUNTS = {
  patient: 'patient@bridgecare.local / PatientPass123!',
  doctor_navigator: 'navigator@bridgecare.local / NavigatorPass123!',
  family_member: 'family@bridgecare.local / FamilyPass123!',
};

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [role, setRole] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const user = await login(email, password, role);
      if (!user.profile_completed) {
        navigate('/profile/setup');
      } else {
        navigate(getHomePathForRole(user.role));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const changeRole = () => {
    setRole('');
    setEmail('');
    setPassword('');
    setError('');
  };

  // Step 1: choose a role
  if (!role) {
    return <RoleSelect title="Sign in" onSelect={setRole} includeFamily />;
  }

  const roleLabel = ROLES.find((r) => r.value === role).label;

  // Step 2: enter credentials
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <button
          type="button"
          onClick={changeRole}
          disabled={submitting}
          className="text-sm font-semibold text-brand-700"
        >
          ← Change role
        </button>
        <h1 className="mt-4 text-2xl font-bold text-slate-900">{roleLabel} sign in</h1>
        <p className="mt-1 text-sm text-slate-600">Enter your account details.</p>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-sm font-medium text-slate-700">Password</label>
              <Link to="/forgot-password" className="text-xs font-medium text-brand-700 hover:underline">
                Forgot password?
              </Link>
            </div>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
              placeholder="••••••••"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <div className="mt-6 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
          <p className="font-semibold text-slate-700">Seeded local test account:</p>
          <p className="mt-1">{TEST_ACCOUNTS[role]}</p>
        </div>

        <p className="mt-5 text-center text-sm text-slate-600">
          New to BridgeCare?{' '}
          <Link to="/register" className="font-semibold text-brand-700 hover:underline">
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}
