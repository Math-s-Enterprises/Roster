import React, { act } from "react";
import { createRoot } from "react-dom/client";
import RosterView from "./RosterView";

const mockParams = new URLSearchParams("week=2026-10-05");
const mockSetParams = jest.fn();
jest.mock("react-router-dom", () => ({
  useSearchParams: () => [mockParams, mockSetParams],
  Link: ({ children, to }) => <a href={to}>{children}</a>,
}), { virtual: true });
jest.mock("@/context/AuthContext", () => ({ useAuth: () => ({ user: {} }) }), { virtual: true });
jest.mock("@/components/RosterPrintSheet", () => () => null, { virtual: true });
jest.mock("canvas-confetti", () => jest.fn());
jest.mock("jspdf", () => jest.fn());
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("../lib/api"),
  api: { get: jest.fn(), post: jest.fn() },
}), { virtual: true });
const { api } = require("@/lib/api");
let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.clearAllMocks();
  mockParams.set("week", "2026-10-05");
  mockParams.delete("roster");
  mockParams.delete("review");
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
});

test.each([false, true])("roster generation waits for the leave review and an explicit choice (dashboard=%s)", async dashboard => {
  if (dashboard) mockParams.set("review", "generate");
  const employees = [
    { employee_id: "one", name: "Nora Walsh", role: "Cashier", departments: ["Deli"] },
    { employee_id: "two", name: "Jamie Byrne", role: "Cashier", departments: ["Deli"] },
    { employee_id: "past", name: "Past Staff", is_active: false },
  ];
  const leave = [
    { employee_id: "one", scope: "employee", date: "2026-10-02", end_date: "2026-10-05" },
    { employee_id: "one", scope: "unavailable", date: "2026-10-06" },
    { employee_id: "two", scope: "sick", date: "2026-10-09" },
    { employee_id: "two", scope: "employee", date: "2026-10-12" },
    { employee_id: "past", scope: "employee", date: "2026-10-09" },
    { scope: "shop", date: "2026-10-10" },
  ];
  api.get.mockImplementation(path => Promise.resolve({ data: {
    "/shop": { departments: ["Shop Floor", "Deli"], current_department: "Deli" },
    "/employees": employees, "/holidays": leave,
  }[path] || [] }));
  api.post.mockResolvedValue({ data: { version: "v1.0", shifts: [] } });
  await act(async () => root.render(<RosterView />));
  const trigger = host.querySelector('[data-testid="btn-generate"]');
  if (dashboard) {
    expect(mockSetParams).toHaveBeenCalledWith(new URLSearchParams("week=2026-10-05"), { replace: true });
    mockParams.delete("review");
  } else {
    await act(async () => trigger.click());
  }
  const dialog = document.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain("Week of 5 Oct 2026 · Deli");
  expect(dialog.textContent).toContain("2 staff have leave recorded this week");
  expect([...dialog.querySelectorAll(".roster-gen-people li")].map(row => row.textContent)).toEqual([
    "Nora WalshMon 5 – Tue 6 Oct", "Jamie ByrneFri 9 Oct",
  ]);
  expect(dialog.querySelector("a").getAttribute("href")).toBe("/calendar?week=2026-10-05&group=Deli");
  expect(api.get).toHaveBeenCalledWith("/holidays", expect.objectContaining({
    params: { week_start: "2026-10-05" }, headers: { "X-Roster-Group": "Deli" },
  }));
  expect(api.post).not.toHaveBeenCalled();
  const action = label => [...document.querySelectorAll('[role="dialog"] button')].find(b => b.textContent === label);
  await act(async () => action("Go back").click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(api.post).not.toHaveBeenCalled();
  await act(async () => trigger.click());
  await act(async () => action("Generate draft").click());
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith("/roster/generate", {
    week_start: "2026-10-05", department: "Deli", keep_pinned: false, only_day: null,
  });
});

test.each([false, true])("the leave review distinguishes an empty week from a failed lookup (failed=%s)", async failed => {
  api.get.mockImplementation(path => path === "/holidays" && failed
    ? Promise.reject(new Error("Offline"))
    : Promise.resolve({ data: path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/employees" ? [{ employee_id: "one", name: "Nora Walsh" }] : [] }));
  await act(async () => root.render(<RosterView />));
  await act(async () => host.querySelector('[data-testid="btn-generate"]').click());
  const dialog = document.querySelector('[role="dialog"]');
  expect(dialog.querySelector('[role="status"]').textContent).toBe(failed
    ? "Could not check leave for this week."
    : "No leave recorded for this week.");
  expect(dialog.querySelector("a").textContent).toBe("Review leave");
  expect(api.post).not.toHaveBeenCalled();
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
});

test("pending employee data is loading, never an empty shop; only the selected week is fetched", async () => {
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  api.get.mockImplementation(path => path === "/employees" ? pending
    : Promise.resolve({ data: path === "/shop" ? { departments: ["Shop Floor"] } : [] }));
  await act(async () => root.render(<RosterView />));
  expect(host.textContent).toContain("Loading roster…");
  expect(host.querySelector('[role="status"]').closest(".wr-page")).not.toBeNull();
  expect(host.querySelector('[role="status"]').className).toBe("wr-empty");
  expect(host.querySelector('[role="status"] h2')).toBeNull();
  expect(host.textContent).not.toContain("No employees yet");
  await act(async () => finish({ data: [{ employee_id: "one", name: "Employee", role: "Cashier" }] }));
  expect(host.textContent).not.toContain("Loading roster…");
  expect(host.textContent).not.toContain("No employees yet");
  expect(api.get).toHaveBeenCalledWith("/rosters", { params: { week_start: "2026-10-05" } });
  expect(api.get.mock.calls.filter(([path]) => path === "/employees")).toHaveLength(1);
});

test("failed loads offer retry; an empty-shop message appears only after a successful empty response", async () => {
  api.get.mockRejectedValue(new Error("Network Error"));
  await act(async () => root.render(<RosterView />));
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  expect(host.querySelector('[role="alert"]').closest(".wr-page")).not.toBeNull();
  expect(host.querySelector("button").className).toBe("wr-btn wr-btn-1");
  expect(host.textContent).not.toContain("No employees yet");
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/shop" ? {} : [] }));
  await act(async () => host.querySelector("button").click());
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.textContent).toContain("No employees yet");
});

test("a link to a specific archived version still fetches that version directly", async () => {
  mockParams.set("roster", "saved-version");
  api.get.mockResolvedValue({ data: [] });
  api.get.mockImplementation(path => Promise.resolve({ data:
    path === "/shop" ? {} : path === "/rosters/saved-version"
      ? { roster_id: "saved-version", department: "Shop Floor" } : [] }));
  await act(async () => root.render(<RosterView />));
  expect(api.get).toHaveBeenCalledWith("/rosters/saved-version");
});

test.each([false, true])("approval breaches appear in Needs attention (overridable=%s)", async (overridable) => {
  const breach = {
    employee_id: "one", name: "Employee", rule: "weekly_hours",
    message: "Employee exceeds their weekly limit.", overridable,
  };
  api.get.mockImplementation(path => Promise.resolve({ data:
    path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/employees" ? [{ employee_id: "one", name: "Employee", role: "Cashier" }]
      : path === "/rosters" ? [{ roster_id: "draft", week_start: "2026-10-05", department: "Shop Floor", shifts: [], edit_warnings: [breach.message] }]
      : path === "/rosters/draft/audit" ? { people: [{ employee_id: "one", breaches: [breach] }] }
      : [] }));
  await act(async () => root.render(<RosterView />));
  expect(host.textContent).toContain("Needs attention (1)");
  expect(host.textContent).toContain(breach.message);
  expect(host.textContent).not.toContain("this week is ready to approve");
  expect(host.textContent).not.toContain("Nothing here blocks approval");
});

test("an unavailable approval audit never claims the week is ready", async () => {
  api.get.mockImplementation(path => path.endsWith("/audit")
    ? Promise.reject(new Error("Network Error"))
    : Promise.resolve({ data: path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/employees" ? [{ employee_id: "one", name: "Employee", role: "Cashier" }]
      : path === "/rosters" ? [{ roster_id: "draft", week_start: "2026-10-05", department: "Shop Floor", shifts: [] }]
      : [] }));
  await act(async () => root.render(<RosterView />));
  expect(host.textContent).toContain("Approval checks are not available yet");
  expect(host.textContent).not.toContain("this week is ready to approve");
});

test("the live roster grid shows last Sunday's Deli night on Monday, not Sunday", async () => {
  api.get.mockImplementation(path => Promise.resolve({ data:
    path === "/shop" ? { departments: ["Shop Floor", "Deli"] }
      : path === "/employees" ? [{ employee_id: "one", name: "Employee", role: "Cashier", departments: ["Shop Floor", "Deli"] }]
      : path === "/rosters" ? [{
        roster_id: "draft", week_start: mockParams.get("week"), department: "Shop Floor", shifts: [],
        external_shifts: [{ employee_id: "one", day: "sun", start: "22:00", end: "06:00", department: "Deli", week_offset: -7 }],
      }]
      : path.endsWith("/audit") ? { people: [] } : [] }));
  await act(async () => root.render(<RosterView />));
  const monday = host.querySelector('[data-testid="cell-one-mon"]');
  expect(monday.textContent).toContain("Deli");
  expect(monday.textContent).toContain("00:00–06:00");
  expect(host.querySelector('[data-testid="cell-one-sun"]').textContent).not.toContain("Deli");
});

test("a previous roster's audit cannot give a newer week an all-clear", async () => {
  let finishOldAudit;
  const oldAudit = new Promise(resolve => { finishOldAudit = resolve; });
  api.get.mockImplementation(path => {
    if (path === "/rosters/2026-10-05/audit") return oldAudit;
    if (path.endsWith("/audit")) return Promise.resolve({ data: { people: [{
      employee_id: "one", breaches: [{ name: "Employee", message: "New week breach" }],
    }] } });
    return Promise.resolve({ data: path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/employees" ? [{ employee_id: "one", name: "Employee", role: "Cashier" }]
      : path === "/rosters" ? [{ roster_id: mockParams.get("week"), week_start: mockParams.get("week"), department: "Shop Floor", shifts: [] }]
      : [] });
  });
  await act(async () => root.render(<RosterView />));
  mockParams.set("week", "2026-10-12");
  await act(async () => root.render(<RosterView />));
  await act(async () => finishOldAudit({ data: { people: [] } }));
  expect(host.textContent).toContain("New week breach");
  expect(host.textContent).not.toContain("this week is ready to approve");
});

test.each([false, true])("an older request cannot replace newer week data (failure=%s)", async (failure) => {
  let finish, fail;
  const pending = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  let employeeRequests = 0;
  api.get.mockImplementation(path => {
    if (path === "/employees" && employeeRequests++ === 0) return pending;
    return Promise.resolve({ data: path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/employees" ? [{ employee_id: "new", name: "Employee", role: "Cashier" }] : [] });
  });
  await act(async () => root.render(<RosterView />));
  mockParams.set("week", "2026-10-12");
  await act(async () => root.render(<RosterView />));
  expect(api.get).toHaveBeenCalledWith("/rosters", { params: { week_start: "2026-10-12" } });
  await act(async () => failure ? fail(new Error("Old request failed")) : finish({ data: [] }));
  expect(host.textContent).not.toContain("No employees yet");
  expect(host.textContent).not.toContain("Loading roster…");
  expect(host.querySelector('[role="alert"]')).toBeNull();
});
