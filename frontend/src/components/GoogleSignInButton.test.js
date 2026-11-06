import React, { act } from "react";
import { createRoot } from "react-dom/client";
import GoogleSignInButton from "./GoogleSignInButton";
import { initializeConsent, readConsent, saveConsent } from "../lib/cookieConsent";

test("Google does not load before consent and a disabled signup cannot bypass the agreement", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); initializeConsent();
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  const onCredential = jest.fn();
  const google = { accounts: { id: { initialize: jest.fn(), renderButton: jest.fn() } } };
  try {
    await act(async () => root.render(<GoogleSignInButton clientId="fictional-client" onCredential={onCredential} disabled />));
    expect(host.querySelector("button").disabled).toBe(true);
    await act(async () => host.querySelector("button").click());
    expect(readConsent()).toBeNull();
    expect(document.querySelector('script[src*="accounts.google.com"]')).toBeNull();
    await act(async () => root.render(<GoogleSignInButton clientId="fictional-client" onCredential={onCredential} />));
    await act(async () => host.querySelector("button").click());
    expect(readConsent()).toMatchObject({ google: true, fonts: false, preferences: false });
    const script = document.querySelector('script[src="https://accounts.google.com/gsi/client"]');
    expect(script).not.toBeNull();
    window.google = google;
    await act(async () => script.dispatchEvent(new Event("load")));
    expect(google.accounts.id.renderButton).toHaveBeenCalledTimes(1);
    google.accounts.id.initialize.mock.calls[0][0].callback({ credential: "fictional-google-token" });
    expect(onCredential).toHaveBeenCalledWith("fictional-google-token");
    await act(async () => saveConsent({}));
    expect(host.querySelector("button").textContent).toBe("Allow Google sign-in");
  } finally {
    await act(async () => root.unmount()); host.remove();
    document.querySelector('script[src="https://accounts.google.com/gsi/client"]')?.remove();
    delete window.google; localStorage.clear(); initializeConsent();
  }
});
