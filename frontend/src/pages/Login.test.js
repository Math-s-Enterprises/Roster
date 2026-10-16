import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Login from "./Login";
import { useAuth } from "@/context/AuthContext";
import { recordFailure } from "@/lib/loginGuard";

jest.mock("react-router-dom", () => ({
  useNavigate: () => jest.fn(), useLocation: () => ({ search: "" }),
  Link: ({ children }) => children,
}), { virtual: true });
jest.mock("@/context/AuthContext", () => ({ useAuth: jest.fn() }), { virtual: true });
jest.mock("@/lib/api", () => ({ errorMessage: () => "Could not create the account." }), { virtual: true });
jest.mock("@/components/AuthShell", () => ({ children }) => children, { virtual: true });
jest.mock("@/components/GoogleSignInButton", () => () => null, { virtual: true });
jest.mock("@/components/LegalConsent", () => ({ ConsentCheckbox: () => null, LegalNote: () => null }), { virtual: true });
jest.mock("@/components/ResetPrompt", () => () => null, { virtual: true });
jest.mock("@/lib/loginGuard", () => ({
  readGuard: () => ({ locked: false }), recordFailure: jest.fn(() => ({ failures: 1 })),
  clearGuard: jest.fn(), PROMPT_AT: 3, LOCK_AT: 5, LOCK_MINUTES: 15, minutesLeft: jest.fn(),
}), { virtual: true });

let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.clearAllMocks();
  recordFailure.mockReturnValue({ failures: 1 });
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
  jest.spyOn(window, "requestAnimationFrame").mockImplementation(callback => { callback(); return 0; });
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  jest.restoreAllMocks();
});

test.each([
  { status: 401, data: { detail: "Invalid email or password" } },
  { status: 404, data: { detail: { code: "email_not_found", message: "Sorry, this email doesn't exist." } } },
])("sign-in keeps account-existence errors generic ($status)", async response => {
  const login = jest.fn().mockRejectedValue({ response });
  useAuth.mockReturnValue({ login, providers: { google: false } });
  await act(async () => root.render(<Login />));
  for (const [selector, value] of [["#si-email", "person@example.com"], ["#si-password", "wrong-password"]]) {
    await act(async () => {
      const input = host.querySelector(selector);
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await act(async () => host.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(login).toHaveBeenCalledWith("person@example.com", "wrong-password", true);
  expect(host.textContent).toContain("That email and password do not match.");
  expect(host.textContent).not.toContain("doesn't exist");
  expect(document.activeElement).toBe(host.querySelector("#si-password"));
  expect(recordFailure).toHaveBeenCalledTimes(response.status === 401 ? 1 : 0);
});
