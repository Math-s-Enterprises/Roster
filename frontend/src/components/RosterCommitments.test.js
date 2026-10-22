import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { externalShiftsByCell } from "../lib/api";
import RosterPrintSheet from "./RosterPrintSheet";

const night = { employee_id: "shared", day: "sun", start: "22:00", end: "06:00",
  department: "Deli", week_offset: -7, date: "2099-01-04" };

test("last Sunday's night appears on Monday, not this Sunday's cell", () => {
  const cells = externalShiftsByCell([night]);
  expect(cells["shared|mon"]).toMatchObject({
    department: "Deli", start: "00:00", end: "06:00", continuation: true,
  });
  expect(cells["shared|sun"]).toBeUndefined();
});

test("a current-week night shows its continuation and a midnight finish does not", () => {
  const cells = externalShiftsByCell([{ ...night, day: "mon", week_offset: 0 }]);
  expect(cells["shared|mon"]).toMatchObject({ start: "22:00", end: "06:00", continuation: false });
  expect(cells["shared|tue"]).toMatchObject({ start: "00:00", end: "06:00", continuation: true });
  expect(externalShiftsByCell([{ ...night, end: "00:00" }])).toEqual({});
});

test("a next-week commitment is not shown on this week's Monday", () => {
  expect(externalShiftsByCell([{ ...night, day: "mon", week_offset: 7 }])).toEqual({});
});

test("boundary context does not create an empty print row for next week's staff", () => {
  const html = renderToStaticMarkup(<RosterPrintSheet
    roster={{ week_start: "2099-01-05", shifts: [], external_shifts: [{ ...night, week_offset: 7 }] }}
    employees={[{ employee_id: "shared", name: "Shared Person", role: "Cashier" }]}
    shop={{ name: "Fictional Shop" }}
  />);
  expect(html).not.toContain("Shared Person");
});

test("the print sheet puts last Sunday's Deli continuation in Monday", () => {
  const wrapper = document.createElement("div");
  wrapper.innerHTML = renderToStaticMarkup(<RosterPrintSheet
    roster={{ week_start: "2099-01-05", shifts: [], external_shifts: [night] }}
    employees={[{ employee_id: "shared", name: "Shared Person", role: "Cashier" }]}
    shop={{ name: "Fictional Shop" }}
  />);
  const row = [...wrapper.querySelectorAll("tbody tr")].find((tr) => tr.textContent.includes("Shared Person"));
  expect(row.children[1].textContent).toContain("Deli · 00:00–06:00");
  expect(row.children[7].textContent).toBe("");
  expect(row.children[8].textContent).toBe("");
});
