import React, { useState } from "react";
import { ArrowRight, KeyRound } from "lucide-react";
import AuthShell from "@/components/AuthShell";
import { ConsentCheckbox, LegalNote } from "@/components/LegalConsent";
import { errorMessage } from "@/lib/api";

export default function GooglePasswordSetup({ email, agreed, onAgreementChange, onSubmit, onCancel }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    if (saving || !agreed) return;
    const next = {};
    if (password.length < 8) next.password = "Use at least 8 characters.";
    if (!confirm) next.confirm = "Type your password again.";
    else if (password !== confirm) next.confirm = "The two passwords do not match.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setSaving(true); setError(null);
    try {
      await onSubmit(password);
    } catch (err) {
      setError(errorMessage(err, "Could not create your account. Try again, or go back and sign in with Google again."));
    } finally { setSaving(false); }
  };

  return (
    <AuthShell single>
      <form className="si-card" onSubmit={submit} noValidate>
        <h1 className="si-h2">Create your password</h1>
        <p className="si-card-sub">Google verified <strong>{email}</strong>. Choose a password for Roster to finish creating your account. You can then sign in with Google or your email and password.</p>
        <div className="si-field">
          <div className="si-label-row">
            <label className="si-label" htmlFor="gp-password">Password</label>
            <button type="button" className="si-toggle" aria-pressed={show}
              aria-controls="gp-password gp-confirm" onClick={() => setShow(value => !value)}>
              {show ? "Hide" : "Show"}
            </button>
          </div>
          <div className="si-input" data-invalid={Boolean(errors.password)}>
            <KeyRound size={17} aria-hidden="true" />
            <input id="gp-password" type={show ? "text" : "password"} autoComplete="new-password"
              autoFocus value={password} maxLength={72} disabled={saving}
              onChange={e => { setPassword(e.target.value); setErrors({}); setError(null); }}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? "gp-password-help gp-password-error" : "gp-password-help"} />
          </div>
          <p id="gp-password-help" className="si-note">Use at least 8 characters.</p>
          {errors.password && <p id="gp-password-error" className="si-field-error">{errors.password}</p>}
        </div>
        <div className="si-field">
          <div className="si-label-row"><label className="si-label" htmlFor="gp-confirm">Confirm password</label></div>
          <div className="si-input" data-invalid={Boolean(errors.confirm)}>
            <KeyRound size={17} aria-hidden="true" />
            <input id="gp-confirm" type={show ? "text" : "password"} autoComplete="new-password"
              value={confirm} maxLength={72} disabled={saving}
              onChange={e => { setConfirm(e.target.value); setErrors({}); setError(null); }}
              aria-invalid={Boolean(errors.confirm)} aria-describedby={errors.confirm ? "gp-confirm-error" : undefined} />
          </div>
          {errors.confirm && <p id="gp-confirm-error" className="si-field-error">{errors.confirm}</p>}
        </div>
        <ConsentCheckbox checked={agreed} onChange={onAgreementChange} />
        <p className="si-form-error" role="alert">{error}</p>
        <button type="submit" className="si-cta" disabled={saving || !agreed} aria-busy={saving}>
          {saving ? <><span className="si-spinner" aria-hidden="true" />Creating your account</>
            : <>Create account <ArrowRight size={18} aria-hidden="true" /></>}
        </button>
        <p className="si-note"><button type="button" className="si-link" onClick={onCancel} disabled={saving}>Back to sign in</button></p>
        <LegalNote signup />
      </form>
    </AuthShell>
  );
}
