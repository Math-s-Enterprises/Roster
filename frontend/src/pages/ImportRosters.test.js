import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ImportRosters from "./ImportRosters";

jest.mock("@/lib/api", () => ({
  ...jest.requireActual("../lib/api"),
  api: { get: jest.fn(), post: jest.fn() },
}), { virtual: true });
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
const { api } = require("@/lib/api");
const { toast } = require("sonner");
const passwordMessage = "This Excel file is password-protected. Open it in Excel, save a copy without password protection, then upload that copy.";
let host, root;

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.clearAllMocks();
  api.get.mockImplementation(path => Promise.resolve({ data:
    path === "/shop" ? { departments: ["Shop Floor"] }
      : path === "/imports/capabilities" ? { spreadsheet: true, csv: true, pdf: false, image: false, reasons: {} }
      : path === "/imports/learning-summary" ? null : [] }));
  api.post.mockRejectedValue({ response: { data: { detail: passwordMessage } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function upload(filename) {
  const input = host.querySelector('[data-testid="import-file"]');
  Object.defineProperty(input, "files", { configurable: true, value: [new File(["fixture"], filename)] });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
}

test("a password-protected upload shows the server's recovery instructions and leaves the upload usable", async () => {
  await act(async () => root.render(<ImportRosters />));
  await upload("locked.xlsx");
  expect(toast.error).toHaveBeenCalledWith(passwordMessage);
  expect(host.textContent).toContain("Drop a roster file here");
  expect(host.textContent).not.toContain("Weeks to import");
  expect(host.querySelector('[data-testid="import-file"]').disabled).toBe(false);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe("/imports");
});

test("format availability is customer-facing even when the server sends setup instructions", async () => {
  const get = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/imports/capabilities"
    ? Promise.resolve({ data: { spreadsheet: true, csv: true, image: false, pdf: false,
      reasons: { llm: "Set ANTHROPIC_API_KEY in backend/.env", pdf_renderer: "pip install pymupdf" } } })
    : get(path));
  await act(async () => root.render(<ImportRosters />));
  expect(host.querySelector(".im-formats").textContent).toBe("Available: Excel and CSV. Currently unavailable: PDF and photos.");
  expect(host.textContent).not.toMatch(/ANTHROPIC|backend\/\.env|pip install|server setup|need.*AI/i);
  await upload("roster.pdf");
  expect(toast.error).toHaveBeenLastCalledWith("PDF uploads are currently unavailable. Use Excel or CSV.");
  await upload("roster.png");
  expect(toast.error).toHaveBeenLastCalledWith("Photo uploads are currently unavailable. Use Excel or CSV.");
  expect(api.post).not.toHaveBeenCalled();
});

test("available PDF uploads are not labelled unavailable when only photos are disabled", async () => {
  const get = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/imports/capabilities"
    ? Promise.resolve({ data: { spreadsheet: true, csv: true, pdf: true, image: false, reasons: {} } })
    : get(path));
  await act(async () => root.render(<ImportRosters />));
  expect(host.querySelector(".im-formats").textContent).toBe("Available: Excel, CSV, and PDF. Currently unavailable: photos.");
});

test("an unavailable-upload response from an older server does not expose its setup instructions", async () => {
  api.post.mockRejectedValueOnce({ response: { status: 503,
    data: { detail: "Set ANTHROPIC_API_KEY in backend/.env" } } });
  await act(async () => root.render(<ImportRosters />));
  await upload("roster.xlsx");
  expect(toast.error).toHaveBeenLastCalledWith("This file format is currently unavailable. Use Excel or CSV.");
});

test("an unlocked copy can be uploaded after the password-protection error", async () => {
  await act(async () => root.render(<ImportRosters />));
  await upload("locked.xlsx");
  api.post.mockResolvedValueOnce({ data: {
    filename: "unlocked.xlsx", kind: "spreadsheet", pages: 1,
    summary: { weeks: 1, shifts: 1, employees: 0, new_employees: 0, unreadable_cells: 0,
      date_range: ["2026-10-26", "2026-10-26"] },
    people: [], weeks: [{ week_start: "2026-10-26", shifts: 1, warnings: [] }],
  } });
  await upload("unlocked.xlsx");
  expect(api.post).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("unlocked.xlsx");
  expect(host.textContent).toContain("Weeks to import");
  expect(toast.error).toHaveBeenCalledTimes(1);
});

const review = {
  import_id: "review-fixture", filename: "roster-with-a-long-filename-for-review.xlsx",
  kind: "spreadsheet", pages: 2, notes: ["Check the highlighted hours before importing."],
  department: "Shop Floor", role_options: ["Shop Floor", "Customer Service Manager"],
  summary: { weeks: 2, shifts: 145, employees: 2, new_employees: 1, unreadable_cells: 10,
    date_range: ["2026-10-19", "2026-10-26"] },
  weeks: [
    { week_start: "2026-10-19", shifts: 74, already_imported: true, sheet_name: "Week ending 25 October",
      warnings: ["First warning", "Second warning", "Third warning must remain reachable"] },
    { week_start: "2026-10-26", shifts: 71, sheet_name: "Week ending 1 November", warnings: [] },
  ],
  people: [
    { name: "Alex", role: "Shop Floor", role_in_file: "Shop Floor", shifts: 74, matched_employee_id: "existing-alex" },
    { name: "A very long employee name that must remain readable", role: "Customer Service Manager",
      role_in_file: "Customer Services Supervisor", shifts: 71 },
  ],
};

async function openReview(preview = review) {
  const existingGet = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/employees"
    ? Promise.resolve({ data: [{ employee_id: "existing-alex", name: "Alex", role: "Cashier", departments: ["Shop Floor"] }] })
    : existingGet(path));
  api.post.mockResolvedValueOnce({ data: preview });
  await act(async () => root.render(<ImportRosters />));
  await upload(preview.filename);
}

test("the themed review separates file totals from selected weeks and keeps full names and warnings", async () => {
  await openReview();
  expect(host.querySelector(".im-page.im-review")).not.toBeNull();
  expect(host.querySelector(".im-review h1").textContent).toBe("Review your import");
  expect([...host.querySelectorAll(".im-review-stats dd")].map(el => el.textContent)).toEqual(["2", "145", "2"]);
  expect(host.querySelector(".im-review-file").textContent).toContain("2 worksheets read");
  expect(host.querySelector(".im-review-total").textContent).toContain("1 week selected · 71 shifts");
  expect(host.querySelector('[aria-label="Import week beginning 2026-10-19"]').checked).toBe(false);
  expect(host.querySelector('[aria-label="Import week beginning 2026-10-26"]').checked).toBe(true);
  expect(host.querySelector(".im-review-warnings summary").textContent).toBe("3 warnings to review");
  expect(host.querySelectorAll(".im-review-warnings li")).toHaveLength(3);
  expect(host.querySelector(".im-review-person-name").textContent).toBe("Alex");
  const longName = host.querySelectorAll(".im-review-person-name")[1];
  expect(longName.textContent).toBe(review.people[1].name);
  expect(longName.className).not.toContain("truncate");
  expect(host.textContent).toContain(review.people[1].role_in_file);
  for (const select of host.querySelectorAll(".im-review-match")) {
    expect(host.querySelector('label[for="' + select.id + '"]')).not.toBeNull();
  }
  expect(host.querySelector('[aria-label="Unreadable cells"]').textContent).toContain("10 cells could not be read");
  expect(host.querySelectorAll(".glass, .text-cyan-400, .truncate")).toHaveLength(0);
});

test("select all and individual weeks update the total and prevent an empty import", async () => {
  await openReview();
  const selectAll = () => host.querySelector(".im-review-select-all");
  await act(async () => selectAll().click());
  expect(host.querySelector(".im-review-total").textContent).toContain("2 weeks selected · 145 shifts");
  expect(selectAll().textContent).toBe("Deselect all");
  await act(async () => selectAll().click());
  expect(host.querySelector('[data-testid="btn-commit-import"]').disabled).toBe(true);
  expect(host.querySelector(".im-review-total").textContent).toContain("Select at least one week");
  await act(async () => host.querySelector('[aria-label="Import week beginning 2026-10-26"]').click());
  expect(host.querySelector(".im-review-total").textContent).toContain("1 week selected · 71 shifts");
  expect(host.querySelector('[data-testid="btn-commit-import"]').disabled).toBe(false);
  expect(api.post).toHaveBeenCalledTimes(1);
});

test("past staff mapping and confirmation keep the existing import payload", async () => {
  await openReview();
  const select = host.querySelectorAll(".im-review-match")[1];
  await act(async () => {
    select.value = "__past_staff__";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.querySelector(".im-review-past").textContent).toContain("keeping 71 shifts of history");
  let finish;
  api.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await act(async () => host.querySelector('[data-testid="btn-commit-import"]').click());
  expect(api.post).toHaveBeenLastCalledWith("/imports/review-fixture/commit", expect.objectContaining({
    week_starts: ["2026-10-26"], employee_map: { Alex: "existing-alex" },
    past_staff: [review.people[1].name],
  }));
  expect(host.querySelector('[data-testid="btn-commit-import"]').disabled).toBe(true);
  expect([...host.querySelectorAll(".im-review-match, .im-review-week-choice input")].every(el => el.disabled)).toBe(true);
  await act(async () => finish({ data: { weeks_imported: 1, employees_created: 0 } }));
  expect(toast.success).toHaveBeenCalledWith("Imported 1 week");
  expect(host.textContent).toContain("Drop a roster file here");
});

test("choosing another file leaves review without committing anything", async () => {
  await openReview();
  await act(async () => host.querySelector(".im-head button").click());
  expect(host.textContent).toContain("Drop a roster file here");
  expect(host.querySelector(".im-review")).toBeNull();
  expect(api.post).toHaveBeenCalledTimes(1);
});

test("image-derived previews and import notes retain their themed review warnings", async () => {
  await openReview({ ...review, kind: "pdf", needs_review: true });
  expect(host.querySelector('[aria-label="Check the image reading"]').textContent).toContain("Check the PDF reading");
  expect(host.querySelector('[aria-label="Import notes"]').textContent).toContain(review.notes[0]);
  expect(host.querySelector(".im-review-file").textContent).toContain("2 pages read");
  expect(host.querySelectorAll(".glass, .text-cyan-400")).toHaveLength(0);
});

test("the selected image week is submitted and its date acknowledgement stays visible before import", async () => {
  const existingGet = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/imports/capabilities"
    ? Promise.resolve({ data: { spreadsheet: true, csv: true, image: true, pdf: true, reasons: {} } })
    : existingGet(path));
  const notice = "Using your selected week beginning 2026-10-26.";
  const preview = { ...review, filename: "roster.png", kind: "image", needs_review: true,
    summary: { ...review.summary, weeks: 1, date_range: ["2026-10-26", "2026-10-26"] },
    weeks: [{ week_start: "2026-10-26", shifts: 71, warnings: [notice] }],
    date_selection: { requested: "2026-10-26", selected_weeks: ["2026-10-26"], file_weeks: [] },
  };
  api.post.mockResolvedValueOnce({ data: preview });
  await act(async () => root.render(<ImportRosters />));
  const input = host.querySelector('input[type="date"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "2026-10-26");
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await upload("roster.png");
  expect(api.post.mock.calls[0][1].get("week_start")).toBe("2026-10-26");
  const warnings = host.querySelector(".im-review-warnings");
  expect(warnings.textContent).toContain(notice);
  expect(warnings.open).toBe(true);
  expect(host.querySelector('[aria-label="Import dates"]').textContent).toContain("Using your selected week beginning 2026-10-26");
  expect(host.querySelector(".im-review-file").textContent).toContain("2026-10-26");
  api.post.mockResolvedValueOnce({ data: { weeks_imported: 1 } });
  await act(async () => host.querySelector('[data-testid="btn-commit-import"]').click());
  expect(api.post).toHaveBeenLastCalledWith("/imports/review-fixture/commit", expect.objectContaining({
    week_starts: ["2026-10-26"],
  }));
});

test("a dated workbook prominently explains that its own dates were kept", async () => {
  await openReview({ ...review, date_selection: {
    requested: "2026-12-07", selected_weeks: [], file_weeks: ["2026-10-19", "2026-10-26"],
  } });
  const notice = host.querySelector('[aria-label="Import dates"]');
  expect(notice).not.toBeNull();
  expect(notice.textContent).toContain("Your selected date was not used");
  expect(notice.textContent).toContain("2026-12-07");
  expect(notice.textContent).toContain("The file already contains dates");
  expect(host.querySelector(".im-review-content").children[2]).toBe(notice);
  expect(host.querySelector('[aria-label="Import week beginning 2026-10-26"]')).not.toBeNull();
});

test("a mixed workbook explains which weeks used the selected date without claiming to replace file dates", async () => {
  await openReview({ ...review, date_selection: {
    requested: "2026-10-26", selected_weeks: ["2026-10-26"], file_weeks: ["2026-10-19"],
  } });
  const notice = host.querySelector('[aria-label="Import dates"]');
  expect(notice.textContent).toContain("Selected date used for undated weeks");
  expect(notice.textContent).toContain("2026-10-26");
  expect(notice.textContent).toContain("Existing file dates were kept");
});

test("employee choices show job roles rather than roster groups, and missing file roles stay empty", async () => {
  await openReview({ ...review, people: [
    { name: "Alex", role: "", role_in_file: null, shifts: 71 },
    { name: "New Person", role: "", role_in_file: null, shifts: 1 },
  ] });
  const map = host.querySelector('[data-testid="map-Alex"]');
  expect(map.options[2].textContent).toBe("Alex — Cashier");
  expect(host.querySelectorAll(".im-review-person-meta")[1].textContent).toBe("No role in file");
  expect(host.querySelector("#import-role-1").value).toBe("");
  expect(host.querySelector("#import-role-1").selectedOptions[0].textContent).toBe("No role");
  expect(host.querySelector("#import-role-0").value).toBe("");
});

test("joining another roster group submits its reviewed role without changing the other group's role", async () => {
  const existingGet = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === "/employees" ? Promise.resolve({ data: [{
    employee_id: "floor-alex", name: "Alex", role: "Customer Service Manager",
    departments: ["Shop Floor"], department_roles: { "Shop Floor": "Customer Service Manager" },
  }] }) : existingGet(path));
  const preview = { ...review, department: "Deli", role_options: ["Deli Assistant"], people: [
    { name: "Alex", role: "Counter", role_in_file: "Counter", shifts: 71 },
  ] };
  api.post.mockResolvedValueOnce({ data: preview });
  await act(async () => root.render(<ImportRosters />));
  await upload(preview.filename);
  const map = host.querySelector('[data-testid="map-Alex"]');
  expect(map.options[2].textContent).toBe("Alex — Customer Service Manager");
  await act(async () => {
    map.value = "floor-alex";
    map.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const role = host.querySelector("#import-role-0");
  expect(role).not.toBeNull();
  await act(async () => {
    role.value = "Deli Assistant";
    role.dispatchEvent(new Event("change", { bubbles: true }));
  });
  api.post.mockRejectedValueOnce(new Error("fixture stops here"));
  await act(async () => host.querySelector('[data-testid="btn-commit-import"]').click());
  expect(api.post).toHaveBeenLastCalledWith("/imports/review-fixture/commit", expect.objectContaining({
    employee_map: { Alex: "floor-alex" }, role_map: { Alex: "Deli Assistant" },
  }));
});

test("an unfamiliar file role asks for a configured role and submits that choice", async () => {
  await openReview({ ...review, people: [
    { name: "New Person", role: "Cust service", role_in_file: "Cust service", shifts: 71 },
  ] });
  const button = host.querySelector('[data-testid="btn-commit-import"]');
  expect(button.disabled).toBe(true);
  expect(host.textContent).toContain("Role in file: Cust service");
  expect(host.textContent).toContain("The file’s role does not match Shop Settings");
  const select = host.querySelector("#import-role-0");
  expect([...select.options].map(o => o.textContent)).toEqual([
    "Choose a role from Shop Settings", "No role", "Shop Floor", "Customer Service Manager",
  ]);
  await act(async () => {
    select.value = "Customer Service Manager";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(button.disabled).toBe(false);
  api.post.mockRejectedValueOnce(new Error("fixture stops here"));
  await act(async () => button.click());
  expect(api.post).toHaveBeenLastCalledWith("/imports/review-fixture/commit", expect.objectContaining({
    role_map: { "New Person": "Customer Service Manager" },
  }));
});

test("mapping an unfamiliar title to existing staff keeps their saved role without rewriting it", async () => {
  await openReview({ ...review, people: [
    { name: "Alex", role: "Cust service", role_in_file: "Cust service", shifts: 71 },
  ] });
  const select = host.querySelector('[data-testid="map-Alex"]');
  await act(async () => {
    select.value = "existing-alex";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.querySelector("#import-role-0")).toBeNull();
  expect(host.querySelector(".im-review-kept-role").textContent).toBe("Keeping existing role: Cashier");
  const button = host.querySelector('[data-testid="btn-commit-import"]');
  expect(button.disabled).toBe(false);
  api.post.mockRejectedValueOnce(new Error("fixture stops here"));
  await act(async () => button.click());
  expect(api.post).toHaveBeenLastCalledWith("/imports/review-fixture/commit", expect.objectContaining({ role_map: {} }));
});
