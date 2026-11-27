import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthContext } from '../../context/AuthContext';
import HolisticHealthPage from './HolisticHealthPage';

// The service is injected through the `api` prop, the same seam the DEV preview
// uses, so no network is involved and the singleton is untouched.
function makeApi(overrides = {}) {
  return {
    getAll: vi.fn().mockResolvedValue([]),
    addRecord: vi.fn().mockResolvedValue(undefined),
    getHerbs: vi.fn().mockResolvedValue([]),
    addHerb: vi.fn().mockResolvedValue(undefined),
    getWarnings: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
}

const notImplemented = () =>
  Object.assign(new Error('Not Implemented'), { status: 501 });

const notFound = () => Object.assign(new Error('Not Found'), { status: 404 });

function renderPage(api) {
  return render(
    <AuthContext.Provider value={{ user: { patient_profile: { id: 'p1' } }, loading: false }}>
      <HolisticHealthPage api={api} />
    </AuthContext.Provider>
  );
}

let api;

beforeEach(() => {
  api = makeApi();
});

describe('HolisticHealthPage error semantics', () => {
  it('treats HTTP 501 on warnings as an unsupported capability, not "no interactions"', async () => {
    api.getWarnings.mockRejectedValue(notImplemented());
    renderPage(api);

    expect(
      await screen.findByText(/Interaction warnings are not available/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/No warnings were returned/i)).not.toBeInTheDocument();
  });

  it('reports a 404 on the holistic-records collection as a failure, not an empty tab', async () => {
    api.getAll.mockRejectedValue(notFound());
    renderPage(api);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not load holistic records/i);
    expect(screen.getByText(/route is not registered/i)).toBeInTheDocument();
    expect(screen.queryByText(/No AYUSH \/ Traditional records yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/i)).not.toBeInTheDocument();
  });

  it('recovers through Retry after a failed load', async () => {
    const user = userEvent.setup();
    api.getAll.mockRejectedValueOnce(notFound());
    renderPage(api);

    const retry = await screen.findByRole('button', { name: /retry/i });
    api.getAll.mockResolvedValue([]);
    await user.click(retry);

    expect(await screen.findByText(/No AYUSH \/ Traditional records yet/i)).toBeInTheDocument();
    expect(api.getAll).toHaveBeenCalledTimes(2);
  });

  it('reports a malformed successful payload instead of rendering an empty tab', async () => {
    api.getAll.mockResolvedValue({ records: [] });
    renderPage(api);

    expect(
      await screen.findByText(/unexpected response when loading holistic records/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/No AYUSH \/ Traditional records yet/i)).not.toBeInTheDocument();
  });

  it('shows the genuine empty state only for a successful empty list', async () => {
    renderPage(api);

    expect(await screen.findByText(/No AYUSH \/ Traditional records yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('HolisticHealthPage injected API', () => {
  it('saves a record through the injected API, never a module singleton', async () => {
    const user = userEvent.setup();
    renderPage(api);

    await user.click(await screen.findByRole('button', { name: /add ayush record/i }));
    // Every required field must be filled or the browser blocks submit.
    fireEvent.change(screen.getByLabelText(/Care system/i), { target: { value: 'Ayurveda' } });
    // fireEvent.change because jsdom's segmented date input ignores typed digits.
    fireEvent.change(screen.getByLabelText(/^Title$/i), { target: { value: 'Morning yoga' } });
    fireEvent.change(screen.getByLabelText(/^Date$/i), { target: { value: '2026-11-01' } });
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(api.addRecord).toHaveBeenCalledTimes(1));
    const [patientId, payload] = api.addRecord.mock.calls[0];
    expect(patientId).toBe('p1');
    expect(payload).toMatchObject({ title: 'Morning yoga', system: 'ayush' });
  });
});
