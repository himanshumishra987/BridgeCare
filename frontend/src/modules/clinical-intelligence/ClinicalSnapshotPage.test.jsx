import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthContext } from '../../context/AuthContext';
import ClinicalSnapshotPage from './ClinicalSnapshotPage';
import { clinicalApi } from '../../api/clinical';

vi.mock('../../api/clinical', () => ({
  clinicalApi: { getSummary: vi.fn(), ask: vi.fn() },
}));

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <ClinicalSnapshotPage />
    </AuthContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ClinicalSnapshotPage states', () => {
  it('reads a 404 on the single summary as "no summary yet", with no error', async () => {
    clinicalApi.getSummary.mockRejectedValue(
      Object.assign(new Error('Not Found'), { status: 404 })
    );
    renderPage();

    expect(await screen.findByText('No summary available')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/Could not load your clinical snapshot/i)).not.toBeInTheDocument();
  });

  it('reports a failed request instead of "No summary available"', async () => {
    clinicalApi.getSummary.mockRejectedValue(
      Object.assign(new Error('AI engine down'), { status: 500 })
    );
    renderPage();

    expect(await screen.findByText(/Could not load your clinical snapshot/i)).toBeInTheDocument();
    expect(screen.getByText(/AI engine down/)).toBeInTheDocument();
    expect(screen.queryByText('No summary available')).not.toBeInTheDocument();
  });

  it('reports 501 as an unsupported capability, not an empty summary', async () => {
    clinicalApi.getSummary.mockRejectedValue(
      Object.assign(new Error('Not Implemented'), { status: 501 })
    );
    renderPage();

    expect(await screen.findByText(/Not available yet/i)).toBeInTheDocument();
    expect(screen.queryByText('No summary available')).not.toBeInTheDocument();
  });

  it('reports a malformed successful payload instead of an empty summary', async () => {
    clinicalApi.getSummary.mockResolvedValue('summary-as-a-string');
    renderPage();

    expect(
      await screen.findByText(/unexpected response when loading your clinical snapshot/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No summary available')).not.toBeInTheDocument();
  });
});
