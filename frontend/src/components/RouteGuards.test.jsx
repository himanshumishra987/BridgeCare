import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthContext } from '../context/AuthContext';
import { ProtectedRoute, RoleHomeRedirect, RoleRoute } from './RouteGuards';

function renderAt(path, user, routes) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={{ user, loading: false }}>
        <Routes>{routes}</Routes>
      </AuthContext.Provider>
    </MemoryRouter>
  );
}

describe('ProtectedRoute', () => {
  it('redirects a signed-out visitor to the login page', () => {
    renderAt('/patient/dashboard', null, [
      <Route key="login" path="/login" element={<div>login screen</div>} />,
      <Route key="protected" element={<ProtectedRoute />}>
        <Route path="/patient/dashboard" element={<div>patient dashboard</div>} />
      </Route>,
    ]);

    expect(screen.getByText('login screen')).toBeInTheDocument();
    expect(screen.queryByText('patient dashboard')).not.toBeInTheDocument();
  });

  it('renders the protected content for a signed-in user', () => {
    renderAt('/patient/dashboard', { role: 'patient' }, [
      <Route key="login" path="/login" element={<div>login screen</div>} />,
      <Route key="protected" element={<ProtectedRoute />}>
        <Route path="/patient/dashboard" element={<div>patient dashboard</div>} />
      </Route>,
    ]);

    expect(screen.getByText('patient dashboard')).toBeInTheDocument();
  });
});

describe('RoleRoute', () => {
  it('sends a wrong-role user to their own home, not to login', () => {
    renderAt('/modules/insurance', { role: 'family_member' }, [
      <Route key="login" path="/login" element={<div>login screen</div>} />,
      <Route key="family" path="/family/dashboard" element={<div>family home</div>} />,
      <Route key="guard" element={<RoleRoute allowedRoles={['patient']} />}>
        <Route path="/modules/insurance" element={<div>insurance</div>} />
      </Route>,
    ]);

    expect(screen.getByText('family home')).toBeInTheDocument();
    expect(screen.queryByText('login screen')).not.toBeInTheDocument();
  });

  it('allows a matching role through', () => {
    renderAt('/modules/insurance', { role: 'patient' }, [
      <Route key="guard" element={<RoleRoute allowedRoles={['patient']} />}>
        <Route path="/modules/insurance" element={<div>insurance</div>} />
      </Route>,
    ]);

    expect(screen.getByText('insurance')).toBeInTheDocument();
  });
});

describe('RoleHomeRedirect', () => {
  it('maps each role to its own home path', () => {
    const cases = [
      ['patient', '/patient/dashboard', 'patient home'],
      ['doctor_navigator', '/navigator/dashboard', 'navigator home'],
      ['family_member', '/family/dashboard', 'family home'],
    ];

    cases.forEach(([role, path, text]) => {
      const { unmount } = renderAt('/dashboard', { role }, [
        <Route key="home" path="/dashboard" element={<RoleHomeRedirect />} />,
        <Route key="target" path={path} element={<div>{text}</div>} />,
      ]);
      expect(screen.getByText(text)).toBeInTheDocument();
      unmount();
    });
  });
});
