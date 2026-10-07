import React, { useEffect, useId, useRef, useState } from "react";
import "@/styles/legal.css";

/**
 * The agreement at sign-up, and the legal line under the sign-in card.
 *
 * WHAT THE CHECKBOX IS — AND IS NOT
 *
 * It records that the business accepts the Terms of Service (a contract,
 * which includes the data processing terms GDPR Article 28 requires between a
 * business and a service that holds its staff's data) and has been shown the
 * Privacy Policy (the notice Article 13 requires at the point data is
 * collected).
 *
 * It is deliberately NOT a GDPR "consent" box. Consent is the wrong legal
 * basis for running a service someone has signed up to: consent must be
 * freely given and separate from other terms, and it cannot be a condition of
 * using the service. Running the account rests on the contract instead. If
 * Roster ever sends marketing email, that needs its own, separate, unticked,
 * optional box — never this one.
 *
 * It starts unticked (pre-ticked boxes do not count as agreement) and the
 * links open in a new tab, so reading the terms does not lose what has been
 * typed into the form.
 *
 * HOW IT STOPS THE FORM
 *
 * While unticked it listens for its form's submit event and cancels it,
 * before the form's own React onSubmit runs, shows why, and moves focus to
 * itself. React handles events at the root of the app, so a listener on the
 * form element itself runs first and can stop the event reaching React. That
 * keeps the change to Login.js to one line: <ConsentCheckbox />.
 */

const Tick = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3.2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
);

const NewTab = ({ href, children }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className="legal-link">
    {children}
  </a>
);

export function ConsentCheckbox() {
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState(false);
  const input = useRef(null);
  const id = useId();

  useEffect(() => {
    const form = input.current?.closest("form");
    if (!form) return undefined;
    const guard = (event) => {
      if (input.current?.checked) return;
      event.preventDefault();
      event.stopPropagation();
      setError(true);
      input.current?.focus();
    };
    form.addEventListener("submit", guard);
    return () => form.removeEventListener("submit", guard);
  }, []);

  return (
    <div className="legal-consent">
      <label className="si-check legal-consent-label">
        <input
          ref={input}
          type="checkbox"
          data-testid="consent-terms"
          checked={checked}
          onChange={(event) => {
            setChecked(event.target.checked);
            if (event.target.checked) setError(false);
          }}
          aria-invalid={error}
          aria-describedby={error ? `${id}-error` : undefined}
        />
        <span className="si-box" aria-hidden="true">{checked && <Tick />}</span>
        <span className="legal-consent-text">
          I agree to the <NewTab href="/terms">Terms of Service</NewTab>, including the data
          processing terms, on behalf of my business, and I have read the{" "}
          <NewTab href="/privacy">Privacy Policy</NewTab>.
        </span>
      </label>
      {error && (
        <p id={`${id}-error`} className="si-field-error" role="alert">
          Tick the box to agree to the Terms of Service before creating your account.
        </p>
      )}
    </div>
  );
}

/**
 * Replaces the "Staff do not sign in" line under the card, keeping that line
 * and adding the legal one. Google sign-in can create an account without
 * passing the checkbox, so this tells people what continuing with Google
 * means.
 */
export function LegalNote() {
  return (
    <>
      <p className="si-note">Staff do not sign in — they get their roster by email.</p>
      <p className="legal-note">
        Signing in or continuing with Google means you accept the{" "}
        <NewTab href="/terms">Terms of Service</NewTab> and have read the{" "}
        <NewTab href="/privacy">Privacy Policy</NewTab>.
      </p>
    </>
  );
}
