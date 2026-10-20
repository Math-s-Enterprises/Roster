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

const setupSteps = [
  { id: "shop", title: "Set up your shop", action: { label: "Open setup", path: "/onboarding" } },
  { id: "history", title: "Import past rosters", action: { label: "Import rosters", path: "/import" } },
  { id: "team", title: "Add anyone the import missed", action: { label: "Add people", path: "/employees" } },
  { id: "details", title: "Check pay and ages", detail: "Jane still on placeholder pay and age",
    who: [{ employee_id: "jane", name: "Jane" }], action: { label: "Review team", path: "/employees" } },
  { id: "employment", title: "Set employment types", detail: "Jane without a type",
    who: [{ employee_id: "jane", name: "Jane" }], action: { label: "Set types", path: "/employees" } },
  { id: "constraints", title: "Fixed shifts and booked leave", optional: true,
    action: { label: "Add fixed shifts", path: "/fixed-shifts" } },
  { id: "roster", title: "Generate and approve a week", action: { label: "Open roster", path: "/roster" } },
].map(s => ({ why: "Explain why this step matters.", detail: "Not done", done: false, ...s }));

function withSetup(setup) {
  const get = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/setup-status" ? Promise.resolve({ data: setup }) : get(path));
}

test("Review steps expands all seven completed steps without leaving the dashboard", async () => {
  withSetup({ complete: true, done: 6, total: 6, steps: setupSteps.map(s => ({ ...s, done: true, who: [] })) });
  await act(async () => root.render(<Dashboard />));
  const review = button("Review steps");
  expect(review.getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelector("#db-setup-steps").hidden).toBe(true);
  await act(async () => review.click());
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(review.getAttribute("aria-expanded")).toBe("true");
  const steps = host.querySelectorAll("#db-setup-steps li");
  expect(steps).toHaveLength(7);
  expect(steps[6].textContent).toContain("Generate and approve a week");
  expect(host.querySelector("#db-setup-steps").textContent).toContain("6 of 6 required steps complete");
  await act(async () => review.click());
  expect(host.querySelector("#db-setup-steps").hidden).toBe(true);
});

test("unfinished setup shows ordered guidance, named employee tasks and precise destinations", async () => {
  withSetup({ complete: false, done: 0, total: 6, steps: setupSteps });
  await act(async () => root.render(<Dashboard />));
  expect(host.querySelector("#db-setup-steps").hidden).toBe(false);
  expect(host.querySelectorAll("#db-setup-steps li")).toHaveLength(7);
  expect(host.querySelector('[data-testid="setup-step-shop"]').textContent).toContain("Start here");
  expect(host.textContent).toContain("Jane still on placeholder pay and age");
  expect(host.textContent).toContain("Jane without a type");
  for (const [id, path] of [["shop", "/onboarding#shop-name"], ["team", "/employees?setup=team"],
    ["history", "/import"], ["roster", "/roster"]]) {
    await act(async () => host.querySelector(`[data-testid="setup-go-${id}"]`).click());
    expect(mockNavigate).toHaveBeenLastCalledWith(path);
  }
  await act(async () => host.querySelector('[data-testid="setup-person-details-jane"]').click());
  expect(mockNavigate).toHaveBeenLastCalledWith("/employees/jane?setup=details");
  await act(async () => host.querySelector('[data-testid="setup-person-employment-jane"]').click());
  expect(mockNavigate).toHaveBeenLastCalledWith("/employees/jane?setup=employment");
  expect(api.post).not.toHaveBeenCalled();
});

test("optional tasks do not take priority over generating a roster", async () => {
  withSetup({ complete: false, done: 5, total: 6,
    steps: setupSteps.map(s => ({ ...s, done: !["constraints", "roster"].includes(s.id) })) });
  await act(async () => root.render(<Dashboard />));
  expect(host.querySelector('[data-testid="setup-step-roster"]').textContent).toContain("Start here");
  expect(host.querySelector('[data-testid="setup-step-constraints"]').textContent).not.toContain("Start here");
  expect(host.querySelector('[data-testid="setup-step-constraints"]').textContent).toContain("Optional");
  expect(host.querySelector(".db-setup-rest").textContent).toBe("· Generate and approve a week");
});

test("a checklist load failure is visible and retry restores the real steps", async () => {
  const get = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/setup-status" ? Promise.reject(new Error("Offline")) : get(path));
  await act(async () => root.render(<Dashboard />));
  expect(host.textContent).toContain("The setup checklist could not be loaded");
  expect(button("Review steps")).toBeUndefined();
  withSetup({ complete: false, done: 0, total: 6, steps: setupSteps });
  await act(async () => button("Retry checklist").click());
  expect(host.querySelectorAll("#db-setup-steps li")).toHaveLength(7);
  expect(host.textContent).not.toContain("could not be loaded");
});

test.each([
  [["Deli"], ["Shop Floor", "Deli"], "Deli"],
  [["unconfigured-private-value"], ["Shop Floor", "Deli"], null],
  [["unconfigured-private-value", "Deli"], ["Shop Floor", "Deli"], "Deli"],
  [["Shop Floor", "Deli"], ["Shop Floor", "Deli"], null],
  [["Deli"], undefined, null],
  [undefined, ["Shop Floor", "Deli"], null],
])("a named setup task switches only to a configured group (memberships=%j, groups=%j)", async (departments, groups, target) => {
  withSetup({ complete: false, done: 0, total: 6, steps: setupSteps });
  const get = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/employees"
    ? Promise.resolve({ data: [{ employee_id: "jane", departments }] })
    : path === "/shop" ? Promise.resolve({ data: { name: "Test shop", current_department: "Shop Floor", departments: groups } })
      : get(path));
  const { ROSTER_GROUP_KEY, SHOP_CHANGED } = require("@/lib/api");
  const changed = jest.fn();
  window.addEventListener(SHOP_CHANGED, changed);
  localStorage.setItem(ROSTER_GROUP_KEY, "Shop Floor");
  try {
    await act(async () => root.render(<Dashboard />));
    await act(async () => host.querySelector('[data-testid="setup-person-details-jane"]').click());
    expect(localStorage.getItem(ROSTER_GROUP_KEY)).toBe(target || "Shop Floor");
    expect(changed).toHaveBeenCalledTimes(target ? 1 : 0);
    expect(mockNavigate).toHaveBeenLastCalledWith("/employees/jane?setup=details");
  } finally {
    window.removeEventListener(SHOP_CHANGED, changed);
    localStorage.removeItem(ROSTER_GROUP_KEY);
  }
});
