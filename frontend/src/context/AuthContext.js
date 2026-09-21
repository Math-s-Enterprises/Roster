import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, clearToken, setToken } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [providers, setProviders] = useState({ password: true, google: false });

  // Ask the backend which sign-in methods are actually configured, so the UI
  // can hide a Google button that would fail on click.
  useEffect(() => {
    let cancelled = false;
    api
      .get("/auth/providers")
      .then((r) => !cancelled && setProviders(r.data))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get("/auth/me");
      setUser(r.data);
      return r.data;
    } catch {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Every sign-in path ends the same way: store the token, set the user.
  const completeSignIn = useCallback((data) => {
    setToken(data.token);
    setUser(data.user);
    return data.user;
  }, []);

  const login = useCallback(
    async (email, password) =>
      completeSignIn((await api.post("/auth/login", { email, password })).data),
    [completeSignIn],
  );

  const signup = useCallback(
    async (payload) => {
      const { data } = await api.post("/auth/signup", payload);
      // A new shop opens in light mode. Only here, and only once the account
      // exists — a failed sign-up must not change anyone's saved preference.
      try {
        localStorage.setItem("roster_theme", "light");
      } catch {
        /* storage unavailable (private mode) — nothing to set */
      }
      return completeSignIn(data);
    },
    [completeSignIn],
  );

  // `credential` is the ID token issued by Google Identity Services in the
  // browser. The backend verifies its signature before trusting it.
  const loginWithGoogle = useCallback(
    async (credential) =>
      completeSignIn((await api.post("/auth/google", { credential })).data),
    [completeSignIn],
  );

  // Both return the backend's message so the page can show it verbatim —
  // forgot-password's response is deliberately generic (see the backend) and
  // must not be reworded into something more specific by the UI.
  const forgotPassword = useCallback(
    async (email) => (await api.post("/auth/forgot-password", { email })).data,
    [],
  );

  const resetPassword = useCallback(
    async (token, password) =>
      (await api.post("/auth/reset-password", { token, password })).data,
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Clearing local credentials matters more than the server round-trip.
    }
    clearToken();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user, loading, providers, login, signup, loginWithGoogle, logout, refresh, setUser,
      forgotPassword, resetPassword,
    }),
    [user, loading, providers, login, signup, loginWithGoogle, logout, refresh, forgotPassword, resetPassword],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
};
