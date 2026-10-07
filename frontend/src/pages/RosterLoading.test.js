import React, { act } from "react";
import { createRoot } from "react-dom/client";
import RosterView from "./RosterView";

const mockParams = new URLSearchParams("week=2026-10-05");
jest.mock("react-router-dom", () => ({
  useSearchParams: () => [mockParams, jest.fn()],
  Link: ({ children }) => <span>{children}</span>,
}), { virtual: true });
jest.mock("@/context/AuthContext", () => ({ useAuth: () => ({ user: {} }) }), { virtual: true });
jest.mock("@/components/RosterPrintSheet", () => () => null, { virtual: true });
jest.mock("canvas-confetti", () => jest.fn());
jest.mock("jspdf", () => jest.fn());
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("../lib/api"),
  api: { get: jest.fn() },
}), { virtual: true });
const { api } = require("@/lib/api");
let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.clearAllMocks();
  mockParams.delete("roster");
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
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
