import React, { act } from "react";
import { createRoot } from "react-dom/client";
import AppLayout from "./AppLayout";
import { AuthProvider, useAuth } from "../context/AuthContext";
import { api } from "../lib/api";

jest.mock("react-router-dom", () => ({
  Outlet: () => null, NavLink: ({ children }) => <span>{children}</span>,
  useLocation: () => ({ pathname: "/", search: "" }), useNavigate: () => jest.fn(),
}), { virtual: true });
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("../lib/api"), api: { get: jest.fn(), post: jest.fn() },
}));
jest.mock("@/components/ChangePasswordModal", () => () => null);
jest.mock("@/components/DeleteAccountModal", () => () => null);
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
  await act(async () => root.render(<AuthProvider><Session /></AuthProvider>));
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
  expect(localStorage.getItem("roster_theme")).toBe("light");
});

test.each(["password", "Google"])("a chosen dark theme survives logout, %s sign-in and refresh", async method => {
  localStorage.setItem("roster_theme", "light");
  await mount(); await signIn();
  await act(async () => themeSwitch().click());
  expect(localStorage.getItem("roster_theme")).toBe("dark");
  await act(async () => host.querySelector('[data-testid="btn-logout"]').click());
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
  await act(async () => host.querySelector('[data-testid="btn-logout"]').click());
  await signIn(method);
  expect(document.documentElement.getAttribute("data-theme")).toBe("light");
});
