import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthContext } from '../../context/AuthContext';
import MedicationsPage from './MedicationsPage';
import { medicationsApi } from '../../api/medications';

vi.mock('../../api/medications', () => ({
  medicationsApi: {
    getAll: vi.fn(),
    addReminder: vi.fn(),
    dismissInteraction: vi.fn(),
  },
}));

const emptyPayload = () => ({ current: [], previous: [], interactions: [], duplicates: [] });

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <MedicationsPage />
    </AuthContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  medicationsApi.getAll.mockResolvedValue(emptyPayload());
});

describe('MedicationsPage states', () => {
  it('shows the empty state only for a genuinely empty successful response', async () => {
    renderPage();
    expect(await screen.findByText('No current medications')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports a failed request instead of "No current medications"', async () => {
    medicationsApi.getAll.mockRejectedValue(
      Object.assign(new Error('Prescription service down'), { status: 500 })
    );
    renderPage();

    expect(await screen.findByText(/Could not load your medications/i)).toBeInTheDocument();
    expect(screen.getByText(/Prescription service down/)).toBeInTheDocument();
    expect(screen.queryByText('No current medications')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('reports a malformed successful payload instead of an empty medication list', async () => {
    medicationsApi.getAll.mockResolvedValue([]);
    renderPage();

    expect(
      await screen.findByText(/unexpected response when loading your medications/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No current medications')).not.toBeInTheDocument();
  });

  it('survives a null list and an interaction without a drugs array', async () => {
    medicationsApi.getAll.mockResolvedValue({
      current: null,
      previous: undefined,
      interactions: [{ description: 'Bleeding risk reported without a drug list' }],
      duplicates: null,
    });
    renderPage();

    expect(
      await screen.findByText('Bleeding risk reported without a drug list')
    ).toBeInTheDocument();
    expect(screen.getByText('Interaction reported')).toBeInTheDocument();
    expect(screen.getByText('No current medications')).toBeInTheDocument();
  });
});
