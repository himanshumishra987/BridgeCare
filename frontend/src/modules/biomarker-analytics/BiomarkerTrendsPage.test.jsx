import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthContext } from '../../context/AuthContext';
import BiomarkerTrendsPage from './BiomarkerTrendsPage';
import { biomarkersApi } from '../../api/biomarkers';

vi.mock('../../api/biomarkers', () => ({
  biomarkersApi: { getAll: vi.fn(), getSeries: vi.fn() },
}));

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <BiomarkerTrendsPage />
    </AuthContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  biomarkersApi.getAll.mockResolvedValue([]);
});

describe('BiomarkerTrendsPage states', () => {
  it('shows the empty state only for a genuinely empty successful response', async () => {
    renderPage();
    expect(await screen.findByText('No biomarker data yet')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports a failed request instead of "No biomarker data yet"', async () => {
    biomarkersApi.getAll.mockRejectedValue(
      Object.assign(new Error('Lab service unavailable'), { status: 503 })
    );
    renderPage();

    expect(await screen.findByText(/Could not load your biomarker trends/i)).toBeInTheDocument();
    expect(screen.getByText(/Lab service unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('No biomarker data yet')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('reports a malformed successful payload instead of an empty chart list', async () => {
    biomarkersApi.getAll.mockResolvedValue({ series: [] });
    renderPage();

    expect(
      await screen.findByText(/unexpected response when loading your biomarker trends/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No biomarker data yet')).not.toBeInTheDocument();
  });

  it('reports a malformed series entry instead of charting it as empty', async () => {
    biomarkersApi.getAll.mockResolvedValue([null]);
    renderPage();

    expect(
      await screen.findByText(/biomarker record was returned in an unexpected shape/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No measurements yet')).not.toBeInTheDocument();
  });
});
