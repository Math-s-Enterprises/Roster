import React, { act } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { useAuth } from "@/context/AuthContext";

// CRA's Jest resolver does not follow this installed router's package exports.
jest.mock("react-router-dom", () => {
  Object.assign(global, { TextEncoder: require("util").TextEncoder, TextDecoder: require("util").TextDecoder });
  return jest.requireActual("../node_modules/react-router-dom/dist/index.js");
}, { virtual: true });
jest.mock("react-router", () => jest.requireActual("../node_modules/react-router/dist/development/index.js"), { virtual: true });
jest.mock("react-router/dom", () => jest.requireActual("../node_modules/react-router/dist/development/dom-export.js"), { virtual: true });
jest.mock("@/context/AuthContext", () => ({ AuthProvider: ({ children }) => children, useAuth: jest.fn() }));
jest.mock("@/components/AppLayout", () => () => {
  const { Outlet } = require("react-router-dom");
  return <Outlet />;
});
jest.mock("@/pages/Login", () => () => <h1>Sign in</h1>);
jest.mock("@/pages/ForgotPassword", () => () => null);
jest.mock("@/pages/ResetPassword", () => () => null);
jest.mock("@/pages/VerifyEmail", () => () => null);
jest.mock("@/pages/Dashboard", () => () => <h1>Dashboard</h1>);
jest.mock("@/pages/Onboarding", () => () => null);
jest.mock("@/pages/Employees", () => () => null);
jest.mock("@/pages/CalendarPage", () => () => null);
jest.mock("@/pages/FixedShifts", () => () => null);
jest.mock("@/pages/AIRules", () => () => null);
jest.mock("@/pages/RosterView", () => () => <h1>Weekly roster</h1>);
jest.mock("@/pages/PastRosters", () => () => null);
jest.mock("@/pages/ImportRosters", () => () => null);
jest.mock("@/pages/SickReport", () => () => null);
jest.mock("@/pages/HoursReport", () => () => null);
jest.mock("@/pages/LearningReport", () => () => null);
jest.mock("@/pages/Pricing", () => () => null);
jest.mock("@/pages/PaymentResult", () => ({ PaymentCancel: () => null, PaymentSuccess: () => null }));
jest.mock("sonner", () => ({ Toaster: () => null }));

let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  useAuth.mockReturnValue({ user: null, loading: false });
  window.history.replaceState({}, "", "/");
  document.title = "Roster";
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  document.documentElement.removeAttribute("data-theme");
});

test.each([null, { email: "fictional@example.com" }])("an unknown nested URL stays visible for user %p and the recovery link works", async user => {
  useAuth.mockReturnValue({ user, loading: false });
  window.history.replaceState({}, "", "/reports/does-not-exist?week=2026-10-26");
  document.documentElement.setAttribute("data-theme", "light");
  await act(async () => root.render(<App />));
  expect(window.location.pathname).toBe("/reports/does-not-exist");
  expect(host.querySelector("h1").textContent).toBe("Page not found");
  expect(document.activeElement).toBe(host.querySelector("h1"));
  expect(document.title).toBe("Page not found | Roster");
  expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  const link = host.querySelector(".nf-action");
  expect(link.getAttribute("href")).toBe(user ? "/" : "/login");
  await act(async () => link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
  expect(host.querySelector("h1").textContent).toBe(user ? "Dashboard" : "Sign in");
  expect(document.title).toBe("Roster");
});

test("an unknown URL does not change the saved dark theme while the session loads", async () => {
  useAuth.mockReturnValue({ user: null, loading: true });
  window.history.replaceState({}, "", "/missing");
  await act(async () => root.render(<App />));
  expect(host.querySelector(".nf-action").textContent).toBe("Back to home");
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
});

test("valid routes and the signed-out protection still work", async () => {
  useAuth.mockReturnValue({ user: { email: "fictional@example.com" }, loading: false });
  window.history.replaceState({}, "", "/roster");
  await act(async () => root.render(<App />));
  expect(host.querySelector("h1").textContent).toBe("Weekly roster");
  useAuth.mockReturnValue({ user: null, loading: false });
  await act(async () => root.render(<App />));
  expect(window.location.pathname).toBe("/login");
  expect(host.querySelector("h1").textContent).toBe("Sign in");
});
