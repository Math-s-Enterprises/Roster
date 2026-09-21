import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import GoogleSignInButton from "@/components/GoogleSignInButton";
import AuthShell, { AuthCard } from "@/components/AuthShell";
import { LOGIN } from "@/constants/testIds/auth";

/**
 * Sign in (handoff: Login page).
 *
 * The one screen that deliberately leaves the approved black/hairline
 * system for its own indigo-to-teal ground. It looks the same in both
 * themes: all copy sits on the vignette's dark ground, so it stays
 * readable whatever the stored theme is. Styles are scoped to .lg-*.
 *
 * This page must not fetch shop data before sign-in — the figures earlier
 * drafts showed would have leaked a shop's numbers to anyone at /login.
 *
 * KEPT FROM THE PREVIOUS PAGE, THOUGH THE HANDOFF DOES NOT SHOW THEM
 *
 * - Creating an account. The handoff is sign-in only, but this page is the
 *   only way a new shop registers; dropping it would leave nobody able to
 *   sign up. It is a link under the card that switches the same form into
 *   sign-up mode rather than a second tab strip.
 * - Google sign-in, rendered only when the backend reports it configured.
 *
 * LEFT OUT, DELIBERATELY
 *
 * - "Keep me signed in". The handoff wants it to control refresh-token
 *   lifetime, and the backend has no such setting — there is no refresh
 *   token and no remember flag on /auth/login. A checkbox that changed
 *   nothing would tell someone on a shared computer they will be signed out
 *   when they will not be, which is worse than not offering it.
 */

const CAPABILITIES = [
  { label: "Age curfews", colour: "#4ff0c0" },
  { label: "Hour caps", colour: "#7c5cff" },
  { label: "Fixed shifts", colour: "#ff6aa8" },
  { label: "Full-day coverage", colour: "#ffc36a" },
];

const Envelope = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="M3 7l9 6 9-6" />
  </svg>
);
const Padlock = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="10" width="16" height="11" rx="2" />
    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);
const Person = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </svg>
);
const Shopfront = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 9l2-5h14l2 5" />
    <path d="M4 9v11h16V9" />
    <path d="M9 20v-6h6v6" />
  </svg>
);
const Arrow = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Login() {
  const { login, signup, loginWithGoogle, providers } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", name: "", shopName: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});

  const isSignup = mode === "signup";

  // Where the user was heading before the login wall, or the dashboard.
  const returnTo = location.state?.from?.pathname || "/";
  const notice = location.state?.notice || null;

  const update = (field) => (event) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }));
    if (fieldErrors[field]) setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
    if (error) setError(null);
  };

  const switchMode = (next) => {
    setMode(next);
    setError(null);
    setFieldErrors({});
  };

  const validate = () => {
    const next = {};
    if (isSignup && !form.name.trim()) next.name = "Enter your name.";
    if (isSignup && !form.shopName.trim()) next.shopName = "Enter the shop's name.";
    if (!form.email.trim()) next.email = "Enter your email address.";
    else if (!EMAIL_SHAPE.test(form.email.trim())) next.email = "That does not look like an email address.";
    if (!form.password) next.password = "Enter your password.";
    else if (isSignup && form.password.length < 8) next.password = "Use at least 8 characters.";
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  };

  const submit = async (event) => {
    event.preventDefault();
    if (submitting || !validate()) return;
    setSubmitting(true);
    setError(null);
    try {
      if (isSignup) {
        await signup({
          email: form.email.trim(),
          password: form.password,
          name: form.name.trim(),
          shop_name: form.shopName.trim(),
        });
      } else {
        await login(form.email.trim(), form.password);
      }
      navigate(returnTo, { replace: true });
    } catch (err) {
      // Sign-in never says which half was wrong — telling someone the email
      // exists is telling an attacker which addresses to try. Sign-up keeps
      // the server's message, since "that email is taken" is the point there.
      setError(
        isSignup
          ? errorMessage(err, "Could not create the account.")
          : "Email or password is not right.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleCredential = async (credential) => {
    setSubmitting(true);
    setError(null);
    try {
      await loginWithGoogle(credential);
      navigate(returnTo, { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Google sign-in did not work. Try your email and password."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    // No "Trouble signing in?" in the bar: it went to the same page as the
    // Forgot password link in the card, and meant nothing on sign-up, where
    // there is no password yet to have trouble with. The card link is the
    // one kept — it sits beside the field it is about, and hides itself in
    // sign-up mode.
    <AuthShell>
          <section>
            <span className="lg-pill">
              <span className="lg-pill-dot" aria-hidden="true" />
              AI-ASSISTED WORKFORCE SCHEDULING
            </span>
            <h1 className="lg-h1">
              Fully covered weekly rosters in <span className="lg-h1-grad">under five minutes</span>.
            </h1>
            <p className="lg-lead">
              Set up your shop, staff and policies. Roster schedules the team while respecting every
              legal limit, holiday and preference — and never leaves the shop unattended.
            </p>
            <div className="lg-chips">
              {CAPABILITIES.map((c) => (
                <span key={c.label} className="lg-chip">
                  <span className="lg-chip-dot" style={{ background: c.colour }} aria-hidden="true" />
                  {c.label}
                </span>
              ))}
            </div>
          </section>

          <AuthCard as="form" onSubmit={submit} noValidate>
              <h2 className="lg-h2">{isSignup ? "Create your shop" : "Sign in to your shop"}</h2>
              <p className="lg-card-sub">
                {isSignup
                  ? "You'll set up staff and opening hours next."
                  : "Manager access — staff get their roster by email."}
              </p>

              {notice && !error && <p className="lg-form-ok" role="status">{notice}</p>}
              {error && <p className="lg-form-error" role="alert">{error}</p>}

              {isSignup && (
                <>
                  <div className="lg-field">
                    <div className="lg-label-row">
                      <label className="lg-label" htmlFor="lg-name">Your name</label>
                    </div>
                    <div className="lg-input" data-invalid={Boolean(fieldErrors.name)}>
                      <Person />
                      <input
                        id="lg-name"
                        data-testid="input-name"
                        value={form.name}
                        onChange={update("name")}
                        autoComplete="name"
                        aria-invalid={Boolean(fieldErrors.name)}
                        aria-describedby={fieldErrors.name ? "lg-name-err" : undefined}
                      />
                    </div>
                    {fieldErrors.name && <p id="lg-name-err" className="lg-field-error">{fieldErrors.name}</p>}
                  </div>

                  <div className="lg-field">
                    <div className="lg-label-row">
                      <label className="lg-label" htmlFor="lg-shop">Shop name</label>
                    </div>
                    <div className="lg-input" data-invalid={Boolean(fieldErrors.shopName)}>
                      <Shopfront />
                      <input
                        id="lg-shop"
                        data-testid="input-shop"
                        value={form.shopName}
                        onChange={update("shopName")}
                        placeholder="e.g. Metro Tech Retail"
                        autoComplete="organization"
                        aria-invalid={Boolean(fieldErrors.shopName)}
                        aria-describedby={fieldErrors.shopName ? "lg-shop-err" : undefined}
                      />
                    </div>
                    {fieldErrors.shopName && <p id="lg-shop-err" className="lg-field-error">{fieldErrors.shopName}</p>}
                  </div>
                </>
              )}

              <div className="lg-field">
                <div className="lg-label-row">
                  <label className="lg-label" htmlFor="lg-email">Email</label>
                </div>
                <div className="lg-input" data-invalid={Boolean(fieldErrors.email)}>
                  <Envelope />
                  <input
                    id="lg-email"
                    data-testid="input-email"
                    type="email"
                    value={form.email}
                    onChange={update("email")}
                    autoComplete="email"
                    aria-invalid={Boolean(fieldErrors.email)}
                    aria-describedby={fieldErrors.email ? "lg-email-err" : undefined}
                  />
                </div>
                {fieldErrors.email && <p id="lg-email-err" className="lg-field-error">{fieldErrors.email}</p>}
              </div>

              <div className="lg-field">
                <div className="lg-label-row">
                  <label className="lg-label" htmlFor="lg-password">Password</label>
                  <button
                    type="button"
                    className="lg-toggle"
                    aria-pressed={showPassword}
                    aria-controls="lg-password"
                    onClick={() => setShowPassword((v) => !v)}
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                <div className="lg-input" data-invalid={Boolean(fieldErrors.password)}>
                  <Padlock />
                  <input
                    id="lg-password"
                    data-testid="input-password"
                    type={showPassword ? "text" : "password"}
                    value={form.password}
                    onChange={update("password")}
                    autoComplete={isSignup ? "new-password" : "current-password"}
                    aria-invalid={Boolean(fieldErrors.password)}
                    aria-describedby={fieldErrors.password ? "lg-password-err" : undefined}
                  />
                </div>
                {fieldErrors.password
                  ? <p id="lg-password-err" className="lg-field-error">{fieldErrors.password}</p>
                  : isSignup && <p className="lg-hint">At least 8 characters.</p>}
              </div>

              {!isSignup && (
                <div className="lg-options">
                  <Link
                    to="/forgot-password"
                    data-testid={LOGIN.forgotPasswordLink}
                    className="lg-link"
                  >
                    Forgot password?
                  </Link>
                </div>
              )}

              <button
                type="submit"
                data-testid="submit-auth"
                className="lg-cta"
                disabled={submitting}
                aria-busy={submitting}
              >
                {submitting ? (
                  <>
                    <span className="lg-spinner" aria-hidden="true" />
                    <span className="sr-only">{isSignup ? "Creating your account" : "Signing in"}</span>
                  </>
                ) : (
                  <>
                    {isSignup ? "Create account" : "Sign in"}
                    <Arrow />
                  </>
                )}
              </button>

              {/* Only when the backend says Google is configured, so nobody is
                  offered a button that cannot work. */}
              {providers?.google && providers?.google_client_id && (
                <>
                  <div className="lg-divider">or</div>
                  <GoogleSignInButton
                    clientId={providers.google_client_id}
                    onCredential={handleGoogleCredential}
                    disabled={submitting}
                  />
                </>
              )}

              <p className="lg-switch">
                {isSignup ? (
                  <>
                    Already have an account?{" "}
                    <button type="button" data-testid="tab-login" className="lg-link" onClick={() => switchMode("login")}>
                      Sign in
                    </button>
                  </>
                ) : (
                  <>
                    New to Roster?{" "}
                    <button
                      type="button"
                      data-testid="tab-signup"
                      className="lg-link"
                      onClick={() => switchMode("signup")}
                    >
                      Create an account
                    </button>
                  </>
                )}
              </p>
          </AuthCard>
    </AuthShell>
  );
}
