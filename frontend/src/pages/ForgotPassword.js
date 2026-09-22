import React, { useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import AuthShell from "@/components/AuthShell";
import { FORGOT_PASSWORD } from "@/constants/testIds/auth";

/**
 * Forgot password — the sign-in page's frame, one card.
 *
 * The confirmation says "if an account exists" on purpose. The backend
 * answers identically whether or not the address is registered, and the
 * page must not undo that by phrasing the two cases differently.
 */

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const Mail = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" />
  </svg>
);
const Arrow = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export default function ForgotPassword() {
  const { forgotPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  const [fieldError, setFieldError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    const address = email.trim();
    if (!address) { setFieldError("Enter your email address."); return; }
    if (!EMAIL_SHAPE.test(address)) { setFieldError("That does not look like an email address."); return; }
    setSubmitting(true);
    setError(null);
    try {
      await forgotPassword(address);
      setSent(true);
    } catch (err) {
      setError(errorMessage(err, "Could not send the reset email. Try again in a moment."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell single>
      <form className="si-card" onSubmit={submit} noValidate>
        <h2 className="si-h2">Reset your password</h2>

        {sent ? (
          <>
            <p className="si-form-ok" role="status">
              If an account exists for <strong>{email.trim()}</strong>, we've sent a link to reset your
              password. It expires in an hour.
            </p>
            <p className="si-card-sub" style={{ marginTop: 14 }}>
              Nothing there? Check your spam folder, or send it again.
            </p>
            <button type="button" className="si-cta" onClick={() => setSent(false)}>
              Send it again
            </button>
            <p className="si-note">
              <Link to="/login" data-testid={FORGOT_PASSWORD.loginLink} className="si-link">
                Back to sign in
              </Link>
            </p>
          </>
        ) : (
          <>
            <p className="si-card-sub">
              Enter the email on your account and we'll send you a link to reset your password.
            </p>

            <div className="si-field">
              <div className="si-label-row">
                <label className="si-label" htmlFor="fp-email">Email</label>
              </div>
              <div className="si-input" data-invalid={Boolean(fieldError)}>
                <Mail />
                <input
                  id="fp-email"
                  data-testid={FORGOT_PASSWORD.emailInput}
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setFieldError(null); setError(null); }}
                  placeholder="you@yourshop.ie"
                  autoComplete="email"
                  autoFocus
                  aria-invalid={Boolean(fieldError)}
                  aria-describedby={fieldError ? "fp-email-err" : undefined}
                />
              </div>
              {fieldError && <p id="fp-email-err" className="si-field-error">{fieldError}</p>}
            </div>

            <p className="si-form-error" aria-live="polite">{error}</p>

            <button
              type="submit"
              data-testid={FORGOT_PASSWORD.submitButton}
              className="si-cta"
              disabled={submitting}
              aria-busy={submitting}
            >
              {submitting ? (
                <>
                  <span className="si-spinner" aria-hidden="true" />
                  <span className="sr-only">Sending the reset link</span>
                </>
              ) : (
                <>Send reset link <Arrow /></>
              )}
            </button>

            <p className="si-note">
              Remembered it?{" "}
              <Link to="/login" data-testid={FORGOT_PASSWORD.loginLink} className="si-link">
                Sign in
              </Link>
            </p>
          </>
        )}
      </form>
    </AuthShell>
  );
}
