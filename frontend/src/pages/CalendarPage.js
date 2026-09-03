/**
 * Holidays & off-days — built to the 3a handoff (which revises 1a/2a).
 *
 * WHAT WAS WRONG WITH THE ORIGINAL PAGE
 * -------------------------------------
 * Every leave entry rendered as an identical row — "2026-09-02 · N/A ·
 * Holiday (unpaid) · Elliot" — so the two questions a manager actually opens
 * this page with went unanswered: who is off right now, and does the shop
 * have cover. Four consecutive single days for one person read as four
 * unrelated bookings.
 *
 * ONE ROW PER PERSON PER CONTINUOUS ABSENCE
 * -----------------------------------------
 * That is the whole organising idea, and it took two goes. The first version
 * also merged people onto a shared row when their dates matched — "Wed 2 Sep
 * · Elliot, Tiago, Jamie, Aaron" — which reads well in a mock and badly
 * against real data: one Edit button, four bookings, no answer to whose is
 * whose. 3a reversed it.
 *
 * It also folded pay type into the run. Thirteen days off with four of them
 * paid is ONE absence tagged "Holiday · 9 unpaid + 4 paid", not three
 * bookings with gaps — the gaps were an artefact of how we store paid days,
 * and the manager was reading them as separate holidays. Expanding a run
 * shows the per-day detail.
 *
 * Every entry states WHEN THE PERSON IS BACK, which is the piece the old
 * list never carried.
 *
 * The `N/A` badge is gone. It was our `scope: "unavailable"` — unpaid leave —
 * rendered as an abbreviation that told the manager nothing. Where a field
 * has no value now, it is omitted rather than labelled.
 *
 * NOTES ON THE DATA, which is unchanged
 * -------------------------------------
 * `scope` carries what the handoff calls `type`:
 *
 *     shop         Shop closed      accent tag, row tinted
 *     employee     paid holiday     draws down entitlement
 *     unavailable  unpaid holiday   the old N/A
 *     sick         Sick             its own kind of absence, never folded in
 *
 * A booking made through the leave flow is one record PER DAY, which is what
 * makes "delete selected days" possible. A booking made as a date range is a
 * single record and can only be removed whole — the delete dialog says so
 * rather than offering a control that would fail.
 *
 * TODAY is taken from the browser. The handoff asks for the server's date,
 * and there is no endpoint for it; the risk is a manager whose machine is
 * set to another day. Worth adding when there is somewhere to put it.
 *
 * `node check-leave-runs.js` (yarn check:runs) pins the run rules.
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

   PAID AND UNPAID ARE ONE KIND OF ABSENCE, not two.
   -------------------------------------------------
   They were separate rows until the 3a revision, which is what produced the
   thing it fixes: Jithin books thirteen days off, four of them paid, and the
   page showed it as several bookings with gaps between them. It is one
   absence. He is away for thirteen days and the shop needs cover for
   thirteen days; which of them draw down his entitlement is a payroll
   question, and the answer belongs in the tag rather than in the shape of
   the list.

   SICK IS NOT FOLDED IN. It is a different kind of absence rather than a
   different way of paying for one, and merging it would put "Sick" and
   "Holiday" under a single label that describes neither. A sick day next to
   a holiday stays its own row.
------------------------------------------------------------------------- */
const HOLIDAY_SCOPES = new Set(["employee", "unavailable"]);
const familyOf = (scope) => (HOLIDAY_SCOPES.has(scope) ? "holiday" : scope);
const isPaid = (scope) => scope === "employee";

/** The tag for a whole absence: one label, even when the pay type changes. */
export function tagFor(run) {
  if (run.family === "shop") return { label: "Shop closed", tone: "accent" };
  if (run.family === "sick") return { label: "Sick", tone: "neutral" };
  if (run.paidDays && run.unpaidDays) {
    return {
      label: `Holiday · ${run.unpaidDays} unpaid + ${run.paidDays} paid`,
      tone: "neutral",
    };
  }
  return run.paidDays
    ? { label: "Holiday · paid", tone: "neutral" }
    : { label: "Holiday · unpaid", tone: "outline" };
}

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
 * Collapse entries into runs — one continuous absence per person.
 *
 * A person's adjacent leave days become a single row. Nothing else merges:
 * two people off the same days are two rows, because the manager is looking
 * for who is missing, and a name is what they act on.
 *
 * This is narrower than it was. Runs of the same shape used to merge their
 * people onto one row — "Wed 2 Sep · Elliot, Tiago, Jamie, Aaron" — which
 * reads well in a mock and badly against real data: the row for four people
 * has one Edit button and no obvious answer to "whose booking is this".
 *
 * PAY TYPE DOES NOT BREAK A RUN. Thirteen days off with four of them paid is
 * one absence, tagged "Holiday · 9 unpaid + 4 paid", not three bookings with
 * gaps. `dayScopes` keeps the per-day detail so the run can be expanded.
 *
 * `days` counts CALENDAR days, not working days. A run across a weekend the
 * shop is closed still reads as its full length — which is what a manager
 * means by "four days off", but is worth knowing before this number is used
 * for anything that costs money.
 */
export function buildRuns(entries, nameOf) {
  const byPerson = new Map();
  for (const entry of entries) {
    // Keyed on the FAMILY, not the scope, so paid and unpaid days of one
    // holiday land in the same bucket and can join up.
    const key = `${entry.employee_id || "shop"}|${familyOf(entry.scope)}`;
    if (!byPerson.has(key)) byPerson.set(key, []);
    for (const date of datesOf(entry)) {
      byPerson.get(key).push({ date, entry });
    }
  }

  const runs = [];
  for (const [key, atoms] of byPerson) {
    atoms.sort((a, b) => a.date.localeCompare(b.date));
    const [employeeId, family] = key.split("|");
    let current = null;
    const push = () => { if (current) runs.push(current); };

    for (const atom of atoms) {
      const adjacent = current && addDays(current.end, 1) === atom.date;
      const sameDay = current && current.end === atom.date;
      if (!adjacent && !sameDay) {
        push();
        current = {
          id: `${employeeId}|${family}|${atom.date}`,
          start: atom.date, end: atom.date, family,
          employeeId: employeeId === "shop" ? null : employeeId,
          entries: new Set(), dayScopes: new Map(),
        };
      }
      if (adjacent) current.end = atom.date;
      current.entries.add(atom.entry);
      // A day booked twice keeps the PAID record: it is the one that costs
      // entitlement, and showing a paid day as unpaid understates what the
      // employee has spent.
      if (!current.dayScopes.has(atom.date) || isPaid(atom.entry.scope)) {
        current.dayScopes.set(atom.date, atom.entry.scope);
      }
    }
    push();
  }

  return runs
    .map((run) => {
      const scopes = [...run.dayScopes.values()];
      return {
        ...run,
        person: run.employeeId ? nameOf(run.employeeId) : null,
        entries: [...run.entries],
        dayScopes: [...run.dayScopes.entries()],
        days: run.dayScopes.size,
        paidDays: scopes.filter(isPaid).length,
        unpaidDays: scopes.filter((s) => s === "unavailable").length,
      };
    })
    .sort((a, b) =>
      a.start.localeCompare(b.start)
      || (a.person || "").localeCompare(b.person || "")
      || a.family.localeCompare(b.family));
}

/**
 * A run's days, laid out one calendar week per row.
 *
 * Thirteen days as a continuous strip of chips reads as one long ribbon —
 * "Monday, Tuesday, Wednesday ... Monday, Tuesday" — and you cannot see
 * where one week ends and the next begins, which is how a manager thinks
 * about cover. So each week gets a row and every day sits under its own
 * weekday column, with the days outside the absence left empty.
 *
 * The same shape the booking form already uses for picking paid days, for
 * the same reason.
 *
 * Returns [{ week, days: [Mon..Sun] }], each day either {date, scope} or
 * null. Weeks start Monday, matching the rest of the app.
 */
export function weeksOf(dayScopes) {
  const byWeek = new Map();
  for (const [date, scope] of dayScopes) {
    const week = mondayOf(date);
    if (!byWeek.has(week)) byWeek.set(week, new Array(7).fill(null));
    // getDay() is 0 for Sunday, so shift it to put Monday at index 0.
    byWeek.get(week)[(parseIso(date).getDay() + 6) % 7] = { date, scope };
  }
  return [...byWeek.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([week, days]) => ({ week, days }));
}

/**
 * Which buttons a row shows.
 *
 * EDIT IS ALWAYS ONE OF THEM. It used to be swapped out for "Show days"
 * whenever a run was stitched from several records — and because the booking
 * flow writes one record PER DAY, that was every multi-day holiday. A
 * one-day leave could be edited and a five-day one could not, which is
 * exactly what the shop owner hit.
 *
 * They answer different questions and are not alternatives: "Show days"
 * explains what the mixed tag is claiming, "Edit" changes the booking.
 */
export function rowActions(run) {
  return { edit: true, expand: run.entries.length > 1 };
}

/**
 * One record, wrapped as a run.
 *
 * The edit dialog takes a run, so that editing "Jithin's thirteen days" and
 * editing "the Thursday inside it" are the same code path with a different
 * scope. Clicking a day chip is the second one.
 */
function runForEntry(entry, run) {
  return {
    ...run,
    id: `${run.id}|${entry.holiday_id}`,
    entries: [entry],
    start: entry.date,
    end: entry.end_date || entry.date,
    dayScopes: datesOf(entry).map((d) => [d, entry.scope]),
    days: datesOf(entry).length,
    paidDays: isPaid(entry.scope) ? datesOf(entry).length : 0,
    unpaidDays: entry.scope === "unavailable" ? datesOf(entry).length : 0,
  };
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
  const [deleting, setDeleting] = useState(null);

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
      .map((run) => ({
        employeeId: run.employeeId,
        name: run.person || "Unknown",
        backOn: addDays(run.end, 1),
        tag: tagFor(run),
      }));
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
    const header = ["Who", "Start", "End", "Days", "Paid", "Unpaid", "Type", "Label"];
    const lines = allRuns.map((run) => [
      run.family === "shop" ? "Whole shop" : run.person || "—",
      run.start, run.end, run.days, run.paidDays, run.unpaidDays,
      tagFor(run).label,
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

      {/* 2 — right now --------------------------------------------------
          Restructured by 3a: the headline and the callout sit side by side,
          and the person cells moved OUT into a full-width band below them.
          The "working today" list is gone with them — with 25 staff it was a
          21-name column answering a question the callout answers in a
          sentence. */}
      <div className="hol-rightnow grid" style={{
        gridTemplateColumns: "1fr 360px",
        alignItems: "stretch",
        borderBottom: "1px solid var(--hairline)",
      }}>
        <div style={{ padding: "24px 30px 22px" }}>
          <div className="hol-overline">Right now — {fmtDay(today)} {year}</div>

          {offToday.length === 0 ? (
            /* The handoff's empty state: the numeral band is replaced rather
               than showing a zero, which reads as an error. */
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 21, fontWeight: 800, lineHeight: 1.15 }}>
                Nobody is off today — all {activeStaff.length} staff on shift
              </div>
              <div className="hol-muted" style={{ fontSize: 13, marginTop: 4 }}>
                {shopClosedToday ? "The shop is closed today."
                  : openHours ? `Shop open ${openHours}` : "Shop hours not set"}
              </div>
            </div>
          ) : (
            <div className="flex items-end gap-4" style={{ marginTop: 6 }}>
              <div className="hol-numeral">{offToday.length}</div>
              <div style={{ fontSize: 21, fontWeight: 800, lineHeight: 1.15, paddingBottom: 4 }}>
                of {activeStaff.length} staff are off today
                <div className="hol-muted" style={{ fontSize: 13, fontWeight: 400, lineHeight: 1.4 }}>
                  {workingToday.length} working
                  {shopClosedToday ? " · shop closed today"
                    : openHours ? ` · shop open ${openHours}` : ""}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="hol-surface flex items-center" style={{
          borderLeft: "2px solid var(--hairline)", padding: "20px 24px",
        }}>
          <div style={{ fontSize: 13, lineHeight: 1.5 }}>
            {everyoneBack && <>{fmtDay(everyoneBack)} everyone is back.<br /></>}
            <span className="hol-muted">
              {nextGap ? (
                <>Next gap: <strong style={{ color: "var(--ink)" }}>{fmtDay(nextGap.start)}</strong>,{" "}
                  {nextGap.family === "shop" ? "when the shop closes"
                    : `when ${nextGap.person} starts ${nextGap.days} day${nextGap.days === 1 ? "" : "s"} off`}.
                </>
              ) : (
                <>No further leave is booked.</>
              )}
            </span>
          </div>
        </div>
      </div>

      {/* The people who are off, full width. Every cell says when they are
          back — the piece the old list never carried. */}
      {offToday.length > 0 && (
        <div className="hol-people grid" style={{
          gridTemplateColumns: "repeat(4, 1fr)",
          borderLeft: "1px solid var(--hairline)",
        }}>
          {offToday.map((person) => (
            <div key={person.employeeId} style={{
              borderRight: "1px solid var(--hairline)",
              borderBottom: "1px solid var(--hairline)",
              padding: "14px 16px 16px",
            }}>
              <div style={{ fontSize: 17, fontWeight: 800 }}>{person.name}</div>
              <div className="hol-muted" style={{ fontSize: 12, margin: "2px 0 10px" }}>
                {person.backOn === addDays(today, 1)
                  ? `Back tomorrow, ${fmtDay(person.backOn)}`
                  : `Back ${fmtDay(person.backOn)}`}
              </div>
              <span className={`hol-tag hol-tag-${person.tag.tone}`}>{person.tag.label}</span>
            </div>
          ))}
        </div>
      )}
      <div className="hol-band" />

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
              ["allUpcoming", "All upcoming"],
              ["past", "Past"],
            ].map(([key, label]) => (
              <button
                key={key}
                data-testid={`hol-view-${key}`}
                aria-pressed={view === key}
                onClick={() => setView(key)}
                className="btn hol-seg-opt"
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
          onDelete={setDeleting}
          emptyMessage={
            view === "past" ? "No leave has been taken yet."
              : view === "allUpcoming" ? "No leave is booked."
                : "No leave booked in the next 30 days."
          }
        />

        {rows.length > 0 && (
          <div className="hol-faint" style={{ marginTop: 12, fontSize: 12 }}>
            Rows are one continuous absence per person. A change of pay type
            mid-run shows as a mixed tag with a <strong style={{ fontWeight: 600 }}>Show days</strong> breakdown,
            not as a new row.{" "}
            <strong style={{ color: "var(--ink-secondary)", fontWeight: 600 }}>Delete</strong>{" "}
            removes a booking added by mistake — it asks to confirm first, and
            on a run booked day by day it offers the whole absence or just some
            days.
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
          run={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
      {deleting && (
        <DeleteRunDialog
          run={deleting}
          onClose={() => setDeleting(null)}
          onDone={() => { setDeleting(null); load(); }}
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
   A run's days, as a small week-by-week calendar

   Shared by the expanded row (where a day opens for editing) and the delete
   dialog (where a day is selected for removal), so the two cannot drift into
   showing the same absence differently.
------------------------------------------------------------------------- */
function DayGrid({ days, onPick, isSelected, label }) {
  const weeks = weeksOf(days);
  return (
    <div>
      <div className="hol-daygrid hol-daygrid-head">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      {weeks.map(({ week, days: row }) => (
        <div key={week} className="hol-daygrid">
          {row.map((day, i) => (
            day ? (
              <button
                key={day.date}
                type="button"
                className={`hol-chip${
                  (isSelected ? isSelected(day.date) : isPaid(day.scope))
                    ? " hol-chip-paid" : ""}`}
                onClick={() => onPick(day.date)}
                title={label ? `${label} ${day.date}` : day.date}
              >
                {day.date.slice(8).replace(/^0/, "")}{" "}
                <span className="hol-chip-kind">
                  {isPaid(day.scope) ? "paid"
                    : day.scope === "sick" ? "sick" : "unpaid"}
                </span>
              </button>
            ) : (
              /* A day the absence does not cover. Kept as an empty cell so
                 the weekday columns stay aligned down the grid — without it
                 a run starting on a Wednesday would put Wednesday under
                 Monday. */
              <span key={`${week}-${i}`} className="hol-chip-empty" aria-hidden />
            )
          ))}
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------
   The table

   Columns are Who first: the manager is scanning for a NAME, and the 3a
   revision puts it where the eye lands. Edit and Delete both sit on the row.

   Delete was inside the edit form for one revision, on the reasoning that a
   one-click trash icon next to eight others is easy to hit by accident. 3a
   brings it back to the row and answers that differently — it is a labelled
   word rather than an icon, and it always confirms. On a run made of several
   day-records the confirm offers the whole absence or just some days.
------------------------------------------------------------------------- */
function LeaveTable({ groups, expanded, onToggleRun, onEdit, onDelete, emptyMessage }) {
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
          <th style={{ width: 150 }}>Who</th>
          <th style={{ width: 200 }}>Dates</th>
          <th style={{ width: 70 }} className="hol-days-col">Days</th>
          <th>Type</th>
          <th style={{ width: 170 }}><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {groups.map((group) => (
          <React.Fragment key={group.label}>
            <tr className="hol-group"><td colSpan={5}>{group.label}</td></tr>
            {group.runs.map((run) => {
              const tag = tagFor(run);
              const isOpen = expanded.includes(run.id);
              // EDIT IS ALWAYS PRESENT. It used to be swapped OUT for "Show
              // days" whenever a run was stitched from several records —
              // which is every multi-day holiday, because the booking flow
              // writes one record per day. So a five-day absence had no way
              // to change its dates at all, and the manager asked why a
              // one-day leave could be edited and a longer one could not.
              //
              // They are not alternatives. Show days explains what the
              // mixed tag is claiming; Edit changes the booking.
              const actions = rowActions(run);
              const mixed = run.paidDays > 0 && run.unpaidDays > 0;
              return (
                <React.Fragment key={run.id}>
                  <tr className={`hol-row${run.family === "shop" ? " hol-shop-closed" : ""}${isOpen ? " hol-open" : ""}`}>
                    <td style={{ fontWeight: 600 }}>
                      {run.family === "shop" ? "Whole shop closed" : run.person || "—"}
                    </td>
                    <td>{fmtRange(run.start, run.end)}</td>
                    <td className="hol-days-col">{run.days}</td>
                    <td><span className={`hol-tag hol-tag-${tag.tone}`}>{tag.label}</span></td>
                    <td>
                      <div className="flex justify-end gap-1">
                        {actions.expand && (
                          <button className="btn btn-ghost hol-action"
                                  onClick={() => onToggleRun(run.id)}>
                            {isOpen ? "Hide days" : "Show days"}
                          </button>
                        )}
                        {actions.edit && (
                          <button className="btn btn-ghost hol-action"
                                  onClick={() => onEdit(run)}>
                            Edit
                          </button>
                        )}
                        <button className="btn btn-ghost hol-action hol-action-quiet"
                                onClick={() => onDelete(run)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>

                  {isOpen && (
                    <tr className="hol-open">
                      <td />
                      <td colSpan={4} style={{ paddingTop: 0 }}>
                        {/* One week per row, each day under its own
                            weekday column. A thirteen-day absence as a
                            continuous strip reads as an unbroken ribbon and
                            hides where the weeks divide, which is how cover
                            is actually thought about. */}
                        <div style={{ paddingBottom: 8 }}>
                          <DayGrid
                            days={run.dayScopes}
                            label="Edit"
                            onPick={(date) => {
                              const entry = run.entries.find(
                                (e) => e.date === date && !e.end_date,
                              );
                              if (entry) onEdit(runForEntry(entry, run));
                            }}
                          />
                        </div>
                        <div className="hol-faint" style={{ fontSize: 11, paddingBottom: 8 }}>
                          One absence, {run.days} day{run.days === 1 ? "" : "s"}.
                          {mixed ? " Paid days sit inside the run — they no longer split it into separate rows." : ""}
                        </div>
                      </td>
                    </tr>
                  )}
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
   Deleting an absence

   "It asks to confirm first, and on a mixed run it offers delete the whole
   absence or delete selected days."

   A booking made through the leave flow is one record PER DAY, so selected
   days can simply be removed. A booking made as a RANGE is one record, and
   there is no endpoint to split it — so that case is offered whole-absence
   deletion only, and says why rather than showing a control that would fail.
------------------------------------------------------------------------- */
function DeleteRunDialog({ run, onClose, onDone }) {
  const perDay = run.entries.length > 1;
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);

  const entryForDay = (date) =>
    run.entries.find((e) => e.date === date && !e.end_date);

  const remove = async (entries) => {
    setBusy(true);
    try {
      // Sequential rather than parallel: a partial failure should leave a
      // comprehensible state, not a scatter of half-deleted days.
      for (const entry of entries) {
        await api.delete(`/holidays/${entry.holiday_id}`);
      }
      toast.success(entries.length === 1 ? "Removed" : `Removed ${entries.length} days`);
      onDone();
    } catch (err) {
      toast.error(errorMessage(err, "Could not remove"));
      setBusy(false);
    }
  };

  return (
    <div className="hol-page fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
         onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="card elevated w-full max-w-md"
           style={{ padding: 24 }}>
        <div className="hol-kicker">Remove</div>
        <h2 className="hol-h2" style={{ margin: "2px 0 10px" }}>
          {run.family === "shop" ? "Whole shop closed" : run.person}
        </h2>
        <p className="hol-muted" style={{ fontSize: 13, lineHeight: 1.5 }}>
          {fmtRange(run.start, run.end)} · {run.days} day{run.days === 1 ? "" : "s"}.
          {" "}This cannot be undone.
        </p>

        {perDay && (
          <div style={{ marginTop: 16 }}>
            <div className="hol-overline" style={{ marginBottom: 8 }}>
              Or remove only some days
            </div>
            <DayGrid
              days={run.dayScopes}
              label="Remove"
              isSelected={(date) => selected.includes(date)}
              onPick={(date) => setSelected((prev) =>
                prev.includes(date) ? prev.filter((d) => d !== date) : [...prev, date])}
            />
          </div>
        )}
        {!perDay && run.days > 1 && (
          <p className="hol-faint" style={{ fontSize: 12, marginTop: 12 }}>
            This absence was booked as a single date range, so it can only be
            removed whole. To shorten it, use Edit and change the end date.
          </p>
        )}

        <div className="flex items-center gap-2" style={{ marginTop: 22 }}>
          <button className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <div className="ml-auto flex gap-2">
            {perDay && selected.length > 0 && (
              <button className="btn btn-danger" disabled={busy}
                      onClick={() => remove(selected.map(entryForDay).filter(Boolean))}>
                Delete {selected.length} day{selected.length === 1 ? "" : "s"}
              </button>
            )}
            <button className="btn btn-danger" disabled={busy}
                    onClick={() => remove(run.entries)}>
              Delete whole absence
            </button>
          </div>
        </div>
      </div>
    </div>
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
function LeaveModal({ employees, run, onClose, onSaved }) {
  const editing = Boolean(run);
  // A run of ONE record is edited in place. A run stitched from several
  // day-records is re-booked as a whole, because there is no "edit these
  // eleven records" endpoint and editing only the first would silently
  // change one day of an eleven-day holiday.
  const single = editing && run.entries.length === 1 ? run.entries[0] : null;
  const wholeAbsence = editing && !single;
  // Only a HOLIDAY absence can be re-booked through /holidays/leave, which
  // writes paid and unpaid days. Sending a multi-day SICK run through it
  // would rewrite every one of those days as holiday — silently, and against
  // the employee's entitlement. Those collapse into a single range record
  // instead, keeping their own scope.
  const rebook = wholeAbsence && run.family === "holiday";
  const collapse = wholeAbsence && !rebook;

  const [scope, setScope] = useState(
    single?.scope || (wholeAbsence ? "leave-week" : "shop"));
  const [empId, setEmpId] = useState(
    single?.employee_id || run?.employeeId || "");
  const [date, setDate] = useState(single?.date || run?.start || "");
  const [endDate, setEndDate] = useState(
    single?.end_date || (run && run.end !== run.start ? run.end : ""));
  const [label, setLabel] = useState(
    single?.label || run?.entries?.[0]?.label || "");
  const [busy, setBusy] = useState(false);

  // The paid-day picker: used when booking new leave, and when re-booking a
  // whole absence, which is the same operation with the dates filled in.
  const [leaveFrom, setLeaveFrom] = useState(wholeAbsence ? run.start : "");
  const [leaveTo, setLeaveTo] = useState(wholeAbsence ? run.end : "");
  const [paidDates, setPaidDates] = useState(
    wholeAbsence
      ? run.dayScopes.filter(([, sc]) => isPaid(sc)).map(([d]) => d)
      : []);
  const [balance, setBalance] = useState(null);

  // Editing a whole absence has no type switch: it IS an employee holiday,
  // and the paid-day picker is where paid and unpaid are decided.
  const scopeOpts = wholeAbsence
    ? []
    : single
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
    if (!empId || (scope !== "leave-week" && !rebook)) { setBalance(null); return; }
    let cancelled = false;
    const params = hoursPerDay ? `?hours_per_day=${hoursPerDay}` : "";
    api.get(`/holiday-balance/${empId}${params}`)
      .then((r) => { if (!cancelled) setBalance(r.data); })
      .catch(() => { if (!cancelled) setBalance(null); });
    return () => { cancelled = true; };
  }, [empId, scope, hoursPerDay, rebook]);

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
      if (single) {
        await api.put(`/holidays/${single.holiday_id}`, {
          date, end_date: endDate || null, label,
          scope, employee_id: scope === "shop" ? null : empId,
        });
        toast.success("Leave updated");
      } else if (rebook) {
        // RE-BOOK, DO NOT DELETE FIRST.
        //
        // `/holidays/leave` already replaces any existing leave inside the
        // range it is given, so posting the new booking corrects the days it
        // covers in one call. Deleting first would open a window where a
        // failure leaves the manager with no booking at all; this way a
        // failure leaves the original untouched.
        //
        // What the POST cannot know about is days the absence USED to cover
        // and no longer does — shortening 17-20 Sep to 17-18 leaves the 19th
        // and 20th behind — so those are removed afterwards, by id.
        const kept = new Set(
          (() => {
            const out = [];
            for (let d = leaveFrom, guard = 0; d <= leaveTo && guard < 400;
                 d = addDays(d, 1), guard++) out.push(d);
            return out;
          })(),
        );
        const r = await api.post("/holidays/leave", {
          employee_id: empId, start_date: leaveFrom, end_date: leaveTo,
          paid_dates: paidDates, label: label || "Holiday",
        });
        const orphans = run.entries.filter(
          (x) => !x.end_date && !kept.has(x.date),
        );
        for (const orphan of orphans) {
          await api.delete(`/holidays/${orphan.holiday_id}`);
        }
        toast.success(
          `${r.data.employee}: ${r.data.paid_days} paid day(s) = ${r.data.paid_hours_total}h` +
          (r.data.unpaid_days ? `, ${r.data.unpaid_days} unpaid` : "") +
          (orphans.length ? `, ${orphans.length} day(s) removed` : ""),
        );
      } else if (collapse) {
        // Several day-records of the same kind become ONE range record: the
        // first is stretched to the new span and the rest removed. Widened
        // first, so a failure part-way leaves the days still covered rather
        // than a hole in the middle of somebody's sick leave.
        const [keep, ...rest] = run.entries;
        await api.put(`/holidays/${keep.holiday_id}`, {
          date, end_date: endDate || date, label,
          scope: keep.scope,
          employee_id: keep.scope === "shop" ? null : empId,
        });
        for (const extra of rest) {
          await api.delete(`/holidays/${extra.holiday_id}`);
        }
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
              {wholeAbsence ? run.person || "Edit leave"
                : editing ? "Edit leave" : "Add leave"}
            </h2>
            {wholeAbsence && (
              <div className="hol-muted" style={{ fontSize: 12, marginTop: 4 }}>
                {fmtRange(run.start, run.end)} · {run.days} day
                {run.days === 1 ? "" : "s"} · change the dates or which days
                are paid
              </div>
            )}
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4">
          {scopeOpts.length > 0 && (
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
          )}

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

          {(scope === "leave-week" || rebook) && balance && (
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

          {(scope === "leave-week" || rebook) ? (
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
          <div className="ml-auto flex gap-2">
            <button type="button" onClick={onClose} className="btn btn-secondary">Cancel</button>
            <button
              data-testid="btn-add-holiday"
              disabled={busy || ((scope === "leave-week" || rebook)
                && (!empId || !allLeaveDates.length || overBalance))}
              className="btn btn-primary"
            >
              <CalendarPlus size={14} />
              {editing ? "Save changes"
                : (scope === "leave-week" || rebook)
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
