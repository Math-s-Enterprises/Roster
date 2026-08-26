/**
 * The roster as a sheet to pin on the wall.
 *
 * WHY THIS IS SEPARATE FROM THE GRID
 *
 * The interactive grid is built for editing: every cell is a button, carries a
 * pin icon, a role accent, a warning triangle, hover states. Printing it meant
 * overriding two dozen screen styles and still getting something that looked
 * like a screenshot of an app.
 *
 * A rota on a staffroom wall is a different document. It answers one question
 * — who is in, and when — for somebody standing three feet away. So this is
 * its own layout: shop name, the week, names down the left grouped by role,
 * days across, times in the cells. Nothing else.
 *
 * FITTING ONE PAGE
 *
 * A shop with 25 staff does not want ten sheets of paper. The row height is
 * computed from how many rows there are and how many pages were asked for, so
 * "one page" genuinely means one page rather than hoping it fits. Below about
 * 3.2mm a row stops being readable at arm's length, so it clamps there and
 * runs over rather than printing something nobody can use.
 */
import React from "react";
import { DAYS, DAY_SHORT, dateForDay, fmtDayDate, shiftPaidHours } from "@/lib/api";

// A4 landscape, 10mm margins, minus the header block. What is left for rows.
const USABLE_MM_PER_PAGE = 152;
const MAX_ROW_MM = 9;
const MIN_ROW_MM = 3.2;   // below this it cannot be read from across a room

export default function RosterPrintSheet({ roster, employees, shop, pages = 1 }) {
  if (!roster) return null;

  // Only people who are actually on this week. Somebody inactive, or simply
  // not rostered, is a blank row taking up height that the rows which matter
  // need in order to stay readable.
  const onRoster = new Set(
    (roster.shifts || []).map((s) => s.employee_id),
  );
  const listed = employees.filter((e) => onRoster.has(e.employee_id));

  // Grouped by role into a map, NOT by walking the list and starting a new
  // group whenever the role changes. The employee list is not guaranteed to
  // arrive sorted by role, and consecutive-grouping turns "Manager,
  // Assistant, Manager" into three headings — the same role printed twice,
  // which reads as a mistake on a wall.
  //
  // Group order follows first appearance, so the sheet matches whatever
  // order the rest of the app is using rather than inventing its own.
  const byRole = new Map();
  listed.forEach((employee) => {
    const role = employee.role || "Team";
    if (!byRole.has(role)) byRole.set(role, []);
    byRole.get(role).push(employee);
  });
  const groups = [...byRole.entries()].map(([role, people]) => ({ role, people }));

  const byPerson = {};
  (roster.shifts || []).forEach((shift) => {
    (byPerson[shift.employee_id] = byPerson[shift.employee_id] || {})[shift.day] = shift;
  });

  // One row per person, one per role heading, one for the day header.
  const rows = listed.length + groups.length + 1;
  const rowMm = Math.min(
    MAX_ROW_MM,
    Math.max(MIN_ROW_MM, (USABLE_MM_PER_PAGE * Math.max(1, pages)) / rows),
  );
  // Type scales with the row, within limits that stay legible in both
  // directions — tiny is unreadable, huge looks like a mistake.
  const fontPt = Math.min(9.5, Math.max(5.2, rowMm * 1.35));

  const cell = (shift) => {
    if (!shift) return "";
    if (shift.paid_holiday) return "Holiday";
    if (shift.unpaid_holiday) return "Unpaid";
    if (shift.sick) return "Sick";
    return `${shift.start}–${shift.end}`;
  };

  return (
    <div id="print-sheet" style={{ fontSize: `${fontPt}pt` }}>
      <div className="print-sheet-head">
        <div className="print-shop">{shop?.name || "Roster"}</div>
        <div className="print-week">
          {fmtDayDate(dateForDay(roster.week_start, "mon"))}
          {" – "}
          {fmtDayDate(dateForDay(roster.week_start, "sun"))}
          {roster.department ? ` · ${roster.department}` : ""}
        </div>
      </div>

      <table className="print-table" style={{ fontSize: `${fontPt}pt` }}>
        <thead>
          <tr style={{ height: `${rowMm}mm` }}>
            <th className="print-name-col">Name</th>
            {DAYS.map((day) => (
              <th key={day}>
                {DAY_SHORT[day]}
                <span className="print-date">
                  {fmtDayDate(dateForDay(roster.week_start, day))}
                </span>
              </th>
            ))}
            <th className="print-hours-col">Hrs</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <React.Fragment key={group.role}>
              <tr className="print-role-row" style={{ height: `${rowMm}mm` }}>
                <td colSpan={9}>{group.role}</td>
              </tr>
              {group.people.map((employee) => {
                const mine = byPerson[employee.employee_id] || {};
                const hours = Object.values(mine)
                  .reduce((total, s) => total + shiftPaidHours(s), 0);
                return (
                  <tr key={employee.employee_id} style={{ height: `${rowMm}mm` }}>
                    <td className="print-name-col">{employee.name}</td>
                    {DAYS.map((day) => (
                      <td key={day} className={mine[day] ? "print-on" : "print-off"}>
                        {cell(mine[day])}
                      </td>
                    ))}
                    <td className="print-hours-col">
                      {hours > 0 ? hours.toFixed(1) : ""}
                    </td>
                  </tr>
                );
              })}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
