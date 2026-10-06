import React, { act } from "react";
import { createRoot } from "react-dom/client";
import fs from "fs";
import Employees, { DeleteEmployeeDialog } from "./Employees";

jest.mock("react-router-dom", () => ({
  useNavigate: () => () => {},
  useParams: () => ({ employeeId: "martin" }),
}), { virtual: true });
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), put: jest.fn() },
  errorMessage: () => "",
  fmtMoney: () => "",
  CURRENCY: "€",
  DAY_SHORT: {},
  DAY_LABELS: {},
  DAYS: [],
  shiftHours: () => 0,
}), { virtual: true });
jest.mock("@/components/ContactImportPanel", () => () => null, { virtual: true });
const { api } = require("@/lib/api");
let host, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host);
  root = createRoot(host);
  jest.clearAllMocks();
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
});
const click = async (button) => act(async () => button.click());

test("employee deletion uses the same app card and offers inactive instead", async () => {
  const onConfirm = jest.fn(), onInactive = jest.fn();
  await act(async () => root.render(
    <DeleteEmployeeDialog
      employee={{ name: "Martin" }}
      busy={false}
      onClose={() => {}}
      onConfirm={onConfirm}
      onInactive={onInactive}
    />,
  ));

  const dialog = document.querySelector('[role="alertdialog"]');
  expect(dialog.className).toContain("card elevated p-6");
  expect(dialog.textContent).toContain("Remove Martin?");
  expect(dialog.textContent).toContain("Past rosters are kept.");
  await click([...dialog.querySelectorAll("button")].find(b => b.textContent === "Mark inactive instead"));
  expect(onInactive).toHaveBeenCalledTimes(1);
  expect(onConfirm).not.toHaveBeenCalled();
  for (const page of ["Employees", "Onboarding", "AIRules", "FixedShifts", "SickReport"]) {
    expect(fs.readFileSync(require.resolve(`./${page}`), "utf8")).not.toContain("window.confirm");
  }
});

test("inactive action persists status, separates leavers and allows reactivation", async () => {
  let employee = { employee_id: "martin", name: "Martin", role: "Manager",
    is_active: true, departments: ["Shop Floor"], max_weekly_hours: 40 };
  const leaver = { ...employee, employee_id: "leaver", name: "Former colleague", is_active: false };
  api.get.mockImplementation(path => Promise.resolve({ data:
    path === "/employees" ? [employee, leaver] : path === "/shop/hierarchy"
      ? { supervisory: ["Manager"] } : path === "/shop" ? {} : [] }));
  api.put.mockImplementation((path, data) => { employee = data; return Promise.resolve({ data }); });
  await act(async () => root.render(<Employees />));
  expect(host.querySelector('[data-testid="employee-card-leaver"]')).toBeNull();
  expect([...host.querySelectorAll("button")].find(b => b.textContent === "Mark inactive").className)
    .toBe("esp-act esp-act-2");
  await click([...host.querySelectorAll("button")].find(b => b.textContent === "Mark inactive"));
  expect(api.put).toHaveBeenCalledWith("/employees/martin", expect.objectContaining({
    is_active: false, name: "Martin", max_weekly_hours: 40, departments: ["Shop Floor"],
  }));
  expect(host.textContent).toContain("Inactive employees");
  expect(host.querySelector('[data-testid="employee-card-leaver"]')).not.toBeNull();
  const reactivate = [...host.querySelectorAll("button")].find(b => b.textContent === "Reactivate");
  expect(reactivate.className).toBe("esp-act esp-act-2");
  await click(reactivate);
  expect(employee.is_active).toBe(true);
  expect(host.querySelector('[data-testid="employee-card-martin"]')).not.toBeNull();
  expect(host.querySelector('[data-testid="employee-card-leaver"]')).toBeNull();
});
