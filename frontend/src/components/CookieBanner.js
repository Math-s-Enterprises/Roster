import React, { useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { LegalLink } from "@/components/LegalConsent";
import { saveConsent, useConsent } from "@/lib/cookieConsent";
import "@/styles/cookie-banner.css";

const OFF = { preferences: false, fonts: false, google: false };
const ON = { preferences: true, fonts: true, google: true };
const OPTIONS = [
  { key: "preferences", title: "Remember preferences", description: "Save your theme, display choices and recent notifications on this device. Without this, they work only for the current visit." },
  { key: "fonts", title: "Google fonts", description: "Download Roster’s typefaces from Google. Google receives your IP address. Otherwise, your device’s fonts are used." },
  { key: "google", title: "Google sign-in", description: "Load Google’s sign-in service, which may use cookies and receive device and account information. Email sign-in works without it." },
];

export default function CookieBanner() {
  const consent = useConsent();
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState(OFF);
  const settingsButton = useRef(null);
  const heading = useRef(null);
  const openSettings = () => {
    setDraft(consent || OFF); setExpanded(true);
    requestAnimationFrame(() => heading.current?.focus());
  };
  const cancel = () => { setExpanded(false); requestAnimationFrame(() => settingsButton.current?.focus()); };
  const choose = choices => {
    saveConsent(choices);
    setExpanded(false);
    requestAnimationFrame(() => settingsButton.current?.focus());
  };

  if (consent && !expanded) return <button ref={settingsButton} type="button"
    className="cookie-settings-link no-print" onClick={openSettings}>Cookie settings</button>;

  return (
    <section className="cookie-banner no-print" aria-labelledby="cookie-banner-title">
      <header className="cookie-banner-heading">
        <ShieldCheck size={24} aria-hidden="true" />
        <h2 id="cookie-banner-title" ref={heading} tabIndex={-1}>Your cookie choices</h2>
      </header>
      <div className="cookie-banner-body">
        <p>Required storage keeps your account and roster group working securely. You choose whether
          we remember extra preferences or load Google fonts and Google sign-in. Optional features stay off until you allow them.</p>
        <p>We don’t use analytics or advertising trackers. <LegalLink kind="privacy">Privacy Policy</LegalLink></p>
        {expanded && <div id="cookie-preferences" className="cookie-options" aria-label="Cookie preferences">
          <div className="cookie-option"><div><strong>Required storage</strong>
            <p>Sign-in, security checks, your selected roster group and this choice. Always on.</p></div>
            <span className="cookie-always">Always on</span></div>
          {OPTIONS.map(option => <label className="cookie-option" key={option.key}>
            <span><strong>{option.title}</strong><span className="cookie-option-detail">{option.description}</span></span>
            <input type="checkbox" role="switch" aria-label={option.title} aria-checked={draft[option.key]}
              checked={draft[option.key]} onChange={event => setDraft(current => ({ ...current, [option.key]: event.target.checked }))} />
          </label>)}
          <p>Rejecting removes saved optional preferences and notification history from this browser, not your shop records.
            Your choice lasts 180 days. You can change it using Cookie settings.</p>
          <p>Google may retain cookies it already set; manage those through your browser.</p>
        </div>}
      </div>
      {consent?.google && <p className="cookie-reload-note">Turning off Google sign-in reloads open Roster tabs
        that have loaded it. Save unfinished work first.</p>}
      <footer className="cookie-banner-actions">
        <div className="cookie-banner-choices">
          <button type="button" onClick={() => choose(ON)}>Accept all</button>
          <button type="button" onClick={() => choose(OFF)}>Reject all</button>
        </div>
        {expanded ? <div className="cookie-banner-settings-actions">
          <button type="button" className="cookie-save" onClick={() => choose(draft)}>Save choices</button>
          <button type="button" onClick={cancel}>Cancel</button>
        </div> : <button ref={settingsButton} type="button" className="cookie-customize" aria-expanded="false" aria-controls="cookie-preferences" onClick={openSettings}>Cookie settings</button>}
      </footer>
    </section>
  );
}
