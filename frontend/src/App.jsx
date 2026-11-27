import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import { ProtectedRoute, RoleHomeRedirect, RoleRoute } from './components/RouteGuards';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getEnabledModulesForRole } from './modules/registry';
import AccessControlPage from './pages/AccessControlPage';
import DocumentsVaultPage from './pages/DocumentsVaultPage';
import FamilyDashboard from './pages/FamilyDashboard';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import HolisticPreview from './pages/HolisticPreview';
import InsurancePage from './pages/InsurancePage';
import InsurancePreview from './pages/InsurancePreview';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import ModulesPreview from './pages/ModulesPreview';
import NavigatorDashboard from './pages/NavigatorDashboard';
import PatientDashboard from './pages/PatientDashboard';
import ProfileSetupPage from './pages/ProfileSetupPage';
import RegisterPage from './pages/RegisterPage';

function AppRoutes() {
  const { user } = useAuth();
  const enabledModuleRoutes = getEnabledModulesForRole(user?.role);

  return (
    <Routes>
      {/* Public routes */}
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      {import.meta.env.DEV && <Route path="/preview/insurance" element={<InsurancePreview />} />}
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
            <Route path="/patient/insurance" element={<InsurancePage />} />
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
          {enabledModuleRoutes.map((mod) => {
            const ModuleComponent = mod.component;
            return <Route key={mod.id} path={mod.path} element={<ModuleComponent />} />;
          })}
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
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
