import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { availabilityConflict, leaveConflict, shiftPaidHours } from "../lib/api";
import ShiftWarningModal from "../components/ShiftWarningModal";

test("an unavailable roster day is named before a manual shift is saved", () => {
  expect(availabilityConflict(
    {
      name: "Anish",
      availability: { available_days: ["tue", "wed"] },
    },
    "mon",
    "09:00",
    "17:00",
  )).toBe("Anish is not available on Monday.");
});

test("a live leave booking is named before a manual shift is saved", () => {
  expect(leaveConflict(
    [{
      employee_id: "emp_1",
      scope: "unavailable",
      date: "2026-08-12",
      end_date: "2026-08-14",
    }],
    { employee_id: "emp_1", name: "Anish" },
    "2026-08-10",
    "wed",
  )).toBe("Anish is on unpaid leave on Wednesday.");
});

test("displayed hours follow the shop break setting, not a stored old total", () => {
  const shift = { start: "09:00", end: "17:00", paid_hours: 7.25 };
  expect(shiftPaidHours(shift, false)).toBe(7.25);
  expect(shiftPaidHours(shift, true)).toBe(8);
});

test("leave warnings use the roster's own confirmation modal", () => {
  const html = renderToStaticMarkup(
    <ShiftWarningModal
      warnings={["Jithin is on unpaid leave on Wednesday."]}
      confirmLabel="Save shift anyway"
      onClose={() => {}}
      onConfirm={() => {}}
    />,
  );
  expect(html).toContain("Confirm this shift?");
  expect(html).toContain("Jithin is on unpaid leave on Wednesday.");
  expect(html).toContain("Save shift anyway");
});
