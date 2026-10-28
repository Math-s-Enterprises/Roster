import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
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
  // `keepSignedIn` picks the store - see setToken in lib/api.
  const completeSignIn = useCallback((data, keepSignedIn = true) => {
    setToken(data.token, keepSignedIn);
    setUser(data.user);
    // Signing in to an account that was waiting to be deleted cancels the deletion: the server
    // does it, and says so. Say so here too, or it would happen without anyone being told.
    if (data.restored) {
      toast.success(
        "Welcome back. The deletion is cancelled and your account is restored. Your subscription stays cancelled.",
        { duration: 10000 },
      );
    }
    return data.user;
  }, []);

  const login = useCallback(
    async (email, password, keepSignedIn = true) =>
      completeSignIn(
        (await api.post("/auth/login", { email, password })).data,
        keepSignedIn,
      ),
    [completeSignIn],
  );

  const signup = useCallback(
    async (payload) => {
      const { data } = await api.post("/auth/signup", payload);
      // With email confirmation on, nothing exists yet: the server has emailed a link, and the
      // account (and the sign-in) only happen when it is clicked. See verifyEmail below.
      if (data.verification_sent) return data;
      // A new shop opens in light mode. Only here, and only once the account
      // exists - a failed sign-up must not change anyone's saved preference.
      try {
        localStorage.setItem("roster_theme", "light");
      } catch {
        /* storage unavailable (private mode) - nothing to set */
      }
      return completeSignIn(data);
    },
    [completeSignIn],
  );

  // `credential` is the ID token issued by Google Identity Services in the
  // browser. The backend verifies its signature before trusting it.
  const loginWithGoogle = useCallback(
    async (credential, password) => {
      const { data } = await api.post("/auth/google", {
        credential, ...(password === undefined ? {} : { password }),
      });
      return data.password_required ? data : completeSignIn(data);
    },
    [completeSignIn],
  );

  // Both return the backend's message so the page can show it verbatim -
  // forgot-password's response is deliberately generic (see the backend) and
  // must not be reworded into something more specific by the UI.
  const forgotPassword = useCallback(
    async (email) => (await api.post("/auth/forgot-password", { email })).data,
    [],
  );

  // The confirmation link was clicked. This is where the account is really made, so it does what
  // sign-up used to do: a new shop opens in light mode, and the person is signed in.
  const verifyEmail = useCallback(
    async (token) => {
      const { data } = await api.post("/auth/verify-email", { token });
      try {
        localStorage.setItem("roster_theme", "light");
      } catch {
        /* storage unavailable (private mode) - nothing to set */
      }
      return completeSignIn(data);
    },
    [completeSignIn],
  );

  const resendVerification = useCallback(
    async (email) => (await api.post("/auth/resend-verification", { email })).data,
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
      forgotPassword, resetPassword, verifyEmail, resendVerification,
    }),
    [
      user, loading, providers, login, signup, loginWithGoogle, logout, refresh,
      forgotPassword, resetPassword, verifyEmail, resendVerification,
    ],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
};
