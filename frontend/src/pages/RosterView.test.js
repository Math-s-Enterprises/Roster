import { availabilityConflict } from "../lib/api";

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
