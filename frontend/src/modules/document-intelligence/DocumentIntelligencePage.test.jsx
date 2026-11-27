import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthContext } from '../../context/AuthContext';
import DocumentIntelligencePage from './DocumentIntelligencePage';
import { documentsApi } from '../../api/documents';
import { documentSecurityApi } from '../../api/documentSecurity';

vi.mock('../../api/documents', () => ({
  documentsApi: {
    list: vi.fn(),
    upload: vi.fn(),
    getExtraction: vi.fn(),
    verify: vi.fn(),
    reject: vi.fn(),
    checkDuplicate: vi.fn(),
  },
}));

vi.mock('../../api/documentSecurity', () => ({
  documentSecurityApi: { get: vi.fn(), retry: vi.fn() },
}));

const DOC = {
  id: 'd1',
  original_filename: 'lab-2026.pdf',
  document_type: 'lab_report',
  file_size_bytes: 2048,
  processing_status: 'processed',
  verification_status: 'pending',
};

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <DocumentIntelligencePage />
    </AuthContext.Provider>
  );
}

async function openDocument(user) {
  await user.click(await screen.findByText('lab-2026.pdf'));
}

beforeEach(() => {
  vi.clearAllMocks();
  documentsApi.list.mockResolvedValue([DOC]);
  documentsApi.getExtraction.mockResolvedValue(null);
  documentSecurityApi.get.mockResolvedValue({ status: 'cleared' });
});

describe('DocumentIntelligencePage list states', () => {
  it('shows an empty state only for a genuinely empty successful list', async () => {
    documentsApi.list.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('No documents yet')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports a failed list request instead of "No documents yet"', async () => {
    documentsApi.list.mockRejectedValue(Object.assign(new Error('Database down'), { status: 500 }));
    renderPage();

    expect(await screen.findByText(/Could not load your documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Database down/)).toBeInTheDocument();
    expect(screen.queryByText('No documents yet')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('reports a malformed successful list instead of rendering it as empty', async () => {
    documentsApi.list.mockResolvedValue({ items: [] });
    renderPage();

    expect(
      await screen.findByText(/unexpected response when loading your documents/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No documents yet')).not.toBeInTheDocument();
  });
});

describe('DocumentIntelligencePage screening gates', () => {
  const blocked = [
    ['pending_scan', 'Queued for screening'],
    ['scanning', 'Screening in progress'],
    ['quarantined', 'Quarantined'],
    ['rejected', 'Rejected — malicious file'],
    ['inconclusive', 'Inconclusive — human review needed'],
    ['human_review', 'Awaiting human review'],
  ];

  it.each(blocked)('blocks preview and download while the file is %s', async (status, label) => {
    const user = userEvent.setup();
    documentSecurityApi.get.mockResolvedValue({ status });
    renderPage();
    await openDocument(user);

    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download original/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /load preview/i })).toBeDisabled();
    expect(screen.getByText(/Download and preview are withheld/i)).toBeInTheDocument();
  });

  it('blocks preview and download when the screening endpoint fails', async () => {
    const user = userEvent.setup();
    documentSecurityApi.get.mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }));
    renderPage();
    await openDocument(user);

    expect(await screen.findByText('Security status unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download original/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /load preview/i })).toBeDisabled();
  });

  it('blocks when the decision omits a status entirely', async () => {
    const user = userEvent.setup();
    documentSecurityApi.get.mockResolvedValue({ scanner_available: true });
    renderPage();
    await openDocument(user);

    expect(await screen.findByText('Security status unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download original/i })).toBeDisabled();
  });

  it('unlocks preview and download only for an explicit cleared decision', async () => {
    const user = userEvent.setup();
    renderPage();
    await openDocument(user);

    expect(await screen.findByText('Screening cleared')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download original/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /load preview/i })).toBeEnabled();
    expect(screen.queryByText(/Download and preview are withheld/i)).not.toBeInTheDocument();
  });
});
