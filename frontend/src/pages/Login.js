import React, { useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { errorMessage } from "@/lib/api";
import GoogleSignInButton from "@/components/GoogleSignInButton";
import AuthShell from "@/components/AuthShell";
import { LOGIN } from "@/constants/testIds/auth";

/**
 * Sign in (handoff: Sign in, doodle background).
 *
 * Beige and terracotta over a hand-drawn pattern of roster motifs, one
 * centred column: hero, card, capability chips, a "Trusted by" marquee.
 * Managers only — the page says plainly that staff never sign in.
 *
 * No app data is fetched here. Everything on the page before sign-in is
 * static, so nothing about any shop is visible to someone at /login.
 *
 * Creating an account stays on this page, switched from the top-right link
 * as the handoff places it. There is no separate sign-up route in this app,
 * and this is the only way a new shop registers.
 *
 * "Keep me signed in" is real: it decides whether the token is kept in
 * localStorage (survives closing the browser) or sessionStorage (cleared
 * when it closes). See setToken in lib/api.
 */

// Marketing copy lives here so changing it never touches the layout.
const CONTENT = {
  capabilities: [
    { label: "Age curfews", swatch: "#b84415" },
    { label: "Hour caps", swatch: "#d2551f" },
    { label: "Fixed shifts", swatch: "#e0b384" },
    { label: "Full-day coverage", swatch: "#8c3410" },
  ],
  trustedBy: ["Top Oil", "South Link", "Centra", "Eddie's Rockets"],
};

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** A same-origin path only — never follow a redirect off the site. */
function safeRedirect(value) {
  if (!value || typeof value !== "string") return null;
  return value.startsWith("/") && !value.startsWith("//") ? value : null;
}

const Mail = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" />
  </svg>
);
const Lock = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);
const Person = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" />
  </svg>
);
const Shop = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 9l2-5h14l2 5" /><path d="M4 9v11h16V9" /><path d="M9 20v-6h6v6" />
  </svg>
);
const Tick = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
);
const Arrow = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export default function Login() {
  const { login, signup, loginWithGoogle, providers } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const passwordRef = useRef(null);

  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({
    email: "", password: "", name: "", shopName: "", keepSignedIn: true,
  });
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | submitting | error
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});

  const isSignup = mode === "signup";
  const submitting = status === "submitting";

  // Where to go afterwards: a same-origin ?redirectTo=, then wherever the
  // login wall interrupted, then the dashboard.
  const params = new URLSearchParams(location.search);
  const returnTo = safeRedirect(params.get("redirectTo"))
    || location.state?.from?.pathname
    || "/";
  const notice = location.state?.notice || null;

  const update = (field) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
    if (fieldErrors[field]) setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
    if (status === "error") { setStatus("idle"); setError(null); }
  };

  const switchMode = (next) => {
    setMode(next);
    setStatus("idle");
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
    setStatus("submitting");
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
        await login(form.email.trim(), form.password, form.keepSignedIn);
      }
      navigate(returnTo, { replace: true });
    } catch (err) {
      // Sign-in never says which half was wrong — confirming an email exists
      // tells an attacker which addresses to try. Sign-up keeps the server's
      // reason, because "that email is taken" is the useful answer there.
      setStatus("error");
      setError(
        isSignup
          ? errorMessage(err, "Could not create the account.")
          : "That email and password do not match.",
      );
      // The email is never cleared; the password is where the fix goes.
      if (!isSignup) requestAnimationFrame(() => passwordRef.current?.focus());
    }
  };

  const handleGoogleCredential = async (credential) => {
    setStatus("submitting");
    setError(null);
    try {
      await loginWithGoogle(credential);
      navigate(returnTo, { replace: true });
    } catch (err) {
      setStatus("error");
      setError(errorMessage(err, "Google sign-in did not work. Try your email and password."));
    }
  };

  const barRight = isSignup ? (
    <>Have an account?{" "}
      <button type="button" data-testid="tab-login" className="si-link" onClick={() => switchMode("login")}>
        Sign in
      </button>
    </>
  ) : (
    <>New shop?{" "}
      <button type="button" data-testid="tab-signup" className="si-link" onClick={() => switchMode("signup")}>
        Create an account
      </button>
    </>
  );

  return (
    <AuthShell barRight={barRight}>
      <section className="si-hero">
        <span className="si-pill">
          <span className="si-pill-dot" aria-hidden="true" />
          AI-ASSISTED WORKFORCE SCHEDULING
        </span>
        <h1 className="si-h1">
          Fully covered weekly rosters in{" "}
          <span className="si-h1-mark">
            under five minutes
            <svg viewBox="0 0 300 12" preserveAspectRatio="none" aria-hidden="true">
              <path
                d="M2 8.5c58-5 96-6.5 148-5.5s96 3.5 148 6"
                fill="none" stroke="#b84415" strokeOpacity=".45" strokeWidth="3.2" strokeLinecap="round"
              />
            </svg>
          </span>
          .
        </h1>
        <p className="si-sub">
          Set up your shop, staff and policies. Roster schedules the team while respecting every legal
          limit, holiday and preference — and never leaves the shop unattended.
        </p>
      </section>

      <form className="si-card" onSubmit={submit} noValidate>
        <h2 className="si-h2">{isSignup ? "Create your shop" : "Sign in to your shop"}</h2>
        {isSignup && (
          <p className="si-card-sub">You'll set up staff and opening hours next.</p>
        )}

        {notice && !error && <p className="si-form-ok" role="status">{notice}</p>}

        {isSignup && (
          <>
            <div className="si-field">
              <div className="si-label-row">
                <label className="si-label" htmlFor="si-name">Your name</label>
              </div>
              <div className="si-input" data-invalid={Boolean(fieldErrors.name)}>
                <Person />
                <input
                  id="si-name" data-testid="input-name" value={form.name} onChange={update("name")}
                  autoComplete="name" aria-invalid={Boolean(fieldErrors.name)}
                  aria-describedby={fieldErrors.name ? "si-name-err" : undefined}
                />
              </div>
              {fieldErrors.name && <p id="si-name-err" className="si-field-error">{fieldErrors.name}</p>}
            </div>
            <div className="si-field">
              <div className="si-label-row">
                <label className="si-label" htmlFor="si-shop">Shop name</label>
              </div>
              <div className="si-input" data-invalid={Boolean(fieldErrors.shopName)}>
                <Shop />
                <input
                  id="si-shop" data-testid="input-shop" value={form.shopName} onChange={update("shopName")}
                  placeholder="e.g. Eddie's Rockets, Main Street" autoComplete="organization"
                  aria-invalid={Boolean(fieldErrors.shopName)}
                  aria-describedby={fieldErrors.shopName ? "si-shop-err" : undefined}
                />
              </div>
              {fieldErrors.shopName && <p id="si-shop-err" className="si-field-error">{fieldErrors.shopName}</p>}
            </div>
          </>
        )}

        <div className="si-field">
          <div className="si-label-row">
            <label className="si-label" htmlFor="si-email">Email</label>
          </div>
          <div className="si-input" data-invalid={Boolean(fieldErrors.email)}>
            <Mail />
            <input
              id="si-email" data-testid="input-email" type="email" value={form.email}
              onChange={update("email")} placeholder="you@yourshop.ie" autoComplete="email"
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? "si-email-err" : undefined}
            />
          </div>
          {fieldErrors.email && <p id="si-email-err" className="si-field-error">{fieldErrors.email}</p>}
        </div>

        <div className="si-field">
          <div className="si-label-row">
            <label className="si-label" htmlFor="si-password">Password</label>
            <button
              type="button" className="si-toggle" aria-pressed={showPassword} aria-controls="si-password"
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          <div className="si-input" data-invalid={Boolean(fieldErrors.password)}>
            <Lock />
            <input
              id="si-password" ref={passwordRef} data-testid="input-password"
              type={showPassword ? "text" : "password"} value={form.password} onChange={update("password")}
              autoComplete={isSignup ? "new-password" : "current-password"}
              aria-invalid={Boolean(fieldErrors.password)}
              aria-describedby={fieldErrors.password ? "si-password-err" : undefined}
            />
          </div>
          {fieldErrors.password
            ? <p id="si-password-err" className="si-field-error">{fieldErrors.password}</p>
            : isSignup && <p className="si-hint">At least 8 characters.</p>}
        </div>

        {!isSignup && (
          <div className="si-options">
            <label className="si-check">
              <input type="checkbox" checked={form.keepSignedIn} onChange={update("keepSignedIn")} />
              <span className="si-box" aria-hidden="true">{form.keepSignedIn && <Tick />}</span>
              <span className="si-check-label">Keep me signed in</span>
            </label>
            <Link to="/forgot-password" data-testid={LOGIN.forgotPasswordLink} className="si-link">
              Forgot password?
            </Link>
          </div>
        )}

        <p className="si-form-error" aria-live="polite">{error}</p>

        <button
          type="submit" data-testid="submit-auth" className="si-cta"
          disabled={submitting} aria-busy={submitting}
        >
          {submitting ? (
            <>
              <span className="si-spinner" aria-hidden="true" />
              <span className="sr-only">{isSignup ? "Creating your account" : "Signing in"}</span>
            </>
          ) : (
            <>{isSignup ? "Create account" : "Sign in"} <Arrow /></>
          )}
        </button>

        {/* Only when the backend says Google is configured. */}
        {providers?.google && providers?.google_client_id && (
          <>
            <div className="si-divider">or</div>
            <GoogleSignInButton
              clientId={providers.google_client_id}
              onCredential={handleGoogleCredential}
              disabled={submitting}
            />
          </>
        )}

        <p className="si-note">Staff do not sign in — they get their roster by email.</p>
      </form>

      <div className="si-chips">
        {CONTENT.capabilities.map((c) => (
          <span key={c.label} className="si-chip">
            <span className="si-chip-dot" style={{ background: c.swatch }} aria-hidden="true" />
            {c.label}
          </span>
        ))}
      </div>

      <section className="si-trusted" aria-label="Trusted by">
        <p className="si-trusted-label">TRUSTED BY</p>
        <div className="si-marquee">
          <div className="si-marquee-row">
            {/* Two identical halves so the loop is seamless. The second is
                hidden from assistive tech — it is the same list again. */}
            {[0, 1].map((half) => (
              <div key={half} className="si-marquee-half" aria-hidden={half === 1 ? "true" : undefined}>
                {CONTENT.trustedBy.map((name) => (
                  <span key={name} className="si-tile">{name}</span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>
    </AuthShell>
  );
}
