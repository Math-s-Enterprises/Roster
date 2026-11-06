import React, { act } from "react";
import { createRoot } from "react-dom/client";
import CookieBanner from "./CookieBanner";
import { CONSENT_KEY, initializeConsent, readConsent, saveConsent } from "../lib/cookieConsent";

jest.mock("react-router-dom", () => ({ Link: ({ to, children }) => <a href={to}>{children}</a> }), { virtual: true });
let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); sessionStorage.clear(); initializeConsent();
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  jest.useRealTimers();
  jest.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); initializeConsent();
});
const render = async () => act(async () => root.render(<CookieBanner />));
const clickText = async text => act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === text).click());

test("nothing optional is allowed before a choice and opening settings does not accept it", async () => {
  host.tabIndex = 0; host.focus();
  await render();
  expect(document.activeElement).toBe(host);
  expect(readConsent()).toBeNull();
  expect(host.querySelector("section").className).toContain("no-print");
  expect([...host.querySelectorAll(".cookie-banner-choices button")].map(button => button.textContent)).toEqual(["Accept all", "Reject all"]);
  await clickText("Cookie settings");
  expect([...host.querySelectorAll('[role="switch"]')].map(input => input.checked)).toEqual([false, false, false]);
  expect(readConsent()).toBeNull();
  await clickText("Cancel");
  expect(readConsent()).toBeNull();
});

test.each([["Accept all", true], ["Reject all", false]])("%s remembers a real choice across remounts without clearing the session", async (label, allowed) => {
  localStorage.setItem("roster_token", "fictional-session");
  localStorage.setItem("roster_group", "Deli");
  await render(); await clickText(label);
  expect(readConsent()).toMatchObject({ preferences: allowed, fonts: allowed, google: allowed });
  expect(host.querySelector("section")).toBeNull();
  await act(async () => root.render(null)); await render();
  expect(host.textContent).toBe("Cookie settings");
  expect(localStorage.getItem("roster_token")).toBe("fictional-session");
  expect(localStorage.getItem("roster_group")).toBe("Deli");
  if (allowed) {
    await clickText("Cookie settings");
    expect(host.querySelector(".cookie-reload-note").textContent).toContain("Save unfinished work first.");
  }
});

test("saved choices can be reopened, changed individually and withdrawn", async () => {
  await render(); await clickText("Cookie settings");
  await act(async () => host.querySelector('[aria-label="Remember preferences"]').click());
  await clickText("Save choices");
  expect(readConsent()).toMatchObject({ preferences: true, fonts: false, google: false });
  await clickText("Cookie settings");
  expect(host.querySelector('[aria-label="Remember preferences"]').checked).toBe(true);
  await clickText("Reject all");
  expect(readConsent()).toMatchObject({ preferences: false, fonts: false, google: false });
});

test("the policy opens without making a choice and Escape returns focus", async () => {
  await render();
  const link = host.querySelector('[data-testid="legal-link-privacy"]'); link.focus();
  await act(async () => link.click());
  const dialog = document.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain("Privacy Policy");
  expect(readConsent()).toBeNull();
  await act(async () => dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(link);
});

test("a choice in another tab updates the visible controls", async () => {
  await render();
  const now = Date.now();
  localStorage.setItem(CONSENT_KEY, JSON.stringify({ version: 1, decidedAt: now, expiresAt: now + 1000, preferences: false, fonts: false, google: false }));
  await act(async () => window.dispatchEvent(new StorageEvent("storage", { key: CONSENT_KEY })));
  expect(host.textContent).toBe("Cookie settings");
});

test("an open tab asks again when its recorded permission expires", async () => {
  jest.useFakeTimers();
  const now = Date.now();
  localStorage.setItem(CONSENT_KEY, JSON.stringify({ version: 1, decidedAt: now, expiresAt: now + 1000, preferences: false, fonts: false, google: false }));
  await render();
  expect(host.querySelector("section")).toBeNull();
  await act(async () => jest.advanceTimersByTime(1000));
  expect(host.querySelector(".cookie-banner-choices").textContent).toContain("Reject all");
});

test("blocked storage still permits a choice for the current visit", async () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  await render(); await clickText("Reject all");
  expect(host.textContent).toBe("Cookie settings");
  expect(readConsent()).toMatchObject({ preferences: false, fonts: false, google: false });
});
