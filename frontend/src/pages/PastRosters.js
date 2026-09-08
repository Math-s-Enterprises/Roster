import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, fmtHours, fmtMoney, DAY_LABELS, DAYS, dateForDay, shiftPaidHours } from "@/lib/api";
import { toast } from "sonner";
import { Download, Search, Calendar } from "lucide-react";

/**
 * Past rosters — archive table (handoff: Past rosters).
 *
 * The flat card list became one row per approved week, grouped by month
 * with per-month totals, and a separate Version history section for the
 * drafts that were replaced. Styling is the handoff's palette, scoped to
 * .par-* in index.css.
 *
 * The split falls out of real fields rather than anything invented:
 * /rosters/past returns every roster whose week has ended, approved or
 * not. `approved` picks the main list; everything else is a version. In
 * history, `manually_edited` reads as "Edited by hand" and `archived` as
 * "Superseded", which is exactly what those flags mean.
 *
 * WHERE THIS DEPARTS FROM THE HANDOFF
 *
 * 1. The date range uses two native date inputs inside the search field
 *    rather than a custom two-month picker popover. Same filtering, same
 *    position in the layout, but it inherits the platform's own keyboard
 *    handling and mobile date UI instead of reimplementing them.
 *
 * 2. Export archive and the per-row Export are stubs. No export endpoint
 *    exists; both say so rather than failing silently.
 *
 * 3. Open links to /roster?week=... — the existing roster view keyed by
 *    week — because there is no read-only /rosters/:id route in this app.
 *
 * 4. No "approved by" name on the row: rosters record approved_at but not
 *    who approved them.
 */

const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

const RECENT_MONTHS = 3;
const PAGE_SIZE = 8;
const VERSIONS_PAGE_SIZE = 5;

const parseDay = (iso) => new Date(`${iso}T00:00:00`);

const addDays = (iso, n) => {
  const d = parseDay(iso);
  d.setDate(d.getDate() + n);
  return d;
};

/** "Mon 24 – Sun 30 Aug", collapsing the month when both ends share one. */
function weekTitle(weekStart) {
  const from = parseDay(weekStart);
  const to = addDays(weekStart, 6);
  const day = (d) => d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
  const month = (d) => d.toLocaleDateString(undefined, { month: "short" });
  return from.getMonth() === to.getMonth()
    ? `${day(from)} – ${day(to)} ${month(to)}`
    : `${day(from)} ${month(from)} – ${day(to)} ${month(to)}`;
}

const monthKeyOf = (weekStart) => {
  const d = parseDay(weekStart);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

const monthLabel = (key) => {
  const [y, m] = key.split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`;
};

const fmtStamp = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
};

/** Distinct people actually rostered that week. */
const peopleIn = (roster) =>
  new Set((roster.shifts || [])
    .filter((s) => s.start && s.end)
    .map((s) => s.employee_id)).size;

/** What a non-approved roster is: replaced, hand-edited, or just a draft. */
function versionState(roster) {
  if (roster.approved) return { text: "Approved", on: true };
  if (roster.manually_edited) return { text: "Edited by hand", on: false };
  if (roster.archived) return { text: "Superseded", on: false };
  return { text: "Draft", on: false };
}

export default function PastRosters() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [scope, setScope] = useState("recent");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [versionsVisible, setVersionsVisible] = useState(VERSIONS_PAGE_SIZE);

  const [emps, setEmps] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get("/rosters/past"),
      api.get("/employees").catch(() => ({ data: [] })),
    ])
      .then(([r, e]) => { setItems(r.data || []); setEmps(e.data || []); })
      .catch((err) => toast.error(errorMessage(err, "Could not load the archive")))
      .finally(() => setLoading(false));
  }, []);

  const empMap = useMemo(
    () => Object.fromEntries(emps.map((e) => [e.employee_id, e])),
    [emps],
  );

  /**
   * Export runs entirely in the browser. Archived rosters arrive with
   * their shifts attached, so there is nothing to ask the server for —
   * and no export endpoint exists to ask.
   */
  const download = (name, rows) => {
    const escape = (v) => {
      const str = String(v ?? "");
      return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
    };
    const csv = rows.map((r) => r.map(escape).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  /** One roster: a row per shift, in day order. */
  const exportRoster = (roster) => {
    const rows = [["Employee", "Role", "Day", "Date", "Start", "End", "Hours"]];
    [...(roster.shifts || [])]
      .sort((a, b) => (DAYS.indexOf(a.day) - DAYS.indexOf(b.day))
        || String(a.start || "").localeCompare(String(b.start || "")))
      .forEach((sh) => {
        const e = empMap[sh.employee_id] || {};
        const label = sh.paid_holiday ? "Holiday" : sh.unpaid_holiday ? "Unpaid" : sh.sick ? "Sick" : "";
        rows.push([
          e.name || sh.employee_id,
          e.role || "",
          DAY_LABELS[sh.day] || sh.day,
          dateForDay(roster.week_start, sh.day).toISOString().slice(0, 10),
          sh.start || label,
          sh.end || label,
          shiftPaidHours(sh).toFixed(1),
        ]);
      });
    if (rows.length === 1) {
      toast.error("That roster has no shifts to export");
      return;
    }
    download(`roster-${roster.week_start}-${roster.version || "v1"}.csv`, rows);
    toast.success(`Exported ${weekTitle(roster.week_start)}`);
  };

  /** The archive: one row per approved week, matching what is on screen. */
  const exportArchive = () => {
    if (approved.length === 0) {
      toast.error("Nothing to export with the current filters");
      return;
    }
    const rows = [["Week starting", "Week ending", "Version", "Hours", "Wage bill", "Score", "People", "Approved"]];
    approved.forEach((r) => {
      rows.push([
        r.week_start,
        addDays(r.week_start, 6).toISOString().slice(0, 10),
        r.version || "",
        Number(r.total_hours || 0).toFixed(1),
        Number(r.labor_cost || 0).toFixed(2),
        r.compliance_score ?? "",
        peopleIn(r),
        r.approved_at || "",
      ]);
    });
    download(`roster-archive-${new Date().toISOString().slice(0, 10)}.csv`, rows);
    toast.success(`Exported ${approved.length} ${approved.length === 1 ? "week" : "weeks"}`);
  };

  /**
   * One filter for both tables. Query matches the ISO date, the rendered
   * week title and the month name, so "31 Aug", "2026-08-31" and "August"
   * all work. A range keeps any week that overlaps it.
   */
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - RECENT_MONTHS);

    return (roster) => {
      const start = roster.week_start;
      if (!start) return false;

      if (q) {
        const hay = [
          start,
          weekTitle(start),
          monthLabel(monthKeyOf(start)),
          roster.version || "",
        ].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }

      if (from || to) {
        const weekEnd = addDays(start, 6);
        const weekStart = parseDay(start);
        if (from && weekEnd < parseDay(from)) return false;
        if (to && weekStart > parseDay(to)) return false;
      } else if (scope === "recent" && parseDay(start) < cutoff) {
        return false;
      }
      return true;
    };
  }, [query, from, to, scope]);

  const approved = useMemo(
    () => items.filter((r) => r.approved).filter(matches)
      .sort((a, b) => b.week_start.localeCompare(a.week_start)),
    [items, matches],
  );

  const versions = useMemo(
    () => items.filter((r) => !r.approved).filter(matches)
      .sort((a, b) => b.week_start.localeCompare(a.week_start)),
    [items, matches],
  );

  /** Months in order, each with its own totals and its peak wage bill. */
  const months = useMemo(() => {
    const shown = approved.slice(0, visible);
    const map = new Map();
    shown.forEach((r) => {
      const key = monthKeyOf(r.week_start);
      if (!map.has(key)) map.set(key, { key, list: [], hours: 0, wage: 0 });
      const g = map.get(key);
      g.list.push(r);
      g.hours += Number(r.total_hours) || 0;
      g.wage += Number(r.labor_cost) || 0;
    });
    return [...map.values()].map((g) => ({
      ...g,
      peak: Math.max(...g.list.map((r) => Number(r.labor_cost) || 0)),
    }));
  }, [approved, visible]);

  const hasRange = Boolean(from || to);

  const clearRange = () => { setFrom(""); setTo(""); };

  const rangeLabel = () => {
    const f = from ? parseDay(from).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "Any";
    const t = to ? parseDay(to).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "Any";
    return `${f} → ${t}`;
  };

  return (
    <div className="par-page">
      <header className="par-head">
        <div>
          <div className="par-eyebrow">ARCHIVE</div>
          <h1 className="par-h1">Past rosters</h1>
          <p className="par-sub">
            Rosters whose week has already ended, grouped by month. Still searchable, printable
            and exportable.
          </p>
        </div>
        <button type="button" className="par-btn" onClick={exportArchive}>
          <Download size={15} strokeWidth={1.6} /> Export archive
        </button>
      </header>

      <div className="par-searchband">
        <div className="par-search">
          <Search size={14} color="#6f6f6f" strokeWidth={1.6} aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by date — or pick a range"
            aria-label="Search rosters by date"
            style={{ color: query ? "#e6e6e6" : undefined }}
          />
          {query && (
            <button
              type="button"
              className="par-clear-text"
              onClick={() => setQuery("")}
              aria-label="Clear search text"
            >
              <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                <path d="M1.6 1.6l6.8 6.8M8.4 1.6L1.6 8.4" stroke="#c9c9c9"
                  strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </button>
          )}
          <span className="par-range" title={rangeLabel()}>
            <Calendar size={14} color="#8c8c8c" strokeWidth={1.6} aria-hidden="true" />
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
              aria-label="Range from"
            />
            <span className="par-range-arrow" aria-hidden="true">→</span>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
              aria-label="Range to"
            />
          </span>
          {hasRange && (
            <button
              type="button"
              className="par-clear-range"
              onClick={clearRange}
              aria-label="Clear date range"
            >
              Clear
            </button>
          )}
        </div>

        <div role="group" aria-label="Scope" style={{ display: "flex", gap: 6 }}>
          <button
            type="button"
            className="par-pill"
            aria-pressed={scope === "recent" && !hasRange}
            onClick={() => { clearRange(); setScope("recent"); }}
          >
            Recent
          </button>
          <button
            type="button"
            className="par-pill"
            aria-pressed={scope === "all" && !hasRange}
            onClick={() => { clearRange(); setScope("all"); }}
          >
            All time
          </button>
        </div>
      </div>

      <div className="par-section">
        <h2 className="par-h2">Archived rosters <span>({approved.length})</span></h2>
        <span className="par-hint">Newest month first</span>
      </div>

      <div className="par-table" role="table" aria-label="Archived rosters">
        <div className="par-row par-colhead" role="row">
          <span role="columnheader">Roster week</span>
          <span role="columnheader">Hours</span>
          <span role="columnheader">Wage bill</span>
          <span role="columnheader">Score</span>
          <span role="columnheader">State</span>
          <span role="columnheader" aria-label="Actions" />
        </div>

        {loading ? (
          <div className="par-emptyrow">Loading…</div>
        ) : approved.length === 0 ? (
          <div className="par-emptyrow">
            <span>
              {items.length === 0
                ? "Nothing archived yet — rosters appear here once their week ends."
                : hasRange
                  ? `No rosters between ${rangeLabel()}.`
                  : "No rosters match that search."}
            </span>
            {hasRange && (
              <button type="button" className="par-link" onClick={clearRange}>Clear range</button>
            )}
          </div>
        ) : months.map((g, gi) => (
          <div key={g.key} role="rowgroup">
            <div className="par-monthhead" data-later={gi > 0}>
              <span className="par-monthname">{monthLabel(g.key)} ({g.list.length})</span>
              <span className="par-monthtot">
                {fmtHours(g.hours)} · {fmtMoney(g.wage)}
              </span>
            </div>

            {g.list.map((r) => {
              const title = weekTitle(r.week_start);
              const stamp = fmtStamp(r.approved_at);
              const people = peopleIn(r);
              const wage = Number(r.labor_cost) || 0;
              return (
                <div className="par-row par-data" role="row" key={r.roster_id}>
                  <div role="cell" style={{ minWidth: 0 }}>
                    <div className="par-title">{title}</div>
                    <div className="par-meta">
                      {stamp ? `Approved ${stamp}` : "Approved"}
                      {people > 0 && ` · ${people} ${people === 1 ? "person" : "people"}`}
                      {r.department ? ` · ${r.department}` : ""}
                    </div>
                  </div>
                  <div className="par-num" role="cell">{fmtHours(r.total_hours)}</div>
                  <div className="par-num" role="cell" data-peak={g.peak > 0 && wage === g.peak}>
                    {fmtMoney(wage)}
                  </div>
                  <div className="par-num" role="cell">{r.compliance_score ?? "—"}</div>
                  <div role="cell"><span className="par-tag">Approved</span></div>
                  <div className="par-acts" role="cell">
                    <Link
                      className="par-act par-act-1"
                      to={`/roster?week=${r.week_start}&roster=${r.roster_id}`}
                      aria-label={`Open roster for ${title}`}
                    >
                      Open
                    </Link>
                    <button
                      type="button"
                      className="par-act par-act-2"
                      onClick={() => exportRoster(r)}
                      aria-label={`Export roster for ${title}`}
                    >
                      Export
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ))}

        {approved.length > 0 && (
          <div className="par-foot">
            <span>
              Showing {Math.min(visible, approved.length)} of {approved.length}{" "}
              {approved.length === 1 ? "roster" : "rosters"} — grouped by month, newest first
            </span>
            {approved.length > visible && (
              <button type="button" className="par-link" onClick={() => setVisible(approved.length)}>
                Show all {approved.length}
              </button>
            )}
          </div>
        )}
      </div>

      {versions.length > 0 && (
        <>
          <div className="par-section">
            <h2 className="par-h2">Version history <span>({versions.length})</span></h2>
            {versions.length > versionsVisible && (
              <button
                type="button"
                className="par-link"
                onClick={() => setVersionsVisible(versions.length)}
              >
                Show all versions
              </button>
            )}
          </div>
          <p className="par-intro">
            Kept for reference only — every generated run of a week, including the drafts that were
            replaced before the roster was approved.
          </p>

          <div className="par-table" role="table" aria-label="Version history">
            <div className="par-vrow par-colhead" role="row">
              <span role="columnheader">Version</span>
              <span role="columnheader">Week</span>
              <span role="columnheader">Hours</span>
              <span role="columnheader">Score</span>
              <span role="columnheader">State</span>
              <span role="columnheader" aria-label="Actions" />
            </div>

            {versions.slice(0, versionsVisible).map((r) => {
              const state = versionState(r);
              const title = weekTitle(r.week_start);
              return (
                <div className="par-vrow par-vdata" role="row" key={r.roster_id}>
                  <div className="par-version" role="cell">{r.version || "—"}</div>
                  <div className="par-vweek" role="cell" style={{ minWidth: 0 }}>{title}</div>
                  <div className="par-vnum" role="cell">{fmtHours(r.total_hours)}</div>
                  <div className="par-vnum" role="cell">{r.compliance_score ?? "—"}</div>
                  <div className="par-vstate" role="cell" data-on={state.on}>{state.text}</div>
                  <div className="par-acts" role="cell">
                    <Link
                      className="par-act par-act-1"
                      to={`/roster?week=${r.week_start}&roster=${r.roster_id}`}
                      aria-label={`Open ${r.version || "version"} for ${title}`}
                    >
                      Open
                    </Link>
                  </div>
                </div>
              );
            })}

            <div className="par-foot">
              <span>
                Showing {Math.min(versionsVisible, versions.length)} of {versions.length} versions
              </span>
            </div>
          </div>
        </>
      )}

      <p className="par-note">
        A week appears in the list above once it has been <strong>approved and its week has
        ended</strong>. Everything else that was generated for that week stays in{" "}
        <strong>version history</strong> — superseded drafts and hand-edited runs — so the record of
        what was tried remains readable. <strong>These rosters are settled</strong>: opening one shows
        what was worked, and nothing here changes it. The amber wage figure is simply the{" "}
        <strong>highest in its month</strong>, not a problem.
      </p>
    </div>
  );
}
