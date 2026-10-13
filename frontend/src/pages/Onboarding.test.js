import React, { act } from "react";
import { createRoot } from "react-dom/client";
import fs from "fs";
import Onboarding from "./Onboarding";

jest.mock("react-router-dom", () => ({ useNavigate: () => () => {} }), { virtual: true });
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), put: jest.fn() },
  errorMessage: () => "",
  DAY_LABELS: {}, DAYS: [], announceShopChange: jest.fn(),
}), { virtual: true });
const { api } = require("@/lib/api");

test("roster group removal requires app confirmation and Cancel preserves the group", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const shop = {
    onboarded: true, name: "Test shop", hours: [],
    min_shift_hours: 4, max_shift_hours: 9,
    departments: ["Shop Floor", "Deli"], multi_department: true,
    roles: ["Manager"], role_hierarchy: ["Manager"],
  };
  api.get.mockImplementation((path) => Promise.resolve({ data: path === "/shop"
    ? shop : { hierarchy: ["Manager"], supervisory: ["Manager"] } }));
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const click = async (element) => act(async () => element.click());
  const remove = () => host.querySelector('[aria-label="Remove Deli"]');
  try {
    await act(async () => root.render(<Onboarding />));
    await click(remove());
    let dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog.textContent).toContain("Remove Deli?");
    expect(remove()).not.toBeNull();
    await click([...dialog.querySelectorAll("button")].find((b) => b.textContent === "Cancel"));
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    expect(remove()).not.toBeNull();
    await click(remove());
    dialog = document.querySelector('[role="alertdialog"]');
    await click([...dialog.querySelectorAll("button")].find((b) => b.textContent === "Remove"));
    expect(remove()).toBeNull();
    expect(api.put).not.toHaveBeenCalled(); // Still requires Save changes.
    expect(fs.readFileSync(require.resolve("./Onboarding"), "utf8")).not.toContain("window.confirm");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

test("removing the last supervisory role clears its saved closing selection", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  api.put.mockClear();
  api.put.mockResolvedValue({ data: {} });
  const shop = {
    onboarded: true, name: "Test shop", hours: [],
    min_shift_hours: 4, max_shift_hours: 9,
    departments: ["Shop Floor"], roles: ["Manager", "Crew"],
  };
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/shop"
    ? shop : { hierarchy: ["Manager", "Crew"], supervisory: ["Manager"], supervisory_roles: ["Manager"] } }));
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Onboarding />));
    const row = [...host.querySelectorAll(".ss-rolerow")].find(el => el.textContent.includes("Manager"));
    await act(async () => [...row.querySelectorAll("button")].find(el => el.textContent === "Remove").click());
    const dialog = document.querySelector('[role="alertdialog"]');
    await act(async () => [...dialog.querySelectorAll("button")].find(el => el.textContent === "Remove").click());
    await act(async () => host.querySelector('[data-testid="btn-save-settings"]').click());
    expect(api.put).toHaveBeenCalledWith("/shop", expect.objectContaining({ roles: ["Crew"], supervisory_roles: [] }));
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
