import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ConsentServices from "./ConsentServices";
import { initializeConsent, saveConsent } from "../lib/cookieConsent";

let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); initializeConsent();
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); localStorage.clear(); initializeConsent(); });

test("Google fonts are absent before consent, load only when enabled and are removed on withdrawal", async () => {
  await act(async () => root.render(<ConsentServices />));
  expect(document.querySelector('link[href*="fonts.googleapis.com"]')).toBeNull();
  await act(async () => saveConsent({ preferences: true, fonts: true }));
  expect(document.querySelector('link[href*="fonts.googleapis.com"]')).not.toBeNull();
  localStorage.setItem("roster_theme", "dark");
  await act(async () => saveConsent({}));
  expect(document.querySelector('link[href*="fonts.googleapis.com"]')).toBeNull();
  expect(localStorage.getItem("roster_theme")).toBeNull();
});

test("withdrawing Google sign-in reloads to terminate a previously loaded SDK", async () => {
  const location = window.location;
  delete window.location; window.location = { reload: jest.fn() };
  const script = document.createElement("script"); script.src = "https://accounts.google.com/gsi/client";
  try {
    saveConsent({ google: true }); document.head.appendChild(script);
    await act(async () => root.render(<ConsentServices />));
    expect(window.location.reload).not.toHaveBeenCalled();
    await act(async () => saveConsent({}));
    expect(window.location.reload).toHaveBeenCalledTimes(1);
  } finally { script.remove(); window.location = location; }
});
