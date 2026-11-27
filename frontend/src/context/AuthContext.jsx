import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  SESSION_EXPIRED_EVENT,
  apiRequest,
  clearStoredTokens,
  getStoredTokens,
  setStoredTokens,
} from '../api/client';

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadCurrentUser = useCallback(async () => {
    const { accessToken } = getStoredTokens();
    if (!accessToken) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await apiRequest('/auth/me');
      // A malformed user payload signs the session out instead of rendering a
      // half-populated account with missing role/profile fields.
      if (!me || typeof me !== 'object' || typeof me.role !== 'string' || !me.role) {
        throw new Error('The server returned an unexpected account response.');
      }
      setUser(me);
    } catch {
      clearStoredTokens();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCurrentUser();
  }, [loadCurrentUser]);

  // The API client clears tokens when a refresh fails; drop the user too so
  // ProtectedRoute redirects instead of leaving a signed-in shell that 401s.
  useEffect(() => {
    const handleSessionExpired = () => {
      setUser(null);
      setLoading(false);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, []);

  const login = async (email, password, expectedRole) => {
    const data = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    // A malformed success must not store a token or a half-built user.
    if (!data || typeof data.access_token !== 'string' || !data.access_token) {
      throw new Error('The server returned an unexpected sign-in response.');
    }
    if (!data.user || typeof data.user !== 'object' || typeof data.user.role !== 'string') {
      throw new Error('The server returned an unexpected account response.');
    }
    // Reject a wrong-role sign-in before any token is stored
    if (expectedRole && data.user.role !== expectedRole) {
      throw new Error('This account does not match the selected role. Go back and choose another.');
    }
    setStoredTokens(data.access_token, data.refresh_token);
    setUser(data.user);
    return data.user;
  };

  const register = async (payload) => {
    const data = await apiRequest('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (!data || typeof data.access_token !== 'string' || !data.access_token) {
      throw new Error('The server returned an unexpected registration response.');
    }
    if (!data.user || typeof data.user !== 'object') {
      throw new Error('The server returned an unexpected account response.');
    }
    setStoredTokens(data.access_token, data.refresh_token);
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    const { refreshToken } = getStoredTokens();
    try {
      await apiRequest('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Clear local session regardless of network outcome
    } finally {
      clearStoredTokens();
      setUser(null);
    }
  };

  const updateProfile = async (payload) => {
    const updated = await apiRequest('/auth/profile', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    if (!updated || typeof updated !== 'object' || typeof updated.role !== 'string') {
      // Keep the last known-good account rather than replacing it with garbage.
      throw new Error('The server returned an unexpected account response.');
    }
    setUser(updated);
    return updated;
  };

  return (
    <AuthContext.Provider
      value={{ user, loading, login, register, logout, updateProfile, reloadUser: loadCurrentUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return ctx;
}
