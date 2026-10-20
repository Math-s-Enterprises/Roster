import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Dashboard from "./Dashboard";

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("../lib/api"),
  api: { get: jest.fn(), post: jest.fn() },
}), { virtual: true });
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
const { api } = require("@/lib/api");
const { toast } = require("sonner");
let host, root;
const button = text => [...document.querySelectorAll("button")].find(b => b.textContent === text);

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  api.get.mockImplementation(path => Promise.resolve({ data:
    path === "/shop" ? { name: "Test shop", departments: ["Shop Floor"] }
      : path === "/employees" ? [{ employee_id: "one" }]
      : path === "/setup-status" ? { complete: true, total: 1, done: 1, steps: [] }
      : path === "/rosters" ? [{ roster_id: "approved", week_start: "2026-10-05",
        version: "v1.0-hist", approved: true, total_hours: 123, labor_cost: 2345, compliance_score: 100 }]
      : Array.from({ length: 8 }, (_, i) => ({ log_id: `log-${i}`, action: "roster_generated",
        detail: `Shop Floor: generated a roster ${i}`, created_at: "2026-10-05T10:00:00Z" })) }));
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

async function openReset() {
  const details = host.querySelector(".db-danger-zone");
  expect(details).not.toBeNull();
  details.open = true;
  const trigger = host.querySelector('[data-testid="btn-reset"]');
  trigger.focus();
  await act(async () => trigger.click());
  return trigger;
}
async function typeConfirmation(value) {
  const input = document.querySelector("#db-confirm");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

test("reset stays out of the primary actions and cancelling or Escape never deletes data", async () => {
  await act(async () => root.render(<Dashboard />));
  expect(host.querySelector('.db-head [data-testid="btn-generate-roster"]')).not.toBeNull();
  expect(host.querySelector('.db-head [data-testid="btn-reset"]')).toBeNull();
  expect(host.querySelector(".db-danger-zone").open).toBe(false);
  const trigger = await openReset();
  expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();
  expect(button("Reset everything").disabled).toBe(true);
  expect(document.activeElement).toBe(button("Cancel"));
  await act(async () => button("Cancel").click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 0)));
  expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await openReset();
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  expect(api.post).not.toHaveBeenCalled();
});

test("reset requires exact confirmation, keeps errors visible and blocks duplicate requests", async () => {
  await act(async () => root.render(<Dashboard />));
  await openReset();
  await typeConfirmation("reset");
  expect(button("Reset everything").disabled).toBe(true);
  await act(async () => button("Reset everything").click());
  expect(api.post).not.toHaveBeenCalled();
  api.post.mockRejectedValueOnce(new Error("Offline"));
  await typeConfirmation("RESET");
  await act(async () => button("Reset everything").click());
  expect(toast.error).toHaveBeenCalled();
  expect(document.querySelector('[role="alertdialog"]')).not.toBeNull();
  let finish;
  api.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await act(async () => button("Reset everything").click());
  expect(button("Cancel").disabled).toBe(true);
  await act(async () => button("Saving…").click());
  expect(api.post.mock.calls).toEqual([["/dev/reset"], ["/dev/reset"]]);
  await act(async () => finish({ data: {} }));
  expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  expect(api.get.mock.calls.filter(([path]) => path === "/shop")).toHaveLength(2);
});

test("activity expansion preserves navigation, counts and keyboard focus", async () => {
  await act(async () => root.render(<Dashboard />));
  expect(host.querySelectorAll(".db-entry")).toHaveLength(6);
  await act(async () => host.querySelector('[data-testid="activity-more"]').click());
  expect(host.querySelectorAll(".db-entry")).toHaveLength(8);
  expect(host.querySelector('[data-testid="activity-count"]').textContent).toBe("All 8 shown");
  expect(document.activeElement).toBe(host.querySelector('[data-testid="activity-fewer"]'));
  await act(async () => host.querySelector(".db-entry-btn").click());
  expect(mockNavigate).toHaveBeenCalledWith("/roster");
  await act(async () => host.querySelector('[data-testid="activity-fewer"]').click());
  expect(host.querySelectorAll(".db-entry")).toHaveLength(6);
  expect(document.activeElement).toBe(host.querySelector('[data-testid="activity-more"]'));
  const status = host.querySelector(".db-tag");
  expect(status.tagName).toBe("SPAN");
  expect(status.tabIndex).toBe(-1);
  expect(status.textContent).toBe("Approved");
});
