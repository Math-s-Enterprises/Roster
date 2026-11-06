import { useEffect, useState } from "react";

export const CONSENT_KEY = "roster_cookie_consent";
export const CONSENT_DAYS = 180;
const VERSION = 1;
const MAX_AGE = CONSENT_DAYS * 86400000;
const CHANGED = "roster:cookie-consent";
// Sign-in, login security and roster_group are required; never erase them here.
const PREFERENCES = ["roster_theme", "roster_fixed_shifts_view", "roster_hours_sort", "roster_learning_sort"];
const visitPreferences = new Map();
let volatileConsent;

export function readConsent() {
  let value;
  try { value = volatileConsent ?? JSON.parse(localStorage.getItem(CONSENT_KEY)); }
  catch { value = volatileConsent; }
  const now = Date.now();
  return value && value.version === VERSION
    && ["preferences", "fonts", "google"].every(key => typeof value[key] === "boolean")
    && Number.isFinite(value.decidedAt) && value.decidedAt <= now
    && Number.isFinite(value.expiresAt) && value.expiresAt > now
    && value.expiresAt <= value.decidedAt + MAX_AGE ? value : null;
}

export function clearOptionalStorage() {
  for (const getStore of [() => localStorage, () => sessionStorage]) {
    try {
      const store = getStore();
      const keys = Array.from({ length: store.length }, (_, index) => store.key(index));
      for (const key of keys) {
        if (PREFERENCES.includes(key) || key?.startsWith("roster_notifications:")) store.removeItem(key);
      }
    } catch { /* Storage may be blocked; the app still works for this visit. */ }
  }
}

export function initializeConsent() {
  volatileConsent = undefined;
  visitPreferences.clear();
  try { localStorage.removeItem("roster_cookie_notice"); } catch { /* Old acknowledgement is not consent. */ }
  if (!readConsent()?.preferences) clearOptionalStorage();
}

export function readPreference(key) {
  if (readConsent()?.preferences) {
    try { return localStorage.getItem(key) ?? visitPreferences.get(key) ?? null; } catch { /* Fall back to this visit. */ }
  }
  return visitPreferences.get(key) ?? null;
}

export function writePreference(key, value) {
  visitPreferences.set(key, String(value));
  if (readConsent()?.preferences) {
    try { localStorage.setItem(key, String(value)); } catch { /* Keep the in-memory choice. */ }
  }
}

export function saveConsent(choices) {
  const decidedAt = Date.now();
  const record = { version: VERSION, decidedAt, expiresAt: decidedAt + MAX_AGE,
    preferences: choices.preferences === true, fonts: choices.fonts === true, google: choices.google === true };
  try { localStorage.setItem(CONSENT_KEY, JSON.stringify(record)); volatileConsent = undefined; }
  catch {
    volatileConsent = record;
    // A quota failure must not leave an older permission to be reused after reload.
    try { localStorage.removeItem(CONSENT_KEY); } catch { /* Blocked storage remains unavailable. */ }
  }
  if (!record.preferences) clearOptionalStorage();
  else visitPreferences.forEach((value, key) => writePreference(key, value));
  window.dispatchEvent(new Event(CHANGED));
}

export function useConsent() {
  const [consent, setConsent] = useState(readConsent);
  useEffect(() => {
    const refresh = event => {
      if (event.type === "storage" && event.key && event.key !== CONSENT_KEY) return;
      if (event.type === "storage") volatileConsent = undefined;
      setConsent(readConsent());
    };
    window.addEventListener(CHANGED, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(CHANGED, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);
  useEffect(() => {
    if (!consent) return;
    // Browser timers cap at about 25 days; re-check long-lived tabs until expiry.
    const timer = setTimeout(() => setConsent(readConsent()), Math.min(consent.expiresAt - Date.now(), 2147483647));
    return () => clearTimeout(timer);
  }, [consent]);
  return consent;
}
