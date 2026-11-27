import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthContext } from '../context/AuthContext';
import AccessControlPage from './AccessControlPage';
import FamilyDashboard from './FamilyDashboard';
import NavigatorDashboard from './NavigatorDashboard';
import { accessGrantsApi } from '../api/accessGrants';
import { patientsApi } from '../api/patients';
import { documentsApi } from '../api/documents';
import { getSecurityForDocuments } from '../api/documentSecurity';

vi.mock('../api/accessGrants', () => ({
  accessGrantsApi: {
    list: vi.fn(),
    create: vi.fn(),
    revoke: vi.fn(),
    listAuditLogs: vi.fn(),
  },
}));

vi.mock('../api/patients', () => ({
  patientsApi: { getAccessible: vi.fn() },
}));

vi.mock('../api/documents', () => ({
  documentsApi: { list: vi.fn(), upload: vi.fn() },
}));

vi.mock('../api/documentSecurity', () => ({
  getSecurityForDocuments: vi.fn(),
  documentSecurityApi: { get: vi.fn(), retry: vi.fn() },
}));

const auth = (user) => ({ user, loading: false });

beforeEach(() => {
  vi.clearAllMocks();
  accessGrantsApi.list.mockResolvedValue([]);
  accessGrantsApi.listAuditLogs.mockResolvedValue([]);
  patientsApi.getAccessible.mockResolvedValue([]);
  documentsApi.list.mockResolvedValue([]);
  getSecurityForDocuments.mockResolvedValue({});
});

describe('AccessControlPage states', () => {
  it('reports a failed grant list instead of "No access grants created yet"', async () => {
    accessGrantsApi.list.mockRejectedValue(Object.assign(new Error('Forbidden'), { status: 403 }));
    render(
      <AuthContext.Provider value={auth({ patient_profile: { id: 'p1' } })}>
        <AccessControlPage />
      </AuthContext.Provider>
    );

    expect(await screen.findByText(/Could not load your access grants/i)).toBeInTheDocument();
    expect(screen.queryByText('No access grants created yet.')).not.toBeInTheDocument();
    // The audit log still loads independently.
    expect(await screen.findByText('No sharing activity recorded yet.')).toBeInTheDocument();
  });

  it('survives a grant with a missing scopes array', async () => {
    accessGrantsApi.list.mockResolvedValue([
      { id: 'g1', grantee_email: 'nav@example.com', grant_type: 'navigator', status: 'active' },
    ]);
    render(
      <AuthContext.Provider value={auth({ patient_profile: { id: 'p1' } })}>
        <AccessControlPage />
      </AuthContext.Provider>
    );

    expect(await screen.findByText(/nav@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/Scopes:\s*none/)).toBeInTheDocument();
  });
});

describe('NavigatorDashboard shape guards', () => {
  it('renders a patient whose scopes field is missing without crashing', async () => {
    patientsApi.getAccessible.mockResolvedValue([
      { grant_id: 'g1', patient_id: 'p1', patient_name: 'Asha Rao' },
    ]);
    render(
      <AuthContext.Provider value={auth({ name: 'Dr Rao', role: 'doctor_navigator' })}>
        <NavigatorDashboard />
      </AuthContext.Provider>
    );

    expect(await screen.findByText('Asha Rao')).toBeInTheDocument();
    expect(screen.getByText(/Scopes:\s*none reported/)).toBeInTheDocument();
  });

  it('reports a failed patient list instead of "No patients have granted you active access yet"', async () => {
    patientsApi.getAccessible.mockRejectedValue(new Error('Gateway timeout'));
    render(
      <AuthContext.Provider value={auth({ name: 'Dr Rao', role: 'doctor_navigator' })}>
        <NavigatorDashboard />
      </AuthContext.Provider>
    );

    expect(await screen.findByText(/Could not load your consented patients/i)).toBeInTheDocument();
    expect(
      screen.queryByText('No patients have granted you active access yet.')
    ).not.toBeInTheDocument();
  });
});

describe('FamilyDashboard shape guards', () => {
  it('renders a record whose scopes field is null without crashing', async () => {
    patientsApi.getAccessible.mockResolvedValue([
      { grant_id: 'g2', patient_name: 'Ravi Kumar', scopes: null },
    ]);
    render(
      <AuthContext.Provider value={auth({ name: 'Meera', role: 'family_member' })}>
        <FamilyDashboard />
      </AuthContext.Provider>
    );

    expect(await screen.findByText('Ravi Kumar')).toBeInTheDocument();
    expect(screen.getByText(/Permitted scopes:\s*none reported/)).toBeInTheDocument();
  });

  it('reports a failed list instead of "No family records are currently shared with you"', async () => {
    patientsApi.getAccessible.mockRejectedValue(new Error('Network down'));
    render(
      <AuthContext.Provider value={auth({ name: 'Meera', role: 'family_member' })}>
        <FamilyDashboard />
      </AuthContext.Provider>
    );

    expect(await screen.findByText(/Could not load your shared family records/i)).toBeInTheDocument();
    expect(
      screen.queryByText('No family records are currently shared with you.')
    ).not.toBeInTheDocument();
  });
});
