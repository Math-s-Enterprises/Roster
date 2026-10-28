import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Login from "./Login";
import { useAuth } from "@/context/AuthContext";
import { recordFailure } from "@/lib/loginGuard";

const mockNavigate = jest.fn();
let mockLocation = { search: "" };
jest.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate, useLocation: () => mockLocation,
  Link: ({ children }) => children,
}), { virtual: true });
jest.mock("@/context/AuthContext", () => ({ useAuth: jest.fn() }), { virtual: true });
jest.mock("@/lib/api", () => ({ errorMessage: () => "Could not create the account." }), { virtual: true });
jest.mock("@/components/AuthShell", () => ({ children }) => children, { virtual: true });
jest.mock("@/components/GoogleSignInButton", () => ({ onCredential, disabled }) =>
  <button type="button" data-testid="google-signin" disabled={disabled} onClick={() => onCredential("verified-google-token")}>Continue with Google</button>, { virtual: true });
jest.mock("@/components/LegalConsent", () => ({
  ConsentCheckbox: ({ checked, onChange }) => <input type="checkbox" aria-label="Accept terms" checked={checked} onChange={e => onChange(e.target.checked)} />,
  LegalNote: () => null,
}), { virtual: true });
jest.mock("@/components/ResetPrompt", () => () => null, { virtual: true });
jest.mock("@/lib/loginGuard", () => ({
  readGuard: () => ({ locked: false }), recordFailure: jest.fn(() => ({ failures: 1 })),
  clearGuard: jest.fn(), PROMPT_AT: 3, LOCK_AT: 5, LOCK_MINUTES: 15, minutesLeft: jest.fn(),
}), { virtual: true });

let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.clearAllMocks();
  mockLocation = { search: "" };
  recordFailure.mockReturnValue({ failures: 1 });
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
  jest.spyOn(window, "requestAnimationFrame").mockImplementation(callback => { callback(); return 0; });
});

async function googleSetup() {
  const loginWithGoogle = jest.fn().mockResolvedValueOnce({ password_required: true, email: "new@gmail.com" });
  useAuth.mockReturnValue({ loginWithGoogle, providers: { google: true, google_client_id: "test-client" } });
  await act(async () => root.render(<Login />));
  await act(async () => host.querySelector('[data-testid="google-signin"]').click());
  return loginWithGoogle;
}
async function fill(selector, value) {
  await act(async () => {
    const input = host.querySelector(selector);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => host.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}

test("a new Google identity sees password setup before navigation or account completion", async () => {
  const google = await googleSetup();
  expect(host.textContent).toContain("Create your password");
  expect(host.textContent).toContain("new@gmail.com");
  expect(document.activeElement.id).toBe("gp-password");
  expect(host.querySelector('[type="submit"]').disabled).toBe(true);
  expect(google).toHaveBeenCalledTimes(1);
  expect(mockNavigate).not.toHaveBeenCalled();
});

test("Google signup requires terms, a long enough password and matching confirmation", async () => {
  const google = await googleSetup();
  await submit();
  expect(google).toHaveBeenCalledTimes(1);
  await act(async () => host.querySelector('[aria-label="Accept terms"]').click());
  await submit();
  expect(host.textContent).toContain("Use at least 8 characters.");
  expect(host.textContent).toContain("Type your password again.");
  await fill("#gp-password", "long-password"); await fill("#gp-confirm", "different-password");
  await submit();
  expect(host.textContent).toContain("The two passwords do not match.");
  expect(google).toHaveBeenCalledTimes(1);
  expect(mockNavigate).not.toHaveBeenCalled();
});

test("completing Google signup resubmits the credential with the chosen password and retains the return path", async () => {
  mockLocation = { search: "?redirectTo=%2Froster" };
  const google = await googleSetup();
  await fill("#gp-password", "my-new-password"); await fill("#gp-confirm", "my-new-password");
  await act(async () => host.querySelector('[aria-label="Accept terms"]').click());
  let finish;
  google.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await submit();
  expect(google).toHaveBeenLastCalledWith("verified-google-token", "my-new-password");
  expect(host.querySelector('[type="submit"]').disabled).toBe(true);
  expect(host.querySelector("#gp-password").disabled).toBe(true);
  expect(mockNavigate).not.toHaveBeenCalled();
  await act(async () => finish({ has_password: true }));
  expect(mockNavigate).toHaveBeenCalledWith("/roster", { replace: true });
});

test("an existing Google account signs in without a password-setup step", async () => {
  const google = jest.fn().mockResolvedValue({ has_password: true });
  useAuth.mockReturnValue({ loginWithGoogle: google, providers: { google: true, google_client_id: "test-client" } });
  await act(async () => root.render(<Login />));
  await act(async () => host.querySelector('[data-testid="google-signin"]').click());
  expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true });
  expect(host.querySelector("#gp-password")).toBeNull();
});

test("a setup failure stays on the form and Back discards the password without creating an account", async () => {
  const google = await googleSetup();
  await fill("#gp-password", "my-new-password"); await fill("#gp-confirm", "my-new-password");
  await act(async () => host.querySelector('[aria-label="Accept terms"]').click());
  google.mockRejectedValueOnce(new Error("expired credential"));
  await submit();
  expect(host.querySelector('[role="alert"]').textContent).toBe("Could not create the account.");
  expect(host.querySelector('[type="submit"]').disabled).toBe(false);
  expect(mockNavigate).not.toHaveBeenCalled();
  await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "Back to sign in").click());
  expect(host.querySelector("#gp-password")).toBeNull();
  expect(host.querySelector('[data-testid="google-signin"]')).not.toBeNull();
  google.mockResolvedValueOnce({ password_required: true, email: "new@gmail.com" });
  await act(async () => host.querySelector('[data-testid="google-signin"]').click());
  expect(host.querySelector("#gp-password").value).toBe("");
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
