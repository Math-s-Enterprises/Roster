import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { KeyRound } from "lucide-react";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import { RESET_PASSWORD } from "@/constants/testIds/auth";

export default function ResetPassword() {
  const { resetPassword } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (password !== confirm) {
      toast.error("Passwords don't match");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(token, password);
      toast.success("Password reset. Log in with your new password.");
      navigate("/login", { replace: true });
    } catch (err) {
      toast.error(errorMessage(err, "Could not reset your password"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen relative overflow-hidden flex items-center justify-center px-8">
      <div className="absolute inset-0 -z-10 bg-black/80" />
      <div className="glass rounded-3xl p-8 md:p-10 max-w-md w-full">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass text-xs text-cyan-400 mb-6">
          <KeyRound size={12} /> Choose a new password
        </div>

        {!token ? (
          <div className="space-y-4">
            <p className="text-white/80">
              This link is missing its reset token. Request a new one from the login page.
            </p>
            <Link
              to="/forgot-password"
              data-testid={RESET_PASSWORD.loginLink}
              className="text-sm text-cyan-400 hover:text-cyan-300"
            >
              Request a new link
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-xs text-white/60">New password</label>
              <input
                data-testid={RESET_PASSWORD.passwordInput}
                required
                type="password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full px-4 py-3 rounded-xl"
                autoComplete="new-password"
                autoFocus
              />
              <p className="text-[11px] text-white/40 mt-1">At least 8 characters.</p>
            </div>
            <div>
              <label className="text-xs text-white/60">Confirm new password</label>
              <input
                data-testid={RESET_PASSWORD.passwordConfirmInput}
                required
                type="password"
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="mt-1 w-full px-4 py-3 rounded-xl"
                autoComplete="new-password"
              />
            </div>
            <button
              type="submit"
              data-testid={RESET_PASSWORD.submitButton}
              disabled={busy}
              className="neon-btn w-full py-3 rounded-full flex items-center justify-center gap-2 mt-2 disabled:opacity-60"
            >
              {busy ? "Resetting…" : "Reset password"}
            </button>
            <Link
              to="/login"
              data-testid={RESET_PASSWORD.loginLink}
              className="block text-center text-sm text-white/50 hover:text-white/70 pt-2"
            >
              Back to log in
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}
