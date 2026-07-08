import React, { createContext, useState, useEffect, useContext } from "react";

const AuthContext = createContext(null);
const API_BASE = import.meta.env.VITE_API_URL || "/api/v1";

export const AuthProvider = ({ children }) => {
  const [user, setUser]       = useState(null);
  const [token, setToken]     = useState(null);
  const [loading, setLoading] = useState(true);

  // ── Authenticated fetch with auto-refresh ──────────────────────────────
  const authFetch = async (url, options = {}) => {
    let headers = { "Content-Type": "application/json", ...options.headers };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let response = await fetch(`${API_BASE}${url}`, { ...options, headers });

    if (response.status === 401 && !url.includes("/auth/login") && !url.includes("/auth/refresh")) {
      const refreshed = await refreshToken();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${refreshed}`;
        response = await fetch(`${API_BASE}${url}`, { ...options, headers });
      } else {
        logout();
      }
    }
    return response;
  };

  const refreshToken = async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });
      if (response.ok) {
        const data = await response.json();
        setToken(data.access_token);
        return data.access_token;
      }
    } catch (_) {}
    return null;
  };

  const checkAuth = async () => {
    setLoading(true);
    const activeToken = await refreshToken();
    if (activeToken) {
      try {
        const response = await fetch(`${API_BASE}/auth/me`, {
          headers: { Authorization: `Bearer ${activeToken}` },
          credentials: "include",
        });
        if (response.ok) setUser(await response.json());
      } catch (_) {}
    }
    setLoading(false);
  };

  const login = async (username, password) => {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const data = await response.json();
      let errMsg = "Authentication failed";
      if (data?.detail) {
        errMsg = Array.isArray(data.detail)
          ? data.detail.map(e => e.msg).join(", ")
          : data.detail;
      }
      throw new Error(errMsg);
    }

    const data = await response.json();
    setToken(data.access_token);

    const profileResponse = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${data.access_token}` },
      credentials: "include",
    });
    if (profileResponse.ok) setUser(await profileResponse.json());
    return true;
  };

  const logout = async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
    } catch (_) {}
    setToken(null);
    setUser(null);
  };

  useEffect(() => { checkAuth(); }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, logout, authFetch, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
