import React, { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Mail, Send } from "lucide-react";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import { FORGOT_PASSWORD } from "@/constants/testIds/auth";

export default function ForgotPassword() {
  const { forgotPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await forgotPassword(email);
      // The backend's response is deliberately identical whether or not the
      // account exists, so the UI never learns (and can't leak) which.
      setSent(true);
    } catch (err) {
      toast.error(errorMessage(err, "Could not send the reset email"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen relative overflow-hidden flex items-center justify-center px-8">
      <div className="absolute inset-0 -z-10 bg-black/80" />
      <div className="glass rounded-3xl p-8 md:p-10 max-w-md w-full">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass text-xs text-cyan-400 mb-6">
          <Mail size={12} /> Reset your password
        </div>

        {sent ? (
          <div className="space-y-4">
            <p className="text-white/80">
              If an account exists for <span className="text-white">{email}</span>, we've sent
              a link to reset your password. It expires in an hour.
            </p>
            <Link
              to="/login"
              data-testid={FORGOT_PASSWORD.loginLink}
              className="text-sm text-cyan-400 hover:text-cyan-300"
            >
              Back to log in
            </Link>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <p className="text-white/60 text-sm">
              Enter the email on your account and we'll send you a link to reset your password.
            </p>
            <div>
              <label className="text-xs text-white/60">Email</label>
              <input
                data-testid={FORGOT_PASSWORD.emailInput}
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full px-4 py-3 rounded-xl"
                autoComplete="email"
                autoFocus
              />
            </div>
            <button
              type="submit"
              data-testid={FORGOT_PASSWORD.submitButton}
              disabled={busy}
              className="neon-btn w-full py-3 rounded-full flex items-center justify-center gap-2 mt-2 disabled:opacity-60"
            >
              <Send size={16} />
              {busy ? "Sending…" : "Send reset link"}
            </button>
            <Link
              to="/login"
              data-testid={FORGOT_PASSWORD.loginLink}
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
