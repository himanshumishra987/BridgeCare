import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthContext } from '../context/AuthContext';
import { holisticApi } from '../api/holistic';
import HolisticPreview from './HolisticPreview';

const METHODS = ['getAll', 'addRecord', 'getHerbs', 'addHerb', 'getWarnings'];

afterEach(() => {
  vi.restoreAllMocks();
});

describe('HolisticPreview isolation', () => {
  it('never replaces or calls the real holisticApi singleton', async () => {
    const getAllSpy = vi.spyOn(holisticApi, 'getAll');
    const addRecordSpy = vi.spyOn(holisticApi, 'addRecord');
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    // Baseline captured after the spies so identity comparison is meaningful.
    const before = Object.fromEntries(METHODS.map((name) => [name, holisticApi[name]]));

    render(
      <AuthContext.Provider value={{ user: { patient_profile: { id: 'real-patient' } }, loading: false }}>
        <HolisticPreview />
      </AuthContext.Provider>
    );

    expect(await screen.findByText(/Preview mode: nothing is sent to a server/i)).toBeInTheDocument();

    // Every shared method is still the same function object, not a memory stub.
    for (const name of METHODS) {
      expect(holisticApi[name]).toBe(before[name]);
    }
    expect(Object.keys(holisticApi).sort()).toEqual([...METHODS].sort());
    expect(getAllSpy).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    // Writing through the preview must not reach the real client either.
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /add ayush record/i }));
    // Every required field must be filled or the browser blocks submit.
    fireEvent.change(screen.getByLabelText(/Care system/i), { target: { value: 'Ayurveda' } });
    // fireEvent.change because jsdom's segmented date input ignores typed digits.
    fireEvent.change(screen.getByLabelText(/^Title$/i), { target: { value: 'Preview-only record' } });
    fireEvent.change(screen.getByLabelText(/^Date$/i), { target: { value: '2026-11-02' } });
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() =>
      expect(screen.getByText(/Record added. It is user-entered and not verified/i)).toBeInTheDocument()
    );
    expect(addRecordSpy).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    for (const name of METHODS) {
      expect(holisticApi[name]).toBe(before[name]);
    }
  });

  it('reports interaction checking as unavailable instead of pretending there are no warnings', async () => {
    render(
      <AuthContext.Provider value={{ user: null, loading: false }}>
        <HolisticPreview />
      </AuthContext.Provider>
    );

    expect(
      await screen.findByText(/Interaction warnings are not available/i)
    ).toBeInTheDocument();
  });
});
