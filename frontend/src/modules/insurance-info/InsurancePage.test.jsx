import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthContext } from '../../context/AuthContext';
import InsurancePage from './InsurancePage';
import { insuranceApi } from '../../api/insurance';

// The HTTP contract is covered by src/api/insurance.test.js; here the service is
// mocked so each load/validation state can be driven deterministically.
vi.mock('../../api/insurance', () => ({
  insuranceApi: {
    getPolicies: vi.fn(),
    addPolicy: vi.fn(),
    extractPolicy: vi.fn(),
    getExpenses: vi.fn(),
    getClaims: vi.fn(),
    getMedicalCard: vi.fn(),
    saveMedicalCard: vi.fn(),
    uploadCardDocument: vi.fn(),
  },
}));

// 501 is the backend saying "this capability is not implemented".
const notImplemented = () =>
  Object.assign(new Error('Not Implemented'), { status: 501, payload: { detail: 'Not Implemented' } });

// 404 is a missing resource: empty for a single-record endpoint, ambiguous for a list.
const notFound = () =>
  Object.assign(new Error('Not Found'), { status: 404, payload: { detail: 'Not Found' } });

function respond({ policies = [], expenses = [], claims = [], card = null } = {}) {
  insuranceApi.getPolicies.mockResolvedValue(policies);
  insuranceApi.getExpenses.mockResolvedValue(expenses);
  insuranceApi.getClaims.mockResolvedValue(claims);
  insuranceApi.getMedicalCard.mockResolvedValue(card);
}

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <InsurancePage />
    </AuthContext.Provider>
  );
}

const openSavedTab = (user) =>
  user.click(screen.getByRole('tab', { name: /saved insurance/i }));

beforeEach(() => {
  vi.clearAllMocks();
  respond();
});

describe('InsurancePage load states', () => {
  it('shows the unavailable state, not an empty record, when the endpoint is not implemented', async () => {
    const user = userEvent.setup();
    insuranceApi.getPolicies.mockRejectedValue(notImplemented());
    renderPage();

    await openSavedTab(user);

    expect(await screen.findByText(/Not available yet/i)).toBeInTheDocument();
    expect(screen.queryByText('No saved insurance')).not.toBeInTheDocument();
  });

  it('reports a 404 on a list endpoint as a failure, not as unavailable or empty', async () => {
    const user = userEvent.setup();
    insuranceApi.getPolicies.mockRejectedValue(notFound());
    renderPage();

    await openSavedTab(user);

    expect(await screen.findByText(/Could not load saved insurance/i)).toBeInTheDocument();
    expect(screen.getByText(/route is not registered/i)).toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText('No saved insurance')).not.toBeInTheDocument();
  });

  it('shows the empty state for a genuinely empty successful response', async () => {
    const user = userEvent.setup();
    renderPage();

    await openSavedTab(user);

    expect(await screen.findByText('No saved insurance')).toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/i)).not.toBeInTheDocument();
  });

  it('reports a failed request per section instead of "no expenses recorded"', async () => {
    const user = userEvent.setup();
    insuranceApi.getExpenses.mockRejectedValue(
      Object.assign(new Error('Database down'), { status: 500 })
    );
    renderPage();

    await openSavedTab(user);

    expect(await screen.findByText(/Could not load expenses/i)).toBeInTheDocument();
    expect(screen.getByText(/Database down/)).toBeInTheDocument();
    expect(screen.queryByText('No expenses recorded')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /retry/i }).length).toBeGreaterThan(0);
  });
});

describe('InsurancePage validation and save', () => {
  it('blocks a policy whose valid until date is before valid from', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Insurer \/ scheme name/i), 'Acme Health');
    await user.type(screen.getByLabelText(/Policy number/i), 'AC-1');
    await user.clear(screen.getByLabelText(/Valid from/i));
    await user.type(screen.getByLabelText(/Valid from/i), '2026-05-01');
    await user.type(screen.getByLabelText(/Valid until/i), '2026-04-01');
    await user.click(screen.getByRole('button', { name: /save insurance/i }));

    expect(await screen.findByText(/cannot be before/i)).toBeInTheDocument();
    expect(insuranceApi.addPolicy).not.toHaveBeenCalled();
  });

  it('saves a manual policy as patient-confirmed and never as insurer-verified', async () => {
    const user = userEvent.setup();
    insuranceApi.addPolicy.mockResolvedValue({ id: 'new' });
    renderPage();

    await user.type(screen.getByLabelText(/Insurer \/ scheme name/i), 'Acme Health');
    await user.type(screen.getByLabelText(/Policy number/i), 'AC-1');
    await user.type(screen.getByLabelText(/Sum insured for the whole policy/i), '500000');
    await user.click(screen.getByRole('button', { name: /save insurance/i }));

    await waitFor(() => expect(insuranceApi.addPolicy).toHaveBeenCalledTimes(1));
    const [, payload] = insuranceApi.addPolicy.mock.calls[0];
    expect(payload).toMatchObject({
      insurer: 'Acme Health',
      policy_number: 'AC-1',
      sum_insured: 500000,
      source: 'manual',
      verification_status: 'patient_confirmed',
      document_id: null,
    });
    expect(payload.verification_status).not.toBe('insurer_verified');
    expect(await screen.findByText(/patient-confirmed, not insurer-verified/i)).toBeInTheDocument();
  });
});

describe('InsurancePage medical card', () => {
  it('shows the saved card, including attached document names', async () => {
    const user = userEvent.setup();
    respond({
      card: {
        holder_name: 'Asha Rao',
        card_number: 'MC-7788',
        issued_by: 'Acme TPA',
        valid_until: '2027-03-31',
        documents: [{ id: 'd1', filename: 'card-front.png' }],
      },
    });
    renderPage();

    await user.click(screen.getByRole('tab', { name: /medical card/i }));

    expect(await screen.findByText('Asha Rao')).toBeInTheDocument();
    expect(screen.getByText('MC-7788')).toBeInTheDocument();
    expect(screen.getByText('card-front.png')).toBeInTheDocument();
  });

  it('reports an unimplemented medical card endpoint instead of an unsaved card', async () => {
    const user = userEvent.setup();
    insuranceApi.getMedicalCard.mockRejectedValue(notImplemented());
    renderPage();

    await user.click(screen.getByRole('tab', { name: /medical card/i }));

    expect(await screen.findByText(/Not available yet/i)).toBeInTheDocument();
    expect(screen.queryByText('No medical card added yet.')).not.toBeInTheDocument();
  });

  it('reads a 404 for the single medical card as "no card saved yet"', async () => {
    const user = userEvent.setup();
    insuranceApi.getMedicalCard.mockRejectedValue(notFound());
    renderPage();

    await user.click(screen.getByRole('tab', { name: /medical card/i }));

    expect(await screen.findByText('No medical card added yet.')).toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Could not load the medical card/i)).not.toBeInTheDocument();
  });

  it('saves a medical card with blank fields normalised to null', async () => {
    const user = userEvent.setup();
    insuranceApi.saveMedicalCard.mockImplementation((_id, data) => Promise.resolve(data));
    renderPage();

    await user.click(screen.getByRole('tab', { name: /medical card/i }));
    await user.click(await screen.findByRole('button', { name: /^add$/i }));

    await user.type(screen.getByLabelText(/Card holder name/i), 'Asha Rao');
    await user.type(screen.getByLabelText(/Medical card number/i), 'MC-7788');
    await user.click(screen.getByRole('button', { name: /save medical card/i }));

    await waitFor(() => expect(insuranceApi.saveMedicalCard).toHaveBeenCalledTimes(1));
    const [patientId, payload] = insuranceApi.saveMedicalCard.mock.calls[0];
    expect(patientId).toBe('p1');
    expect(payload).toMatchObject({
      holder_name: 'Asha Rao',
      card_number: 'MC-7788',
      issued_by: null,
      valid_until: null,
    });
    // No document was attached, so no document_id is claimed.
    expect(payload).not.toHaveProperty('document_id');
    expect(await screen.findByText(/not insurer-verified/i)).toBeInTheDocument();
  });
});
