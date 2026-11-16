import React, { act } from "react";
import { createRoot } from "react-dom/client";
import fs from "fs";
import Employees, { DeleteEmployeeDialog } from "./Employees";
const mockSetupParams = new URLSearchParams();
const mockEmployeeParams = { employeeId: "martin" };

jest.mock("react-router-dom", () => ({
  useNavigate: () => () => {},
  useParams: () => mockEmployeeParams,
  useSearchParams: () => [mockSetupParams, jest.fn()],
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
  mockSetupParams.delete("setup");
  mockEmployeeParams.employeeId = "martin";
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
});
const click = async (button) => act(async () => button.click());
const editor = () => document.querySelector('[role="dialog"]');
const activateTab = async (label) => {
  const tab = [...editor().querySelectorAll('[role="tab"]')].find((item) => item.textContent === label);
  await act(async () => tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })));
};
const type = async (input, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
});

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

test.each(["details", "employment"])("setup %s opens the named employee's existing form without saving", async task => {
  mockSetupParams.set("setup", task);
  const employee = { employee_id: "martin", name: "Martin", role: "Crew", age_group: "18_plus",
    hourly_rate: 13, max_weekly_hours: 40, departments: ["Shop Floor"], is_active: true };
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/employees" ? [employee]
    : path === "/shop" ? { departments: ["Shop Floor"] } : path === "/shop/hierarchy" ? { hierarchy: ["Crew"] } : [] }));
  await act(async () => root.render(<Employees />));
  const dialog = editor();
  expect(dialog).not.toBeNull();
  expect(dialog.querySelector('[data-testid="emp-name"]').value).toBe("Martin");
  if (task === "details") expect(document.activeElement).toBe(dialog.querySelector('[data-testid="emp-rate"]'));
  else expect(document.activeElement).toBe(dialog.querySelector('select[name="employment_type"]'));
  expect(dialog.querySelector('[aria-selected="true"]').textContent).toBe("Employment");
  expect(api.put).not.toHaveBeenCalled();
  await click(dialog.querySelector('[aria-label="Close dialog"]'));
  expect(editor()).toBeNull();
  await act(async () => root.render(<Employees />));
  expect(editor()).toBeNull();
});

test("the add-people setup action opens a new form, not an existing employee", async () => {
  mockSetupParams.set("setup", "team");
  mockEmployeeParams.employeeId = undefined;
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/employees" ? []
    : path === "/shop" ? { departments: ["Deli"], current_department: "Deli" }
      : path === "/shop/hierarchy" ? {} : [] }));
  await act(async () => root.render(<Employees />));
  expect(editor().querySelector("h2").textContent).toBe("New employee");
  const name = editor().querySelector('[data-testid="emp-name"]');
  expect(name.value).toBe("");
  const ageGroup = editor().querySelector('[data-testid="emp-age-group"]');
  expect(ageGroup.value).toBe("");
  expect(ageGroup.checkValidity()).toBe(false);
  expect([...ageGroup.options].slice(1).map(option => option.textContent))
    .toEqual(["Under 16", "16–17", "18 or over"]);
  expect(document.activeElement).toBe(name);
  expect(editor().querySelector('[data-testid="emp-department-Deli"]').getAttribute("aria-pressed")).toBe("true");
  expect(api.put).not.toHaveBeenCalled();
});

test("an hourly rate with cents is valid and saves without rounding to half euros", async () => {
  mockSetupParams.set("setup", "details");
  const employee = { employee_id: "martin", name: "Martin", role: "Crew", age_group: "18_plus",
    hourly_rate: 15, max_weekly_hours: 40, departments: ["Shop Floor"], is_active: true,
    employment_type: "hourly" };
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/employees" ? [employee]
    : path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/shop/hierarchy" ? { hierarchy: ["Crew"] } : [] }));
  api.put.mockImplementation((path, data) => Promise.resolve({ data }));
  await act(async () => root.render(<Employees />));
  const input = editor().querySelector('[data-testid="emp-rate"]');
  await type(input, "16.15");
  expect(input.checkValidity()).toBe(true);
  await click(editor().querySelector('[data-testid="btn-save-employee"]'));
  expect(api.put).toHaveBeenCalledWith("/employees/martin", expect.objectContaining({
    hourly_rate: 16.15, age_group: "18_plus",
  }));
  expect(api.put.mock.calls[0][1]).not.toHaveProperty("age");
});

test.each(["weekly", ""])("pay review opens the contract pay field, not an hourly rate (period=%s)", async period => {
  mockSetupParams.set("setup", "details");
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/employees" ? [{
    employee_id: "martin", name: "Martin", role: "Crew", departments: ["Shop Floor"],
    max_weekly_hours: 40, employment_type: "full_time_contract", contract_pay_period: period,
  }] : path === "/shop" ? { departments: ["Shop Floor"] }
    : path === "/shop/hierarchy" ? { hierarchy: ["Crew"] } : [] }));
  await act(async () => root.render(<Employees />));
  expect(editor().querySelector('[data-testid="emp-rate"]')).toBeNull();
  expect(document.activeElement).toBe(editor().querySelector(`[data-testid="${period ? "emp-salary" : "emp-pay-weekly"}"]`));
  expect(api.put).not.toHaveBeenCalled();
});

test("one save retains edits across tabs, preserves inactive status and reveals invalid fields", async () => {
  const employee = { employee_id: "martin", name: "Martin", role: "Crew", age_group: "18_plus",
    departments: ["Shop Floor"], is_active: false, max_weekly_hours: 40, employment_type: "hourly" };
  api.get.mockImplementation(path => Promise.resolve({ data: path === "/employees" ? [employee]
    : path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/shop/hierarchy" ? { hierarchy: ["Crew"] } : [] }));
  api.put.mockResolvedValue({ data: employee });
  await act(async () => root.render(<Employees />));
  await click(host.querySelector('[data-testid="btn-edit-martin"]'));
  expect(editor().querySelector('[data-testid="emp-active"]')).toBeNull();
  const name = editor().querySelector('[data-testid="emp-name"]');
  await type(name, "Marty");
  await activateTab("Holidays");
  const opening = editor().querySelector('[data-testid="emp-opening-holiday"]');
  await type(opening, "-1");
  await activateTab("Profile");
  expect(editor().querySelector('[aria-selected="true"]').textContent).toBe("Profile");
  const save = editor().querySelector('[data-testid="btn-save-employee"]');
  await click(save);
  expect(api.put).not.toHaveBeenCalled();
  expect(editor().querySelector('[aria-selected="true"]').textContent).toBe("Holidays");
  expect(document.activeElement).toBe(opening);
  await type(opening, "14.5");
  await click(save);
  expect(api.put).toHaveBeenCalledTimes(1);
  expect(api.put).toHaveBeenCalledWith("/employees/martin", expect.objectContaining({
    name: "Marty", opening_holiday_hours: 14.5, is_active: false,
  }));
});
