import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
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

  const login = async (email, password, expectedRole) => {
    const data = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
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
