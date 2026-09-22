import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import AuthShell from "@/components/AuthShell";
import { RESET_PASSWORD } from "@/constants/testIds/auth";

/**
 * Reset password — reached from the emailed link, the sign-in page's frame.
 *
 * On success it hands a message to the sign-in page rather than toasting
 * here and navigating away, where the toast would be gone before anyone
 * read it.
 */

const Lock = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);
const Arrow = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export default function ResetPassword() {
  const { resetPassword } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});

  const clear = () => { setError(null); setFieldErrors({}); };

  const submit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    const next = {};
    if (password.length < 8) next.password = "Use at least 8 characters.";
    if (!confirm) next.confirm = "Type the new password again.";
    else if (password !== confirm) next.confirm = "The two passwords do not match.";
    setFieldErrors(next);
    if (Object.keys(next).length) return;

    setSubmitting(true);
    setError(null);
    try {
      await resetPassword(token, password);
      navigate("/login", {
        replace: true,
        state: { notice: "Password reset — sign in with your new password." },
      });
    } catch (err) {
      setError(errorMessage(err, "This link has expired or already been used. Request a new one."));
    } finally {
      setSubmitting(false);
    }
  };

  const inputType = showPassword ? "text" : "password";

  return (
    <AuthShell single>
      <form className="si-card" onSubmit={submit} noValidate>
        <h2 className="si-h2">Choose a new password</h2>

        {!token ? (
          <>
            <p className="si-form-error" role="alert">
              This link is missing its reset token, so it cannot be used. Request a new one.
            </p>
            <Link to="/forgot-password" data-testid={RESET_PASSWORD.loginLink} className="si-cta">
              Request a new link <Arrow />
            </Link>
            <p className="si-note">
              <Link to="/login" className="si-link">Back to sign in</Link>
            </p>
          </>
        ) : (
          <>
            <p className="si-card-sub">At least 8 characters. You'll sign in with it next.</p>

            <div className="si-field">
              <div className="si-label-row">
                <label className="si-label" htmlFor="rp-password">New password</label>
                <button
                  type="button"
                  className="si-toggle"
                  aria-pressed={showPassword}
                  aria-controls="rp-password rp-confirm"
                  onClick={() => setShowPassword((v) => !v)}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              <div className="si-input" data-invalid={Boolean(fieldErrors.password)}>
                <Lock />
                <input
                  id="rp-password"
                  data-testid={RESET_PASSWORD.passwordInput}
                  type={inputType}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); clear(); }}
                  autoComplete="new-password"
                  autoFocus
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby={fieldErrors.password ? "rp-password-err" : undefined}
                />
              </div>
              {fieldErrors.password && <p id="rp-password-err" className="si-field-error">{fieldErrors.password}</p>}
            </div>

            <div className="si-field">
              <div className="si-label-row">
                <label className="si-label" htmlFor="rp-confirm">Confirm new password</label>
              </div>
              <div className="si-input" data-invalid={Boolean(fieldErrors.confirm)}>
                <Lock />
                <input
                  id="rp-confirm"
                  data-testid={RESET_PASSWORD.passwordConfirmInput}
                  type={inputType}
                  value={confirm}
                  onChange={(e) => { setConfirm(e.target.value); clear(); }}
                  autoComplete="new-password"
                  aria-invalid={Boolean(fieldErrors.confirm)}
                  aria-describedby={fieldErrors.confirm ? "rp-confirm-err" : undefined}
                />
              </div>
              {fieldErrors.confirm && <p id="rp-confirm-err" className="si-field-error">{fieldErrors.confirm}</p>}
            </div>

            <p className="si-form-error" aria-live="polite">{error}</p>

            <button
              type="submit"
              data-testid={RESET_PASSWORD.submitButton}
              className="si-cta"
              disabled={submitting}
              aria-busy={submitting}
            >
              {submitting ? (
                <>
                  <span className="si-spinner" aria-hidden="true" />
                  <span className="sr-only">Resetting your password</span>
                </>
              ) : (
                <>Reset password <Arrow /></>
              )}
            </button>

            <p className="si-note">
              <Link to="/login" data-testid={RESET_PASSWORD.loginLink} className="si-link">
                Back to sign in
              </Link>
            </p>
          </>
        )}
      </form>
    </AuthShell>
  );
}
