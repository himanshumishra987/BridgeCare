import { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import RouteErrorBoundary from './components/RouteErrorBoundary';
import { ProtectedRoute, RoleHomeRedirect, RoleRoute } from './components/RouteGuards';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getEnabledModulesForRole } from './modules/registry';
import AccessControlPage from './pages/AccessControlPage';
import DocumentsVaultPage from './pages/DocumentsVaultPage';
import FamilyDashboard from './pages/FamilyDashboard';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import ModulesPreview from './pages/ModulesPreview';
import NavigatorDashboard from './pages/NavigatorDashboard';
import PatientDashboard from './pages/PatientDashboard';
import ProfileSetupPage from './pages/ProfileSetupPage';
import RegisterPage from './pages/RegisterPage';

// DEV-only preview pages. Loading them lazily keeps their preview-only code out of
// the entry chunk and lets the module pages they reuse be split normally.
const HolisticPreview = lazy(() => import('./pages/HolisticPreview'));
const InsuranceModulePreview = lazy(() => import('./pages/InsuranceModulePreview'));

function AppRoutes() {
  const { user } = useAuth();
  const location = useLocation();
  const enabledModuleRoutes = getEnabledModulesForRole(user?.role);

  return (
    <Suspense fallback={null}>
      {/* Keyed on the path so navigating away clears a render error. */}
      <RouteErrorBoundary key={location.pathname}>
      <Routes>
        {/* Public routes */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        {import.meta.env.DEV && (
          <Route path="/preview/insurance" element={<InsuranceModulePreview />} />
        )}
        {import.meta.env.DEV && <Route path="/preview/holistic" element={<HolisticPreview />} />}
        {import.meta.env.DEV && <Route path="/preview" element={<ModulesPreview />} />}
        {import.meta.env.DEV && <Route path="/preview/:moduleId" element={<ModulesPreview />} />}

        {/* Authenticated routes */}
        <Route element={<ProtectedRoute />}>
          <Route path="/dashboard" element={<RoleHomeRedirect />} />

          <Route element={<AppLayout />}>
            <Route path="/profile/setup" element={<ProfileSetupPage />} />

            {/* Patient Portal */}
            <Route element={<RoleRoute allowedRoles={['patient']} />}>
              <Route path="/patient/dashboard" element={<PatientDashboard />} />
              <Route path="/patient/documents" element={<DocumentsVaultPage />} />
              <Route path="/patient/access" element={<AccessControlPage />} />
              {/* Insurance has one implementation: the registered module page. */}
              <Route
                path="/patient/insurance"
                element={<Navigate to="/modules/insurance" replace />}
              />
            </Route>

            {/* Doctor / Navigator Portal */}
            <Route element={<RoleRoute allowedRoles={['doctor_navigator']} />}>
              <Route path="/navigator/dashboard" element={<NavigatorDashboard />} />
            </Route>

            {/* Family Shared View */}
            <Route element={<RoleRoute allowedRoles={['family_member']} />}>
              <Route path="/family/dashboard" element={<FamilyDashboard />} />
            </Route>

            {/* Plug-and-play routes generated from enabled entries in MODULE_REGISTRY */}
            {enabledModuleRoutes.map((mod) => (
              <Route key={mod.id} path={mod.path} element={<mod.component />} />
            ))}
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </RouteErrorBoundary>
    </Suspense>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}
