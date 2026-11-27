import { Suspense, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  FileUp,
  LayoutDashboard,
  LogOut,
  Menu,
  Shield,
  UserCog,
  Users,
  X,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getEnabledModulesForRole } from '../modules/registry';
import LoadingSpinner from './ui/LoadingSpinner';
import SafetyBanner from './SafetyBanner';

const CORE_NAV_BY_ROLE = {
  patient: [
    { to: '/patient/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/patient/documents', label: 'Document Vault', icon: FileUp },
    { to: '/patient/access', label: 'Access & Audit', icon: Shield },
    { to: '/profile/setup', label: 'Profile Setup', icon: UserCog },
  ],
  doctor_navigator: [
    { to: '/navigator/dashboard', label: 'Consented Patients', icon: Users },
    { to: '/profile/setup', label: 'Profile Setup', icon: UserCog },
  ],
  family_member: [
    { to: '/family/dashboard', label: 'Shared Records', icon: Users },
    { to: '/profile/setup', label: 'Profile Setup', icon: UserCog },
  ],
};

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const coreLinks = CORE_NAV_BY_ROLE[user?.role] || [];
  const enabledModules = getEnabledModulesForRole(user?.role);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const renderNavLinks = () => (
    <nav className="space-y-1">
      <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
        Foundation
      </p>
      {coreLinks.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
              isActive
                ? 'bg-brand-50 text-brand-700'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`
          }
        >
          <Icon className="h-4 w-4 shrink-0" />
          <span>{label}</span>
        </NavLink>
      ))}

      {enabledModules.length > 0 && (
        <div className="pt-4">
          <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Modules
          </p>
          {enabledModules.map((mod) => {
            const Icon = mod.icon;
            return (
              <NavLink
                key={mod.id}
                to={mod.path}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                    isActive
                      ? 'bg-brand-50 text-brand-700'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  }`
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{mod.title}</span>
              </NavLink>
            );
          })}
        </div>
      )}
    </nav>
  );

  return (
    <div className="min-h-screen bg-slate-50 lg:flex">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex lg:w-64 lg:flex-col lg:border-r lg:border-slate-200 lg:bg-white">
        <div className="flex h-16 items-center justify-between border-b border-slate-200 px-5">
          <Link to="/dashboard" className="text-lg font-bold tracking-tight text-brand-700">
            BridgeCare
          </Link>
          <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700">
            {user?.role === 'doctor_navigator' ? 'Navigator' : user?.role === 'family_member' ? 'Family' : 'Patient'}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{renderNavLinks()}</div>
        <div className="border-t border-slate-200 p-4">
          <div className="mb-3 truncate text-xs text-slate-500">{user?.email}</div>
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Mobile Top Bar */}
      <div className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4 lg:hidden">
        <Link to="/dashboard" className="text-lg font-bold text-brand-700">
          BridgeCare
        </Link>
        <button
          type="button"
          onClick={() => setMobileOpen((prev) => !prev)}
          className="rounded-lg p-2 text-slate-600 hover:bg-slate-100"
          aria-label="Toggle navigation"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="border-b border-slate-200 bg-white p-4 lg:hidden">
          {renderNavLinks()}
          <button
            type="button"
            onClick={handleLogout}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8">
        <div className="mx-auto max-w-6xl space-y-6">
          <SafetyBanner />
          {/* Module pages are lazy-loaded; this is their shared fallback. */}
          <Suspense fallback={<LoadingSpinner message="Loading module…" />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
