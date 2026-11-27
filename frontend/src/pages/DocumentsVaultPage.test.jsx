import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthContext } from '../context/AuthContext';
import DocumentsVaultPage from './DocumentsVaultPage';
import { documentsApi } from '../api/documents';
import { getSecurityForDocuments } from '../api/documentSecurity';

vi.mock('../api/documents', () => ({
  documentsApi: { list: vi.fn(), upload: vi.fn() },
}));

vi.mock('../api/documentSecurity', () => ({
  getSecurityForDocuments: vi.fn(),
  documentSecurityApi: { get: vi.fn(), retry: vi.fn() },
}));

const DOC = {
  id: 'd1',
  original_filename: 'discharge.pdf',
  document_type: 'discharge_summary',
  file_size_bytes: 4096,
  processing_status: 'processed',
  verification_status: 'verified',
};

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <DocumentsVaultPage />
    </AuthContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  documentsApi.list.mockResolvedValue([DOC]);
  getSecurityForDocuments.mockResolvedValue({ d1: { status: 'cleared' } });
});

describe('DocumentsVaultPage states', () => {
  it('reports a failed list request instead of "No documents uploaded yet"', async () => {
    documentsApi.list.mockRejectedValue(Object.assign(new Error('Offline'), { status: 503 }));
    renderPage();

    expect(await screen.findByText(/Could not load your stored documents/i)).toBeInTheDocument();
    expect(screen.queryByText('No documents uploaded yet.')).not.toBeInTheDocument();
  });

  it('reports a malformed successful list instead of an empty vault', async () => {
    documentsApi.list.mockResolvedValue('not-a-list');
    renderPage();

    expect(
      await screen.findByText(/unexpected response when loading your stored documents/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No documents uploaded yet.')).not.toBeInTheDocument();
  });

  it('shows the empty state for a genuine empty success', async () => {
    documentsApi.list.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('No documents uploaded yet.')).toBeInTheDocument();
  });
});

describe('DocumentsVaultPage download gating', () => {
  const blocked = [
    ['pending_scan', 'screening: pending_scan'],
    ['scanning', 'screening: scanning'],
    ['quarantined', 'screening: quarantined'],
    ['rejected', 'screening: rejected'],
    ['inconclusive', 'screening: inconclusive'],
    ['human_review', 'screening: human_review'],
  ];

  it.each(blocked)('disables download while the file is %s', async (status, label) => {
    getSecurityForDocuments.mockResolvedValue({ d1: { status } });
    renderPage();

    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download/i })).toBeDisabled();
    expect(screen.getByText(/Withheld until screening clears/i)).toBeInTheDocument();
  });

  it('disables download when the screening lookup failed', async () => {
    getSecurityForDocuments.mockResolvedValue({ d1: null });
    renderPage();

    expect(await screen.findByText(/screening status unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download/i })).toBeDisabled();
  });

  it('enables download only for a cleared file', async () => {
    renderPage();

    expect(await screen.findByText('Screening cleared')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download/i })).toBeEnabled();
  });
});
