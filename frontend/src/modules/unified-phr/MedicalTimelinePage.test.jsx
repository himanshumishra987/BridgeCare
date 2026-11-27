import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AuthContext } from '../../context/AuthContext';
import MedicalTimelinePage from './MedicalTimelinePage';
import { timelineApi } from '../../api/timeline';

vi.mock('../../api/timeline', () => ({
  timelineApi: { get: vi.fn(), getEpisode: vi.fn() },
}));

const ITEM = {
  id: 't1',
  title: 'Blood test',
  document_type: 'lab_report',
  date: '2026-10-01',
  verification_status: 'verified',
};

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <MedicalTimelinePage />
    </AuthContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  timelineApi.get.mockResolvedValue([]);
  timelineApi.getEpisode.mockResolvedValue(ITEM);
});

describe('MedicalTimelinePage states', () => {
  it('shows the empty state only for a genuinely empty successful response', async () => {
    renderPage();
    expect(await screen.findByText('No records found')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports a failed request instead of "No records found"', async () => {
    timelineApi.get.mockRejectedValue(Object.assign(new Error('Database down'), { status: 500 }));
    renderPage();

    expect(await screen.findByText(/Could not load your medical timeline/i)).toBeInTheDocument();
    expect(screen.getByText(/Database down/)).toBeInTheDocument();
    expect(screen.queryByText('No records found')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('reports a malformed successful payload instead of an empty timeline', async () => {
    timelineApi.get.mockResolvedValue({ records: [] });
    renderPage();

    expect(
      await screen.findByText(/unexpected response when loading your medical timeline/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No records found')).not.toBeInTheDocument();
  });

  it('keeps the records already loaded when a filtered refresh fails', async () => {
    timelineApi.get.mockResolvedValueOnce([ITEM]);
    renderPage();
    expect(await screen.findByText('Blood test')).toBeInTheDocument();

    timelineApi.get.mockRejectedValue(Object.assign(new Error('Search failed'), { status: 500 }));
    fireEvent.change(screen.getByPlaceholderText(/Search timeline/i), {
      target: { value: 'blood' },
    });

    expect(await screen.findByText(/Could not load your medical timeline/i)).toBeInTheDocument();
    expect(screen.getByText('Blood test')).toBeInTheDocument();
    expect(screen.getByText(/Showing records loaded earlier/i)).toBeInTheDocument();
  });

  it('reports a malformed timeline entry instead of crashing the list', async () => {
    timelineApi.get.mockResolvedValue([null]);
    renderPage();

    expect(
      await screen.findByText(/timeline record was returned in an unexpected shape/i)
    ).toBeInTheDocument();
  });
});

describe('MedicalTimelinePage episode detail', () => {
  it('does not silently swallow a failed episode request', async () => {
    timelineApi.get.mockResolvedValue([ITEM]);
    timelineApi.getEpisode.mockRejectedValue(new Error('Episode unavailable'));
    renderPage();

    fireEvent.click(await screen.findByText('Blood test'));

    expect(
      await screen.findByText(/Linked episode details could not be loaded: Episode unavailable/i)
    ).toBeInTheDocument();
    // The basic record stays visible in the list as well as in the detail panel.
    expect(screen.getAllByText('Blood test').length).toBeGreaterThan(0);
  });
});
