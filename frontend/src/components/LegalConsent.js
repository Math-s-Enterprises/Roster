import React, { useId, useState } from "react";
import "@/styles/legal.css";
import LegalDialog from "@/components/LegalDialog";

/**
 * The agreement at sign-up, and the legal line under the sign-in card.
 *
 * WHAT THE CHECKBOX IS - AND IS NOT
 *
 * It records that the business accepts the Terms of Service (a contract, which
 * includes the data processing terms GDPR Article 28 requires between a
 * business and a service that holds its staff's data) and has been shown the
 * Privacy Policy (the notice Article 13 requires at the point data is
 * collected).
 *
 * It is deliberately NOT a GDPR "consent" box. Consent is the wrong legal basis
 * for running a service someone has signed up to: consent must be freely given
 * and separate from other terms, and it cannot be a condition of using the
 * service. Running the account rests on the contract instead. If Roster ever
 * sends marketing email, that needs its own, separate, unticked, optional box -
 * never this one.
 *
 * It starts unticked (a pre-ticked box is not agreement), and "Create account"
 * stays off until it is ticked - the sign-up form owns that state, so the
 * button, the Google button and the submit handler all read the same answer.
 *
 * The two links open a small dialog rather than a new page, so reading the
 * terms never costs anyone what they have typed. They sit inside the label but
 * are buttons, and a click on interactive content inside a label does not
 * activate the label - so opening the terms does not tick the box.
 */

const Tick = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3.2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
);

/** A link that opens the Terms or the Privacy Policy in a dialog. */
export function LegalLink({ kind, children }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="legal-link legal-linkbtn"
        data-testid={`legal-link-${kind}`}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      {open && <LegalDialog kind={kind} onClose={() => setOpen(false)} />}
    </>
  );
}

export function ConsentCheckbox({ checked, onChange }) {
  const id = useId();
  return (
    <div className="legal-consent">
      <label className="si-check legal-consent-label">
        <input
          type="checkbox"
          data-testid="consent-terms"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          aria-required="true"
          aria-describedby={checked ? undefined : id}
        />
        <span className="si-box" aria-hidden="true">{checked && <Tick />}</span>
        <span className="legal-consent-text">
          I agree to the <LegalLink kind="terms">Terms of Service</LegalLink>, including the data
          processing terms, on behalf of my business, and I have read the{" "}
          <LegalLink kind="privacy">Privacy Policy</LegalLink>.
        </span>
      </label>
      {!checked && (
        <p id={id} className="legal-required" data-testid="consent-required">
          Required to create your account.
        </p>
      )}
    </div>
  );
}

/**
 * Under the card. Keeps the "Staff do not sign in" line. On sign-in it adds the
 * legal line, because Google can create an account without the box being
 * ticked; on sign-up the box says it, and Google is held back until it is
 * ticked, so repeating it would only be noise.
 */
export function LegalNote({ signup = false }) {
  return (
    <>
      <p className="si-note">Staff do not sign in - they get their roster by email.</p>
      {!signup && (
        <p className="legal-note">
          Signing in or continuing with Google means you accept the{" "}
          <LegalLink kind="terms">Terms of Service</LegalLink> and have read the{" "}
          <LegalLink kind="privacy">Privacy Policy</LegalLink>.
        </p>
      )}
    </>
  );
}
