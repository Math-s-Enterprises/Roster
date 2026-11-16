import React, { act } from "react";
import { createRoot } from "react-dom/client";
import AppLayout from "./AppLayout";
import { AuthProvider, useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { initializeConsent, saveConsent } from "../lib/cookieConsent";
import { CookieConsentProvider } from "./CookieBanner";

jest.mock("react-router-dom", () => ({
  Outlet: () => null, NavLink: ({ children }) => <span>{children}</span>,
  useLocation: () => ({ pathname: "/", search: "" }), useNavigate: () => jest.fn(),
}), { virtual: true });
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("../lib/api"), api: { get: jest.fn(), post: jest.fn() },
}));
jest.mock("@/components/ChangePasswordModal", () => ({ onClose }) => <div role="dialog">Password confirmation<button onClick={onClose}>Close password</button></div>);
jest.mock("@/components/DeleteAccountModal", () => ({ onClose }) => <div role="dialog">Delete confirmation<button onClick={onClose}>Close deletion</button></div>);
jest.mock("@/components/RosterGroupSelect", () => () => null);
jest.mock("@/components/NotificationsDrawer", () => () => null);
jest.mock("@/lib/notifications", () => ({
  NotificationsProvider: ({ children }) => children,
  useNotifications: () => ({ unread: 0 }),
}));
jest.mock("sonner", () => ({ toast: { success: jest.fn() } }));

let host, root, signedIn;
const user = { user_id: "theme-user", name: "Theme User", email: "theme@example.test" };

function Session() {
  const { user: current, loading, login, loginWithGoogle } = useAuth();
  if (loading) return null;
  return current ? <AppLayout /> : <>
    <button onClick={() => login(user.email, "test-password")}>Sign in with password</button>
    <button onClick={() => loginWithGoogle("test-credential")}>Sign in with Google</button>
  </>;
}

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); sessionStorage.clear();
  initializeConsent();
  document.documentElement.removeAttribute("data-theme");
  jest.clearAllMocks();
  signedIn = false;
  api.get.mockImplementation(path => {
    if (path === "/auth/me") return signedIn
      ? Promise.resolve({ data: user }) : Promise.reject(new Error("signed out"));
    return Promise.resolve({ data: path === "/auth/providers" ? { password: true, google: true }
      : path === "/shop" ? { departments: ["Shop Floor"] } : [] });
  });
  api.post.mockImplementation(path => {
    signedIn = path !== "/auth/logout";
    return Promise.resolve({ data: signedIn ? { token: "fictional-token", user } : {} });
  });
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  localStorage.clear(); sessionStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
async function mount() {
  await act(async () => root.render(<AuthProvider><CookieConsentProvider><Session /></CookieConsentProvider></AuthProvider>));
}
async function openSettings() {
  await act(async () => host.querySelector('[data-testid="btn-settings"]').dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
}
async function selectSetting(id) {
  await openSettings();
  await act(async () => document.querySelector(`[data-testid="${id}"]`).click());
}
async function signIn(method = "password") {
  const label = method === "password" ? "Sign in with password" : "Sign in with Google";
  await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === label).click());
}
const themeSwitch = () => host.querySelector('[data-testid="btn-theme"]');

test.each(["password", "Google"])("a first %s sign-in opens in light mode", async method => {
  await mount(); await signIn(method);
  expect(themeSwitch().getAttribute("aria-checked")).toBe("true");
  expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  expect(localStorage.getItem("roster_theme")).toBeNull();
});

test.each(["password", "Google"])("a chosen dark theme survives logout, %s sign-in and refresh", async method => {
  saveConsent({ preferences: true });
  localStorage.setItem("roster_theme", "light");
  await mount(); await signIn();
  await act(async () => themeSwitch().click());
  expect(localStorage.getItem("roster_theme")).toBe("dark");
  await selectSetting("btn-logout");
  expect(themeSwitch()).toBeNull();
  expect(localStorage.getItem("roster_theme")).toBe("dark");
  await signIn(method);
  expect(themeSwitch().getAttribute("aria-checked")).toBe("false");
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount();
  expect(themeSwitch().getAttribute("aria-checked")).toBe("false");
  expect(localStorage.getItem("roster_theme")).toBe("dark");
  await act(async () => themeSwitch().click());
  await selectSetting("btn-logout");
  await signIn(method);
  expect(document.documentElement.getAttribute("data-theme")).toBe("light");
});

test("one flat sidebar Settings row replaces the loose account actions and floating cookie link", async () => {
  saveConsent({ preferences: false });
  await mount(); await signIn();
  expect(host.querySelector('[data-testid="btn-settings"]').className).toContain("nv-item");
  expect(document.querySelector(".cookie-settings-link")).toBeNull();
  expect(document.querySelector('[data-testid="btn-logout"]')).toBeNull();
  await openSettings();
  expect([...document.querySelectorAll('[role="menuitem"]')].map(item => item.textContent)).toEqual([
    "Change password", "Delete account", "Sign out", "Cookie settings",
  ]);
  expect(document.querySelector('[role="menu"]').className).toContain("no-print");
  await act(async () => document.querySelector('[role="menuitem"]').dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  await act(async () => new Promise(resolve => setTimeout(resolve, 0)));
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(host.querySelector('[data-testid="btn-settings"]'));
});

test.each([["btn-change-password", "Password confirmation", "Close password"], ["btn-delete-account", "Delete confirmation", "Close deletion"]])(
  "%s still opens its existing confirmation without submitting an account change", async (id, text, close) => {
    saveConsent({ preferences: false });
    await mount(); await signIn();
    api.post.mockClear();
    await selectSetting(id);
    expect(document.querySelector('[role="dialog"]').textContent).toContain(text);
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
    await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === close).click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  },
);

test("sidebar cookie settings reopen real consent controls and return focus after saving", async () => {
  saveConsent({ preferences: true, fonts: false, google: false });
  await mount(); await signIn();
  await selectSetting("btn-cookie-settings");
  await act(async () => new Promise(resolve => requestAnimationFrame(resolve)));
  expect(document.activeElement).toBe(host.querySelector("#cookie-banner-title"));
  expect(host.querySelector('[aria-label="Remember preferences"]').checked).toBe(true);
  await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "Reject all").click());
  await act(async () => new Promise(resolve => requestAnimationFrame(resolve)));
  expect(host.querySelector(".cookie-banner")).toBeNull();
  expect(document.querySelector(".cookie-settings-link")).toBeNull();
  expect(document.activeElement).toBe(host.querySelector('[data-testid="btn-settings"]'));
  await selectSetting("btn-cookie-settings");
  await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "Cancel").click());
  await act(async () => new Promise(resolve => requestAnimationFrame(resolve)));
  await selectSetting("btn-logout");
  expect(host.querySelector(".cookie-settings-link").textContent).toBe("Cookie settings");
});

test("a first-visit consent banner remains available while the sidebar is mounted", async () => {
  await mount(); await signIn();
  expect(host.querySelector(".cookie-banner-choices").textContent).toContain("Reject all");
  expect(host.querySelector('[data-testid="btn-settings"]')).not.toBeNull();
});
