/**
 * Holidays & off-days — redesigned to the 1a / 2a handoff.
 *
 * WHAT WAS WRONG WITH THE OLD PAGE
 * --------------------------------
 * Every leave entry rendered as an identical row — "2026-09-02 · N/A ·
 * Holiday (unpaid) · Elliot" — so the two questions a manager actually opens
 * this page with went unanswered: who is off right now, and does the shop
 * have cover. Four consecutive single days for one person read as four
 * unrelated bookings.
 *
 * So: a "right now" band that answers today at a glance, and a table where
 * consecutive days collapse into one run. Every entry states WHEN THE PERSON
 * IS BACK, which is the piece the old list never carried.
 *
 * The `N/A` badge is gone. It was our `scope: "unavailable"` — unpaid leave —
 * rendered as an abbreviation that told the manager nothing. Where a field
 * has no value now, it is omitted rather than labelled.
 *
 * NOTES ON THE DATA, which is unchanged
 * -------------------------------------
 * `scope` carries what the handoff calls `type`:
 *
 *     shop         Shop closed        accent tag, row tinted
 *     employee     Holiday · paid     draws down entitlement
 *     unavailable  Holiday · unpaid   the old N/A
 *     sick         Sick               neutral tag
 *
 * The mock only ever shows "Holiday · unpaid" because its sample data has
 * nothing else. Ours distinguishes paid from unpaid and that distinction is
 * load-bearing — there is a whole balance and paid-days flow behind it — so
 * both are shown.
 *
 * TODAY is taken from the browser. The handoff asks for the server's date,
 * and there is no endpoint for it; the risk is a manager whose machine is
 * set to another day. Worth adding when there is somewhere to put it.
 */
import React, { useEffect, useMemo, useState } from "react";
import { api, errorMessage, DAYS, DAY_SHORT, mondayOf } from "@/lib/api";
import { toast } from "sonner";
import { CalendarPlus, Download, Plus, X } from "lucide-react";

/* -------------------------------------------------------------------------
   Dates. Local, never UTC: `toISOString()` shifts across midnight depending
   on the timezone, and leave is date-only.
------------------------------------------------------------------------- */
const isoOf = (d) =>
  `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, "0")}-${`${d.getDate()}`.padStart(2, "0")}`;
const parseIso = (iso) => new Date(`${iso}T00:00:00`);
const addDays = (iso, n) => {
  const d = parseIso(iso);
  d.setDate(d.getDate() + n);
  return isoOf(d);
};
const todayIso = () => isoOf(new Date());

/** "Wed 2 Sep" */
const fmtDay = (iso) =>
  parseIso(iso).toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short",
  });

/** "Wed 2 Sep" for one day, "Thu 17 – Sun 20 Sep" for a run. */
function fmtRange(start, end) {
  if (start === end) return fmtDay(start);
  const a = parseIso(start);
  const b = parseIso(end);
  const sameMonth =
    a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear();
  // The month is stated once when both ends share it — "Thu 17 – Sun 20 Sep"
  // rather than "Thu 17 Sep – Sun 20 Sep", which reads as two dates.
  const left = sameMonth
    ? a.toLocaleDateString("en-GB", { weekday: "short", day: "numeric" })
    : fmtDay(start);
  return `${left} – ${fmtDay(end)}`;
}

const monthName = (iso) =>
  parseIso(iso).toLocaleDateString("en-GB", { month: "long" });

/* -------------------------------------------------------------------------
   Leave types
------------------------------------------------------------------------- */
const TYPES = {
  shop: { label: "Shop closed", tone: "accent", who: "Whole shop closed" },
  employee: { label: "Holiday · paid", tone: "outline" },
  unavailable: { label: "Holiday · unpaid", tone: "outline" },
  sick: { label: "Sick", tone: "neutral" },
};
const typeOf = (entry) => TYPES[entry.scope] || TYPES.unavailable;

/** Every calendar date an entry covers, inclusive. */
function datesOf(entry) {
  const out = [];
  const last = entry.end_date && entry.end_date >= entry.date
    ? entry.end_date : entry.date;
  // Bounded so one malformed record cannot spin the page. A booking longer
  // than a year is a typo'd year, which the API also guards against.
  for (let d = entry.date, guard = 0; d <= last && guard < 400; d = addDays(d, 1), guard++) {
    out.push(d);
  }
  return out;
}

/**
 * Collapse entries into runs — the heart of the redesign.
 *
 * Two collapses, in this order, and the order matters:
 *
 *   1. ADJACENT DAYS for the same person and type become one run. Four
 *      single-day records for Jithin become "Thu 17 – Sun 20 Sep · 4".
 *   2. RUNS THAT SHARE A SHAPE merge their people. Four people each off on
 *      the 2nd become "Wed 2 Sep · 1 · Elliot, Tiago, Jamie, Aaron".
 *
 * Doing 2 before 1 would glue different people's unrelated dates together.
 *
 * `days` counts CALENDAR days, not working days. A run across a weekend the
 * shop is closed still reads as its full length — which is what a manager
 * means by "four days off", but is worth knowing before this number is used
 * for anything that costs money.
 */
export function buildRuns(entries, nameOf) {
  // 1 — adjacent days per (person, type)
  const byPerson = new Map();
  for (const entry of entries) {
    const key = `${entry.employee_id || "shop"}|${entry.scope}`;
    if (!byPerson.has(key)) byPerson.set(key, []);
    for (const date of datesOf(entry)) {
      byPerson.get(key).push({ date, entry });
    }
  }

  const runs = [];
  for (const [key, atoms] of byPerson) {
    atoms.sort((a, b) => a.date.localeCompare(b.date));
    let current = null;
    for (const atom of atoms) {
      if (current && addDays(current.end, 1) === atom.date) {
        current.end = atom.date;
        current.days += 1;
        current.entries.add(atom.entry);
      } else if (current && current.end === atom.date) {
        current.entries.add(atom.entry);      // overlapping records, same day
      } else {
        if (current) runs.push(current);
        const [employeeId, scope] = key.split("|");
        current = {
          start: atom.date, end: atom.date, days: 1, scope,
          employeeId: employeeId === "shop" ? null : employeeId,
          entries: new Set([atom.entry]),
        };
      }
    }
    if (current) runs.push(current);
  }

  // 2 — runs of the same shape share a row
  const byShape = new Map();
  for (const run of runs) {
    const key = `${run.start}|${run.end}|${run.scope}`;
    if (!byShape.has(key)) {
      byShape.set(key, {
        id: key, start: run.start, end: run.end, days: run.days,
        scope: run.scope, employeeIds: [], entries: new Set(),
      });
    }
    const row = byShape.get(key);
    if (run.employeeId) row.employeeIds.push(run.employeeId);
    for (const entry of run.entries) row.entries.add(entry);
  }

  return [...byShape.values()]
    .map((row) => ({
      ...row,
      entries: [...row.entries],
      people: row.employeeIds.map(nameOf).filter(Boolean),
    }))
    .sort((a, b) => a.start.localeCompare(b.start) || a.scope.localeCompare(b.scope));
}

/** Which section of the upcoming table a run belongs in. */
function upcomingGroup(start, today) {
  const thisWeek = mondayOf(today);
  const nextWeek = addDays(thisWeek, 7);
  const weekAfter = addDays(thisWeek, 14);
  if (start < nextWeek) return "This week";
  if (start < weekAfter) return "Next week";
  const sameMonth = start.slice(0, 7) === today.slice(0, 7);
  return sameMonth ? `Later in ${monthName(start)}` : monthName(start);
}

/** Which section of the past table — newest month first. */
function pastGroup(start, today) {
  const sameMonth = start.slice(0, 7) === today.slice(0, 7);
  return sameMonth ? `This month — ${monthName(start)}` : monthName(start);
}

function groupRuns(runs, labelFor) {
  const out = [];
  for (const run of runs) {
    const label = labelFor(run.start);
    if (!out.length || out[out.length - 1].label !== label) {
      out.push({ label, runs: [] });
    }
    out[out.length - 1].runs.push(run);
  }
  return out;
}

/* ========================================================================= */

export default function CalendarPage() {
  const [hols, setHols] = useState([]);
  const [emps, setEmps] = useState([]);
  const [shop, setShop] = useState(null);
  const [view, setView] = useState("upcoming30");
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [expanded, setExpanded] = useState([]);

  const today = useMemo(todayIso, []);

  const load = async () => {
    const [h, e, s] = await Promise.all([
      api.get("/holidays"), api.get("/employees"), api.get("/shop"),
    ]);
    setHols(h.data);
    setEmps(e.data);
    setShop(s.data);
  };
  useEffect(() => { load(); }, []);

  const nameOf = useMemo(() => {
    const byId = new Map(emps.map((e) => [e.employee_id, e.name]));
    return (id) => byId.get(id) || null;
  }, [emps]);

  const activeStaff = useMemo(
    () => emps.filter((e) => e.is_active !== false), [emps],
  );

  /* ---- who is off today, and when are they back ------------------------ */
  const offToday = useMemo(() => {
    const runs = buildRuns(
      hols.filter((h) => h.scope !== "shop" && h.employee_id), nameOf,
    );
    return runs
      .filter((run) => run.start <= today && run.end >= today)
      .flatMap((run) =>
        run.employeeIds.map((id) => ({
          employeeId: id,
          name: nameOf(id) || "Unknown",
          backOn: addDays(run.end, 1),
          type: TYPES[run.scope] || TYPES.unavailable,
        })),
      );
  }, [hols, nameOf, today]);

  const offTodayIds = useMemo(
    () => new Set(offToday.map((p) => p.employeeId)), [offToday],
  );
  const workingToday = useMemo(
    () => activeStaff.filter((e) => !offTodayIds.has(e.employee_id)),
    [activeStaff, offTodayIds],
  );

  const shopClosedToday = useMemo(
    () => hols.some(
      (h) => h.scope === "shop" && h.date <= today
        && (h.end_date || h.date) >= today,
    ),
    [hols, today],
  );

  /* ---- runs, split into the three views -------------------------------- */
  const allRuns = useMemo(() => buildRuns(hols, nameOf), [hols, nameOf]);

  const upcomingRuns = useMemo(
    () => allRuns.filter((r) => r.end >= today), [allRuns, today],
  );
  const within30 = useMemo(() => {
    const horizon = addDays(today, 30);
    return upcomingRuns.filter((r) => r.start <= horizon);
  }, [upcomingRuns, today]);
  const pastRuns = useMemo(
    () => allRuns.filter((r) => r.end < today).sort(
      (a, b) => b.start.localeCompare(a.start),
    ),
    [allRuns, today],
  );

  /* ---- the next day somebody is off, after today ----------------------- */
  const nextGap = useMemo(() => {
    const future = upcomingRuns
      .filter((r) => r.start > today && r.scope !== "shop")
      .sort((a, b) => a.start.localeCompare(b.start));
    return future[0] || null;
  }, [upcomingRuns, today]);

  const everyoneBack = useMemo(() => {
    if (!offToday.length) return null;
    return offToday.reduce(
      (latest, p) => (p.backOn > latest ? p.backOn : latest), offToday[0].backOn,
    );
  }, [offToday]);

  const rows = view === "past" ? pastRuns
    : view === "allUpcoming" ? upcomingRuns : within30;
  const groups = useMemo(
    () => groupRuns(rows, (start) =>
      view === "past" ? pastGroup(start, today) : upcomingGroup(start, today)),
    [rows, view, today],
  );

  /* ---- past-view statistics -------------------------------------------- */
  const year = today.slice(0, 4);
  const stats = useMemo(() => {
    let holidayDays = 0, sickDays = 0, closures = 0;
    const perDay = new Map();
    for (const entry of hols) {
      const dates = datesOf(entry).filter((d) => d.startsWith(year) && d < today);
      if (!dates.length) continue;
      if (entry.scope === "shop") closures += 1;
      else if (entry.scope === "sick") sickDays += dates.length;
      else holidayDays += dates.length;
      if (entry.scope !== "shop") {
        for (const d of dates) perDay.set(d, (perDay.get(d) || 0) + 1);
      }
    }
    let thinnest = null;
    for (const [date, count] of perDay) {
      if (!thinnest || count > thinnest.count) thinnest = { date, count };
    }
    return { holidayDays, sickDays, closures, thinnest };
  }, [hols, year, today]);

  /* ---- days taken per person, this year -------------------------------- */
  const perPerson = useMemo(() => {
    const tally = new Map(
      activeStaff.map((e) => [e.employee_id, { name: e.name, days: 0, sick: 0 }]),
    );
    for (const entry of hols) {
      if (entry.scope === "shop" || !entry.employee_id) continue;
      const row = tally.get(entry.employee_id);
      if (!row) continue;
      const days = datesOf(entry).filter(
        (d) => d.startsWith(year) && d < today,
      ).length;
      row.days += days;
      if (entry.scope === "sick") row.sick += days;
    }
    const list = [...tally.values()].sort((a, b) => b.days - a.days);
    const max = list.length ? Math.max(...list.map((r) => r.days), 1) : 1;
    return { list, max };
  }, [hols, activeStaff, year, today]);

  /* ---- actions ---------------------------------------------------------- */
  const exportCsv = () => {
    const header = ["Start", "End", "Days", "Who", "Type", "Label"];
    const lines = allRuns.map((run) => [
      run.start, run.end, run.days,
      run.scope === "shop" ? "Whole shop" : run.people.join(" / ") || "—",
      typeOf({ scope: run.scope }).label,
      run.entries[0]?.label || "",
    ]);
    const csv = [header, ...lines]
      .map((cells) => cells.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `leave-${today}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const openHours = useMemo(() => {
    if (!shop?.hours) return null;
    const weekday = DAYS[(parseIso(today).getDay() + 6) % 7];
    const row = shop.hours.find((h) => h.day === weekday);
    if (!row || row.closed) return null;
    return `${row.open}–${row.close}`;
  }, [shop, today]);

  const toggleRun = (id) =>
    setExpanded((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);

  const collapsedRuns = rows.filter((r) => r.entries.length > 1 && r.days > 1);

  return (
    <div className="hol-page -m-6 lg:-m-10">
      {/* 1 — page header ------------------------------------------------- */}
      <div className="hol-band flex items-end justify-between gap-6 flex-wrap"
           style={{ padding: "28px 32px 20px" }}>
        <div>
          <div className="hol-kicker">Calendar</div>
          <h1 className="hol-h1" style={{ margin: "2px 0 0" }}>Holidays &amp; off-days</h1>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-secondary" onClick={exportCsv} data-testid="hol-export">
            <Download size={14} /> Export
          </button>
          <button className="btn btn-primary" onClick={() => setAddOpen(true)}
                  data-testid="btn-add-leave">
            <Plus size={14} /> Add leave
          </button>
        </div>
      </div>

      {/* 2 — right now ---------------------------------------------------- */}
      <div className="hol-band hol-rightnow grid" style={{ gridTemplateColumns: "1fr 320px" }}>
        <div style={{ padding: "26px 32px 28px" }}>
          <div className="hol-overline">Right now — {fmtDay(today)} {year}</div>

          {offToday.length === 0 ? (
            /* Empty state, per the handoff: the numeral band is replaced
               rather than showing a zero, which reads as an error. */
            <div style={{ margin: "10px 0 0" }}>
              <div style={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>
                Nobody is off today — all {activeStaff.length} staff on shift
              </div>
              <div className="hol-muted" style={{ fontSize: 13, marginTop: 4 }}>
                {shopClosedToday ? "The shop is closed today."
                  : openHours ? `Shop open ${openHours}` : "Shop hours not set"}
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-end gap-4" style={{ margin: "4px 0 22px" }}>
                <div className="hol-numeral">{offToday.length}</div>
                <div style={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1, paddingBottom: 6 }}>
                  of {activeStaff.length} staff are off today
                  <div className="hol-muted" style={{ fontSize: 13, fontWeight: 400, lineHeight: 1.4 }}>
                    {workingToday.length} working
                    {shopClosedToday ? " · shop closed today"
                      : openHours ? ` · shop open ${openHours}` : ""}
                  </div>
                </div>
              </div>

              {/* 4-up, wrapping past 4. Every cell says when they are back —
                  the piece the old list never carried. */}
              <div className="hol-people grid" style={{
                gridTemplateColumns: "repeat(4, 1fr)",
                borderTop: "2px solid var(--hairline)",
                borderLeft: "1px solid var(--hairline)",
              }}>
                {offToday.map((person) => (
                  <div key={person.employeeId} style={{
                    borderRight: "1px solid var(--hairline)",
                    borderBottom: "1px solid var(--hairline)",
                    padding: "14px 14px 16px",
                  }}>
                    <div style={{ fontSize: 17, fontWeight: 800 }}>{person.name}</div>
                    <div className="hol-muted" style={{ fontSize: 12, margin: "2px 0 10px" }}>
                      {person.backOn === addDays(today, 1)
                        ? `Back tomorrow, ${fmtDay(person.backOn)}`
                        : `Back ${fmtDay(person.backOn)}`}
                    </div>
                    <span className={`hol-tag hol-tag-${person.type.tone}`}>
                      {person.type.label}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="hol-surface" style={{
          borderLeft: "2px solid var(--hairline)", padding: "26px 24px",
        }}>
          <div className="hol-overline" style={{ marginBottom: 12 }}>Working today</div>
          <div style={{ borderTop: "1px solid var(--hairline)" }}>
            {workingToday.length === 0 && (
              <div className="hol-muted" style={{ padding: "9px 0", fontSize: 14 }}>
                Nobody is scheduled.
              </div>
            )}
            {workingToday.map((e) => (
              <div key={e.employee_id} style={{
                padding: "9px 0", borderBottom: "1px solid var(--hairline)", fontSize: 14,
              }}>
                {e.name}
              </div>
            ))}
          </div>

          <div style={{
            marginTop: 18, padding: 12, border: "2px solid var(--primary)",
            fontSize: 12, lineHeight: 1.5,
          }}>
            {everyoneBack && (
              <>{fmtDay(everyoneBack)} everyone is back. </>
            )}
            {nextGap ? (
              <>Next gap: <strong>{fmtDay(nextGap.start)}</strong>, when{" "}
                {nextGap.scope === "shop" ? "the shop closes"
                  : `${nextGap.people.join(", ")} start${nextGap.people.length === 1 ? "s" : ""} ${nextGap.days} day${nextGap.days === 1 ? "" : "s"} off`}.
              </>
            ) : (
              <>No further leave is booked.</>
            )}
          </div>
        </div>
      </div>

      {/* 3 — booked leave / history --------------------------------------- */}
      <div style={{ padding: "24px 32px 32px" }}>
        <div className="flex items-baseline justify-between gap-5 flex-wrap"
             style={{ marginBottom: 14 }}>
          <h2 className="hol-h2">
            {view === "past" ? "Leave already taken" : "Booked leave"}
          </h2>
          <div className="flex gap-1" role="group" aria-label="Which leave to show">
            {[
              ["upcoming30", "Next 30 days"],
              ["allUpcoming", `All upcoming (${upcomingRuns.length})`],
              ["past", "Past"],
            ].map(([key, label]) => (
              <button
                key={key}
                data-testid={`hol-view-${key}`}
                aria-pressed={view === key}
                onClick={() => setView(key)}
                className={view === key ? "btn btn-primary" : "btn btn-secondary"}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {view === "past" && (
          <StatStrip stats={stats} year={year} />
        )}

        <LeaveTable
          groups={groups}
          expanded={expanded}
          onToggleRun={toggleRun}
          onEdit={setEditing}
          nameOf={nameOf}
          emptyMessage={
            view === "past" ? "No leave has been taken yet."
              : view === "allUpcoming" ? "No leave is booked."
                : "No leave booked in the next 30 days."
          }
        />

        {collapsedRuns.length > 0 && (
          <div className="hol-faint" style={{ marginTop: 12, fontSize: 12 }}>
            {collapsedRuns.length === 1
              ? `${collapsedRuns[0].entries.length} consecutive single-day entries for ${collapsedRuns[0].people.join(", ") || "the shop"} (${fmtRange(collapsedRuns[0].start, collapsedRuns[0].end)}) are shown as one run.`
              : `${collapsedRuns.length} runs of consecutive single-day entries are shown as one row each.`}{" "}
            <button
              className="btn btn-ghost"
              style={{ fontSize: 12, padding: "2px 6px" }}
              onClick={() => setExpanded(
                expanded.length ? [] : collapsedRuns.map((r) => r.id),
              )}
            >
              {expanded.length ? "Collapse runs" : "Show individual days"}
            </button>
          </div>
        )}

        {view === "past" && perPerson.list.length > 0 && (
          <div style={{ marginTop: 28 }}>
            <div className="hol-overline" style={{ marginBottom: 12 }}>
              Days taken per person, {year}
            </div>
            <div style={{ borderTop: "1px solid var(--hairline)" }}>
              {perPerson.list.map((row) => (
                <div key={row.name} className="grid items-center" style={{
                  gridTemplateColumns: "96px 1fr 90px", gap: 14,
                  padding: "8px 0", borderBottom: "1px solid var(--hairline)",
                }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{row.name}</span>
                  <span style={{
                    height: 14,
                    width: `${Math.round((row.days / perPerson.max) * 100)}%`,
                    /* Neutral rather than accent when the total is mostly
                       sick days — those are not holiday and should not read
                       as somebody taking more leave than their colleagues. */
                    background: row.sick > row.days / 2
                      ? "var(--ink-mute)" : "var(--primary)",
                  }} />
                  <span className="hol-muted" style={{ fontSize: 12 }}>
                    {row.days === 0 ? "none yet"
                      : `${row.days} day${row.days === 1 ? "" : "s"}${row.sick ? ` · ${row.sick} sick` : ""}`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {addOpen && (
        <LeaveModal
          employees={emps}
          onClose={() => setAddOpen(false)}
          onSaved={() => { setAddOpen(false); load(); }}
        />
      )}
      {editing && (
        <LeaveModal
          employees={emps}
          entry={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Stat strip (past view)
------------------------------------------------------------------------- */
function StatStrip({ stats, year }) {
  const cells = [
    [stats.holidayDays, `holiday days taken in ${year}`, false],
    [stats.sickDays, "sick days recorded", false],
    [stats.closures, "shop closures", false],
    // The handoff's fourth cell is "thinnest day — 4 staff on shift", which
    // needs roster data rather than leave data. Replaced with the equivalent
    // this page can answer honestly: the day most people were off.
    stats.thinnest
      ? [fmtDay(stats.thinnest.date),
         `most people off — ${stats.thinnest.count} on leave`, true]
      : ["—", "no leave taken yet", true],
  ];
  return (
    <div className="hol-surface hol-stats grid" style={{
      gridTemplateColumns: "repeat(4, 1fr)",
      borderTop: "2px solid var(--hairline)",
      borderBottom: "2px solid var(--hairline)",
      marginBottom: 22,
    }}>
      {cells.map(([value, label, accent], i) => (
        <div key={label} style={{
          padding: "16px 20px",
          borderRight: i < 3 ? "1px solid var(--hairline)" : "none",
        }}>
          <div style={{
            fontSize: 30, lineHeight: 1, fontWeight: 800,
            color: accent ? "var(--primary)" : "var(--ink)",
          }}>
            {value}
          </div>
          <div className="hol-muted" style={{ fontSize: 12, marginTop: 4 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------
   The table
------------------------------------------------------------------------- */
function LeaveTable({ groups, expanded, onToggleRun, onEdit, nameOf, emptyMessage }) {
  if (!groups.length) {
    return (
      <div className="hol-muted" style={{
        padding: "28px 0", fontSize: 14, borderTop: "2px solid var(--hairline)",
      }}>
        {emptyMessage}
      </div>
    );
  }
  return (
    <table className="hol-table">
      <thead>
        <tr>
          <th style={{ width: 190 }}>Dates</th>
          <th style={{ width: 80 }} className="hol-days-col">Days</th>
          <th>Who</th>
          <th style={{ width: 170 }}>Type</th>
          <th style={{ width: 60 }}><span className="sr-only">Edit</span></th>
        </tr>
      </thead>
      <tbody>
        {groups.map((group) => (
          <React.Fragment key={group.label}>
            <tr className="hol-group"><td colSpan={5}>{group.label}</td></tr>
            {group.runs.map((run) => {
              const type = typeOf({ scope: run.scope });
              const isOpen = expanded.includes(run.id);
              return (
                <React.Fragment key={run.id}>
                  <tr className={`hol-row${run.scope === "shop" ? " hol-shop-closed" : ""}`}>
                    <td style={{ fontWeight: 600 }}>{fmtRange(run.start, run.end)}</td>
                    <td className="hol-days-col">{run.days}</td>
                    <td style={run.scope === "shop" ? { fontWeight: 600 } : undefined}>
                      {run.scope === "shop"
                        ? "Whole shop closed"
                        : run.people.join(", ") || "—"}
                    </td>
                    <td><span className={`hol-tag hol-tag-${type.tone}`}>{type.label}</span></td>
                    <td>
                      {run.entries.length === 1 ? (
                        <button className="btn btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }}
                                onClick={() => onEdit(run.entries[0])}>
                          Edit
                        </button>
                      ) : (
                        /* A run made of several records cannot be edited as
                           one — expanding it is what makes each editable. */
                        <button className="btn btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }}
                                onClick={() => onToggleRun(run.id)}>
                          {isOpen ? "Hide" : "Days"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {isOpen && run.entries.map((entry) => (
                    <tr key={entry.holiday_id} className="hol-row">
                      <td style={{ paddingLeft: 16 }} className="hol-muted">
                        {fmtRange(entry.date, entry.end_date || entry.date)}
                      </td>
                      <td className="hol-days-col hol-muted">
                        {datesOf(entry).length}
                      </td>
                      <td className="hol-muted">
                        {entry.scope === "shop"
                          ? "Whole shop closed" : nameOf(entry.employee_id) || "—"}
                      </td>
                      <td className="hol-muted" style={{ fontSize: 12 }}>{entry.label}</td>
                      <td>
                        <button className="btn btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }}
                                onClick={() => onEdit(entry)}>
                          Edit
                        </button>
                      </td>
                    </tr>
                  ))}
                </React.Fragment>
              );
            })}
          </React.Fragment>
        ))}
      </tbody>
    </table>
  );
}

/* -------------------------------------------------------------------------
   Add / edit leave

   The booking form is unchanged — same three types, same per-day paid
   picker, same balance guard — it has simply moved behind the Add leave
   button. In EDIT mode the paid-day picker is hidden: an existing record is
   one already-decided day, and re-running the booking flow over it would
   rewrite days the manager did not open the dialog to touch.
------------------------------------------------------------------------- */
function LeaveModal({ employees, entry, onClose, onSaved }) {
  const editing = Boolean(entry);
  const [scope, setScope] = useState(entry?.scope || "shop");
  const [empId, setEmpId] = useState(entry?.employee_id || "");
  const [date, setDate] = useState(entry?.date || "");
  const [endDate, setEndDate] = useState(entry?.end_date || "");
  const [label, setLabel] = useState(entry?.label || "");
  const [busy, setBusy] = useState(false);

  // Booking a range of employee leave: the paid-day picker, add mode only.
  const [leaveFrom, setLeaveFrom] = useState("");
  const [leaveTo, setLeaveTo] = useState("");
  const [paidDates, setPaidDates] = useState([]);
  const [balance, setBalance] = useState(null);

  const scopeOpts = editing
    ? [["shop", "Shop closed"], ["employee", "Holiday · paid"],
       ["unavailable", "Holiday · unpaid"], ["sick", "Sick"]]
    : [["shop", "Shop closed"], ["leave-week", "Employee leave"], ["sick", "Sick"]];

  const leaveWeeks = useMemo(() => {
    if (!leaveFrom || !leaveTo || leaveTo < leaveFrom) return [];
    const buckets = new Map();
    for (let d = leaveFrom, guard = 0; d <= leaveTo && guard < 400; d = addDays(d, 1), guard++) {
      const week = mondayOf(d);
      if (!buckets.has(week)) buckets.set(week, []);
      buckets.get(week).push(d);
    }
    return [...buckets.entries()].map(([week, dates]) => ({ week, dates }));
  }, [leaveFrom, leaveTo]);

  const allLeaveDates = useMemo(
    () => leaveWeeks.flatMap((w) => w.dates), [leaveWeeks],
  );
  useEffect(() => {
    setPaidDates((prev) => prev.filter((d) => allLeaveDates.includes(d)));
  }, [allLeaveDates]);

  const selected = employees.find((e) => e.employee_id === empId);
  const hoursPerDay = selected?.max_weekly_hours
    ? Math.round((selected.max_weekly_hours / 5) * 100) / 100 : null;

  useEffect(() => {
    if (!empId || scope !== "leave-week") { setBalance(null); return; }
    let cancelled = false;
    const params = hoursPerDay ? `?hours_per_day=${hoursPerDay}` : "";
    api.get(`/holiday-balance/${empId}${params}`)
      .then((r) => { if (!cancelled) setBalance(r.data); })
      .catch(() => { if (!cancelled) setBalance(null); });
    return () => { cancelled = true; };
  }, [empId, scope, hoursPerDay]);

  const maxPaidDays = balance?.max_payable_days ?? null;
  const requestedHours = hoursPerDay
    ? Math.round(paidDates.length * hoursPerDay * 100) / 100 : null;
  const overBalance = balance != null && requestedHours != null
    && requestedHours > balance.available_hours + 1e-6;

  const toggleDate = (d) => setPaidDates((prev) => {
    if (prev.includes(d)) return prev.filter((x) => x !== d);
    if (maxPaidDays != null && prev.length >= maxPaidDays) {
      toast.error(
        `${selected?.name || "This employee"} has ${balance.available_hours}h left, ` +
        `which covers ${maxPaidDays} paid day${maxPaidDays === 1 ? "" : "s"}. ` +
        "The remaining days can still be booked as unpaid.",
      );
      return prev;
    }
    return [...prev, d];
  });

  const toggleAll = () => {
    if (paidDates.length === allLeaveDates.length) { setPaidDates([]); return; }
    const limit = maxPaidDays == null
      ? allLeaveDates.length : Math.min(maxPaidDays, allLeaveDates.length);
    if (limit < allLeaveDates.length) {
      toast.warning(
        `Only ${limit} of ${allLeaveDates.length} day(s) fit in the remaining ` +
        `${balance.available_hours}h. The rest are booked as unpaid.`,
      );
    }
    setPaidDates(allLeaveDates.slice(0, limit));
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (editing) {
        await api.put(`/holidays/${entry.holiday_id}`, {
          date, end_date: endDate || null, label,
          scope, employee_id: scope === "shop" ? null : empId,
        });
        toast.success("Leave updated");
      } else if (scope === "leave-week") {
        const r = await api.post("/holidays/leave", {
          employee_id: empId, start_date: leaveFrom, end_date: leaveTo,
          paid_dates: paidDates, label: label || "Holiday",
        });
        toast.success(
          `${r.data.employee}: ${r.data.paid_days} paid day(s) = ${r.data.paid_hours_total}h` +
          (r.data.unpaid_days ? `, ${r.data.unpaid_days} unpaid` : ""),
        );
      } else {
        await api.post("/holidays", {
          date, end_date: endDate || null, label, scope,
          employee_id: scope === "sick" ? empId : null,
        });
        toast.success("Added");
      }
      onSaved();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save"));
    } finally {
      setBusy(false);
    }
  };

  /* Delete lives HERE, not as a bare trash icon on every row — the old
     one-click delete sat next to eight others and was easy to hit by
     accident. */
  const remove = async () => {
    if (!window.confirm(
      `Remove this leave entry?\n\n${fmtRange(entry.date, entry.end_date || entry.date)}` +
      `\n\nThis cannot be undone.`,
    )) return;
    setBusy(true);
    try {
      await api.delete(`/holidays/${entry.holiday_id}`);
      toast.success("Removed");
      onSaved();
    } catch (err) {
      toast.error(errorMessage(err, "Could not remove"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="hol-page fixed inset-0 z-50 bg-black/60 flex items-start justify-center p-4 overflow-y-auto"
         onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="card elevated w-full max-w-lg my-8"
        style={{ padding: 24 }}
      >
        <div className="flex items-start justify-between gap-4" style={{ marginBottom: 18 }}>
          <div>
            <div className="hol-kicker">{editing ? "Edit" : "New"}</div>
            <h2 className="hol-h2" style={{ marginTop: 2 }}>
              {editing ? "Edit leave" : "Add leave"}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="hol-overline">Type</label>
            <div className="flex gap-2 mt-1.5 flex-wrap">
              {scopeOpts.map(([key, text]) => (
                <button
                  type="button"
                  key={key}
                  onClick={() => setScope(key)}
                  className={scope === key ? "btn btn-primary" : "btn btn-secondary"}
                  style={{ fontSize: 12, padding: "8px 12px" }}
                >
                  {text}
                </button>
              ))}
            </div>
            {scope === "sick" && (
              <div className="hol-muted" style={{ fontSize: 11, marginTop: 8 }}>
                Sick leave is never used as AI training data.
              </div>
            )}
          </div>

          {scope !== "shop" && (
            <div>
              <label className="hol-overline">Employee</label>
              <select required value={empId} onChange={(e) => setEmpId(e.target.value)}
                      className="mt-1.5 w-full px-3 py-2.5">
                <option value="">Select…</option>
                {employees.map((e) => (
                  <option key={e.employee_id} value={e.employee_id}>
                    {e.name} · {e.max_weekly_hours}h
                  </option>
                ))}
              </select>
            </div>
          )}

          {scope === "leave-week" && balance && (
            <div className="hol-surface" style={{ padding: 12, fontSize: 11 }}>
              <div className="flex justify-between">
                <span className="hol-muted">Holiday available</span>
                <span className="font-mono" style={{ color: "var(--primary)" }}>
                  {balance.available_hours}h
                </span>
              </div>
              <div className="flex justify-between" style={{ marginTop: 4 }}>
                <span className="hol-muted">Covers</span>
                <span className="font-mono">
                  {balance.max_payable_days} day{balance.max_payable_days === 1 ? "" : "s"}
                  <span className="hol-muted"> @ {balance.hours_per_day}h</span>
                </span>
              </div>
            </div>
          )}

          {scope === "leave-week" ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="hol-overline">From</label>
                  <input data-testid="leave-from" required type="date" value={leaveFrom}
                         onChange={(e) => {
                           setLeaveFrom(e.target.value);
                           if (!leaveTo || leaveTo < e.target.value) setLeaveTo(e.target.value);
                         }}
                         className="mt-1.5 w-full px-3 py-2.5 font-mono" />
                </div>
                <div>
                  <label className="hol-overline">To</label>
                  <input data-testid="leave-to" required type="date" min={leaveFrom} value={leaveTo}
                         onChange={(e) => setLeaveTo(e.target.value)}
                         className="mt-1.5 w-full px-3 py-2.5 font-mono" />
                </div>
              </div>

              {allLeaveDates.length > 0 && (
                <div>
                  <div className="flex items-center justify-between">
                    <label className="hol-overline">
                      Which days are paid? ({allLeaveDates.length} day
                      {allLeaveDates.length === 1 ? "" : "s"} off)
                    </label>
                    <button type="button" onClick={toggleAll} className="btn btn-ghost"
                            style={{ fontSize: 11, padding: "2px 8px" }}>
                      {paidDates.length === allLeaveDates.length ? "Clear all" : "All paid"}
                    </button>
                  </div>
                  <div className="mt-2 space-y-2 max-h-56 overflow-y-auto scroll-thin">
                    {leaveWeeks.map(({ week, dates }, i) => (
                      <div key={week} className="hol-surface" style={{ padding: 8 }}>
                        <div className="flex items-center justify-between" style={{ marginBottom: 6 }}>
                          <span style={{ fontSize: 11 }}>
                            Week {i + 1}
                            <span className="hol-muted font-mono" style={{ marginLeft: 8 }}>{week}</span>
                          </span>
                          <span style={{ fontSize: 10, color: "var(--primary)" }}>
                            {dates.filter((d) => paidDates.includes(d)).length
                              ? `${dates.filter((d) => paidDates.includes(d)).length} paid` : "none paid"}
                          </span>
                        </div>
                        <div className="flex gap-1">
                          {DAYS.map((dayKey, dayIndex) => {
                            const d = addDays(week, dayIndex);
                            const inRange = dates.includes(d);
                            const on = paidDates.includes(d);
                            return (
                              <button type="button" key={d} disabled={!inRange}
                                      onClick={() => toggleDate(d)}
                                      title={inRange ? d : `${d} — not in this booking`}
                                      className={`flex-1 py-1.5 ${on ? "btn btn-primary" : "btn btn-secondary"}`}
                                      style={{
                                        fontSize: 10, padding: "6px 0",
                                        opacity: inRange ? 1 : 0.25,
                                      }}>
                                {DAY_SHORT[dayKey]}
                                <span style={{ display: "block", fontSize: 8, opacity: 0.6 }}>
                                  {d.slice(8)}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                  {overBalance && (
                    <p style={{ fontSize: 11, color: "var(--danger)", marginTop: 6 }}>
                      That is {Math.round((requestedHours - balance.available_hours) * 100) / 100}h
                      more than they have left. Untick a day or book it as unpaid.
                    </p>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="hol-overline">Start date</label>
                <input data-testid="hol-date" required type="date" value={date}
                       onChange={(e) => setDate(e.target.value)}
                       className="mt-1.5 w-full px-3 py-2.5 font-mono" />
              </div>
              <div>
                <label className="hol-overline">End date (optional)</label>
                <input data-testid="hol-end" type="date" min={date} value={endDate}
                       onChange={(e) => setEndDate(e.target.value)}
                       className="mt-1.5 w-full px-3 py-2.5 font-mono" />
              </div>
            </div>
          )}

          <div>
            <label className="hol-overline">Label</label>
            <input data-testid="hol-label" value={label} onChange={(e) => setLabel(e.target.value)}
                   required={scope !== "leave-week"}
                   placeholder={scope === "shop" ? "Public holiday, closure…" : "Holiday"}
                   className="mt-1.5 w-full px-3 py-2.5" />
          </div>
        </div>

        <div className="flex items-center gap-2" style={{ marginTop: 22 }}>
          {editing && (
            <button type="button" onClick={remove} disabled={busy} className="btn btn-danger">
              Delete
            </button>
          )}
          <div className="ml-auto flex gap-2">
            <button type="button" onClick={onClose} className="btn btn-secondary">Cancel</button>
            <button
              data-testid="btn-add-holiday"
              disabled={busy || (scope === "leave-week" && (!empId || !allLeaveDates.length || overBalance))}
              className="btn btn-primary"
            >
              <CalendarPlus size={14} />
              {editing ? "Save changes"
                : scope === "leave-week"
                  ? (allLeaveDates.length
                      ? `Book ${allLeaveDates.length} day${allLeaveDates.length === 1 ? "" : "s"}`
                      : "Book leave")
                  : "Add"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
