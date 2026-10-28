import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider, useAuth } from "./AuthContext";
import { api, getToken } from "../lib/api";

jest.mock("@/lib/api", () => ({ ...jest.requireActual("../lib/api"), api: { get: jest.fn(), post: jest.fn() } }));
jest.mock("sonner", () => ({ toast: { success: jest.fn() } }));

function Signup() {
  const { user, loginWithGoogle } = useAuth();
  const [step, setStep] = useState(null);
  return <>
    <span data-testid="session">{user ? user.email : "signed out"}</span>
    <span data-testid="step">{step?.password_required ? "password required" : ""}</span>
    <button onClick={async () => setStep(await loginWithGoogle("verified-google-token"))}>Google</button>
    <button onClick={() => loginWithGoogle("verified-google-token", "new-password")}>Complete</button>
  </>;
}

test("a Google password prompt creates no frontend session, and only completion stores the app token", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); sessionStorage.clear();
  api.get.mockImplementation(path => path === "/auth/me" ? Promise.reject(new Error("signed out"))
    : Promise.resolve({ data: { password: true, google: true } }));
  api.post.mockResolvedValueOnce({ data: { password_required: true, email: "new@gmail.com" } })
    .mockResolvedValueOnce({ data: { token: "fictional-app-token", user: { email: "new@gmail.com", has_password: true } } });
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<AuthProvider><Signup /></AuthProvider>));
    await act(async () => host.querySelectorAll("button")[0].click());
    expect(host.querySelector('[data-testid="step"]').textContent).toBe("password required");
    expect(host.querySelector('[data-testid="session"]').textContent).toBe("signed out");
    expect(getToken()).toBeNull();
    expect(api.post).toHaveBeenLastCalledWith("/auth/google", { credential: "verified-google-token" });
    await act(async () => host.querySelectorAll("button")[1].click());
    expect(api.post).toHaveBeenLastCalledWith("/auth/google", { credential: "verified-google-token", password: "new-password" });
    expect(getToken()).toBe("fictional-app-token");
    expect(host.querySelector('[data-testid="session"]').textContent).toBe("new@gmail.com");
    expect(JSON.stringify(localStorage)).not.toMatch(/new-password|verified-google-token/);
  } finally {
    await act(async () => root.unmount()); host.remove();
    localStorage.clear(); sessionStorage.clear();
  }
});
