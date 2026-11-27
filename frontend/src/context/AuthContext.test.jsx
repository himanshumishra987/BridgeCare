import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { SESSION_EXPIRED_EVENT } from '../api/client';

const BASE = 'http://localhost:8000/api/v1';

let auth;
let fetchMock;

function Capture() {
  auth = useAuth();
  return null;
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function loginResponse(role = 'patient') {
  return json({
    access_token: 'access-1',
    refresh_token: 'refresh-1',
    user: { id: 'u1', email: 'person@bridgecare.local', role, profile_completed: true },
  });
}

async function renderAuth() {
  render(
    <AuthProvider>
      <Capture />
    </AuthProvider>
  );
  await waitFor(() => expect(auth.loading).toBe(false));
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  localStorage.clear();
});

describe('AuthProvider', () => {
  it('starts signed out when no token is stored', async () => {
    await renderAuth();
    expect(auth.user).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('stores both tokens and the user on a successful login', async () => {
    fetchMock.mockResolvedValueOnce(loginResponse('patient'));
    await renderAuth();

    await act(async () => {
      await auth.login('person@bridgecare.local', 'secret', 'patient');
    });

    expect(localStorage.getItem('bridgecare_access_token')).toBe('access-1');
    expect(localStorage.getItem('bridgecare_refresh_token')).toBe('refresh-1');
    expect(auth.user.role).toBe('patient');
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/auth/login`);
  });

  it('rejects a wrong-role sign-in before storing any token', async () => {
    fetchMock.mockResolvedValueOnce(loginResponse('doctor_navigator'));
    await renderAuth();

    await act(async () => {
      await expect(auth.login('person@bridgecare.local', 'secret', 'patient')).rejects.toThrow(
        /does not match the selected role/
      );
    });

    expect(localStorage.getItem('bridgecare_access_token')).toBeNull();
    expect(auth.user).toBeNull();
  });

  it('clears the local session even when the logout request fails', async () => {
    fetchMock.mockResolvedValueOnce(loginResponse('patient'));
    await renderAuth();
    await act(async () => {
      await auth.login('person@bridgecare.local', 'secret', 'patient');
    });
    fetchMock.mockResolvedValueOnce(json({ detail: 'boom' }, 500));

    await act(async () => {
      await auth.logout();
    });

    expect(localStorage.getItem('bridgecare_access_token')).toBeNull();
    expect(auth.user).toBeNull();
  });

  it('drops the signed-in user when the API reports an expired session', async () => {
    fetchMock.mockResolvedValueOnce(loginResponse('patient'));
    await renderAuth();
    await act(async () => {
      await auth.login('person@bridgecare.local', 'secret', 'patient');
    });
    expect(auth.user).not.toBeNull();

    act(() => {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
    });

    await waitFor(() => expect(auth.user).toBeNull());
    expect(auth.loading).toBe(false);
  });
});
