import { availabilityConflict, leaveConflict } from "../lib/api";

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
