import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Calendar, Download, Printer, Search } from "lucide-react";

import { api, errorMessage, fmtHours, fmtMoney } from "@/lib/api";

/**
 * Hours and wages — payroll report (handoff: Hours and wages).
 *
 * Filter band, stats band, one wide per-person table. Read-only: the page
 * creates nothing. Styling is the handoff's palette, scoped to .hw-* in
 * index.css.
 *
 * The numbers all come from GET /reports/hours, which builds them from
 * approved rosters only — drafts are excluded at the query level, not here.
 * The cost formula stays server-side so screen, CSV and print cannot
 * disagree.
 *
 * DEVIATIONS
 *
 * 1. Rows are a CSS grid with table roles rather than a real <table>. The
 *    handoff specifies both a real table and minmax() column tracks, and
 *    those cannot both hold — a table cannot express minmax. Grid plus
 *    role="table"/"row"/"cell" gives assistive tech the same structure and
 *    matches the five sibling pages already built this way.
 *
 * 2. Clicking a row opens a summary rather than a week-by-week breakdown.
 *    The report returns per-period totals and the names of any short weeks;
 *    it does not return per-week rows, so a weekly table would have to be
 *    invented. The drawer shows what the API actually knows, including
 *    which weeks were short.
 *
 * 3. No separate breaks column. When breaks are unpaid the handoff has
 *    ON FLOOR and PAID HOURS diverge, and the difference is the break time.
 */

const iso = (d) => d.toISOString().slice(0, 10);

/** Monday of the week containing `d`. Weeks run Mon–Sun everywhere else. */
function mondayOf(d) {
  const out = new Date(d);
  out.setDate(out.getDate() - ((out.getDay() + 6) % 7));
  return out;
}

function presetRange(key) {
  const today = new Date();
  if (key === "this-week") {
    const from = mondayOf(today);
    const to = new Date(from); to.setDate(to.getDate() + 6);
    return [iso(from), iso(to)];
  }
  if (key === "last-week") {
    const from = mondayOf(today); from.setDate(from.getDate() - 7);
    const to = new Date(from); to.setDate(to.getDate() + 6);
    return [iso(from), iso(to)];
  }
  if (key === "this-month") {
    const from = new Date(today.getFullYear(), today.getMonth(), 1);
    const to = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    return [iso(from), iso(to)];
  }
  const from = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const to = new Date(today.getFullYear(), today.getMonth(), 0);
  return [iso(from), iso(to)];
}

const PRESETS = [
  ["this-week", "This week"],
  ["last-week", "Last week"],
  ["this-month", "This month"],
  ["last-month", "Last month"],
];

const SORT_KEY = "roster_hours_sort";
const PAGE = 10;

const fmtRangeDay = (isoDate) => {
  const d = new Date(`${isoDate}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? isoDate
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

/** Zero reads as an em dash — "0h" invites the reader to wonder why. */
const orDash = (value, format) =>
  value ? format(value) : <span className="hw-zero">—</span>;

export default function HoursReport() {
  const [preset, setPreset] = useState("last-month");
  const [[start, end], setRange] = useState(() => presetRange("last-month"));
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState(() => localStorage.getItem(SORT_KEY) || "az");
  const [visible, setVisible] = useState(PAGE);
  const [detailFor, setDetailFor] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 150);
    return () => clearTimeout(t);
  }, [query]);

  const choose = (key) => { setPreset(key); setRange(presetRange(key)); setVisible(PAGE); };

  /** An explicit range and a preset are mutually exclusive. */
  const setEdge = (which, value) => {
    if (!value) return;
    setPreset("");
    setRange(which === "from" ? [value, end] : [start, value]);
    setVisible(PAGE);
  };

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const { data } = await api.get("/reports/hours", { params: { start, end } });
      setData(data);
    } catch (err) {
      toast.error(errorMessage(err, "Could not build the report"));
      setData(null);
    } finally { setBusy(false); }
  }, [start, end]);

  useEffect(() => { load(); }, [load]);

  const chooseSort = (key) => { setSort(key); localStorage.setItem(SORT_KEY, key); };

  const breaksPaid = data ? data.breaks_are_paid !== false : true;
  const rows = useMemo(() => data?.rows || [], [data]);

  const filtered = useMemo(() => {
    const q = debounced.trim().toLowerCase();
    const list = q
      ? rows.filter((r) =>
          String(r.name || "").toLowerCase().includes(q)
          || String(r.role || "").toLowerCase().includes(q))
      : [...rows];
    return sort === "cost"
      ? list.sort((a, b) => (b.cost || 0) - (a.cost || 0))
      : list.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  }, [rows, debounced, sort]);

  const totals = data?.totals;
  const wholeWeeks = data?.whole_weeks?.length || 0;

  const detail = detailFor ? rows.find((r) => r.employee_id === detailFor) : null;

  /**
   * CSV of the current scope with filters applied, plus the total row —
   * which always reflects the whole period, never the filtered subset.
   */
  const exportCsv = () => {
    if (!filtered.length) {
      toast.error("Nothing to export in this period");
      return;
    }
    const escape = (v) => {
      const str = String(v ?? "");
      return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
    };
    const header = [
      "Employee", "Role", "Days", "On floor", "Paid hours",
      "Paid holiday", "Sick days", "Cost", "Short weeks",
    ];
    const body = filtered.map((r) => [
      r.name, r.role || "", r.days_worked,
      Number(r.span_hours || 0).toFixed(2),
      Number(r.paid_hours || 0).toFixed(2),
      Number(r.paid_holiday_hours || 0).toFixed(2),
      r.sick_days || 0,
      Number(r.cost || 0).toFixed(2),
      (r.short_weeks || []).join(" / "),
    ]);
    const total = [
      `TOTAL · ${totals?.people ?? 0} people`, "", totals?.days_worked ?? 0,
      Number(totals?.span_hours || 0).toFixed(2),
      Number(totals?.paid_hours || 0).toFixed(2),
      Number(totals?.paid_holiday_hours || 0).toFixed(2),
      totals?.sick_days ?? 0,
      Number(totals?.cost || 0).toFixed(2),
      "",
    ];
    const csv = [
      [`Hours and wages ${start} to ${end}`],
      [breaksPaid ? "Breaks paid" : "Breaks unpaid"],
      [],
      header, ...body, total,
    ].map((r) => r.map(escape).join(",")).join("\n");

    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `hours-${start}-to-${end}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${filtered.length} ${filtered.length === 1 ? "person" : "people"}`);
  };

  const shown = filtered.slice(0, visible);

  return (
    <div className="hw-page">
      <header className="hw-head">
        <div>
          <div className="hw-eyebrow">REPORTS</div>
          <h1 className="hw-h1">Hours and wages</h1>
          <p className="hw-sub">
            Built from approved rosters only. A draft is a proposal, so counting one would bill for
            hours nobody was told to work.
          </p>
        </div>
        <div className="hw-actions">
          <button
            type="button"
            data-testid="btn-export-csv"
            className="hw-btn"
            disabled={!filtered.length}
            onClick={exportCsv}
          >
            <Download size={15} strokeWidth={1.6} /> Export CSV
          </button>
          <button type="button" className="hw-btn" onClick={() => window.print()}>
            <Printer size={15} strokeWidth={1.6} /> Print
          </button>
        </div>
      </header>

      <div className="hw-filters">
        <div className="hw-filters-row">
          <div className="hw-presets" role="group" aria-label="Period">
            {PRESETS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                data-testid={`period-${key}`}
                className="hw-preset"
                aria-pressed={preset === key}
                onClick={() => choose(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="hw-range">
            <Calendar size={14} color="#8c8c8c" strokeWidth={1.6} aria-hidden="true" />
            <input
              type="date"
              value={start}
              onChange={(e) => setEdge("from", e.target.value)}
              onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
              aria-label="Period from"
            />
            <span className="hw-range-arrow" aria-hidden="true">→</span>
            <input
              type="date"
              value={end}
              min={start}
              onChange={(e) => setEdge("to", e.target.value)}
              onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
              aria-label="Period to"
            />
            {!preset && (
              <button
                type="button"
                className="hw-range-clear"
                onClick={() => choose("last-month")}
                aria-label="Clear the date range"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {data && (
          <div className="hw-policy">
            <span className="hw-tag">{breaksPaid ? "Breaks paid" : "Breaks unpaid"}</span>
            <span className="hw-policy-text">
              {breaksPaid
                ? "Every hour on the floor is paid, breaks included."
                : "Paid hours exclude breaks — the gap between on floor and paid hours is break time. Change this in shop settings if your staff are paid through them."}
            </span>
          </div>
        )}
      </div>

      <div className="hw-stats">
        <div className="hw-stat">
          <div className="hw-stat-label">People</div>
          <div className="hw-stat-value">{totals?.people ?? 0}</div>
        </div>
        <div className="hw-stat">
          <div className="hw-stat-label">Paid hours</div>
          <div className="hw-stat-value">{fmtHours(totals?.paid_hours || 0)}</div>
        </div>
        <div className="hw-stat">
          <div className="hw-stat-label">Wage cost</div>
          <div className="hw-stat-value" data-accent="true">{fmtMoney(totals?.cost || 0)}</div>
        </div>
      </div>

      <div className="hw-section">
        <h2 className="hw-h2">
          By person <span>({rows.length})</span>
        </h2>
        <div className="hw-controls">
          <div className="hw-search">
            <Search size={14} color="#6f6f6f" strokeWidth={1.6} aria-hidden="true" />
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setVisible(PAGE); }}
              placeholder="Search name or role"
              aria-label="Search name or role"
            />
            {query && (
              <button
                type="button"
                className="hw-clear"
                onClick={() => setQuery("")}
                aria-label="Clear search"
              >
                <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                  <path d="M1.6 1.6l6.8 6.8M8.4 1.6L1.6 8.4" stroke="#c9c9c9"
                    strokeWidth="1.7" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
          <div className="hw-sorts" role="group" aria-label="Sort">
            <button type="button" className="hw-sort" aria-pressed={sort === "az"} onClick={() => chooseSort("az")}>
              A–Z
            </button>
            <button type="button" className="hw-sort" aria-pressed={sort === "cost"} onClick={() => chooseSort("cost")}>
              Cost
            </button>
          </div>
        </div>
      </div>

      <div className="hw-table" role="table" aria-label="Hours and wages by person">
        <div className="hw-row hw-colhead" role="row">
          <span role="columnheader">Employee</span>
          <span role="columnheader">Role</span>
          <span className="hw-num" role="columnheader">Days</span>
          <span className="hw-num hw-col-floor" role="columnheader">On floor</span>
          <span className="hw-num" role="columnheader">Paid hours</span>
          <span className="hw-num" role="columnheader">Paid holiday</span>
          <span className="hw-num" role="columnheader">Sick</span>
          <span className="hw-num" role="columnheader">Cost</span>
        </div>

        {busy && !data ? (
          <div className="hw-emptyrow">Building the report…</div>
        ) : rows.length === 0 ? (
          <div className="hw-emptyrow">
            No approved rosters in this period — drafts are not counted.
          </div>
        ) : filtered.length === 0 ? (
          <div className="hw-emptyrow">
            <span>No one matches “{debounced}”.</span>
            <button type="button" className="hw-link" onClick={() => setQuery("")}>Clear</button>
          </div>
        ) : shown.map((r) => {
          const short = r.short_weeks?.length || 0;
          return (
            <button
              type="button"
              className="hw-row hw-data"
              role="row"
              key={r.employee_id}
              data-testid={`hours-row-${r.employee_id}`}
              data-flagged={short > 0}
              onClick={() => setDetailFor(r.employee_id)}
              aria-label={`${r.name}, ${fmtHours(r.paid_hours)} paid, ${fmtMoney(r.cost)}${short ? `, ${short} short weeks` : ""}. Open breakdown.`}
            >
              <span className="hw-name-cell" role="cell">
                <span className="hw-name">{r.name}</span>
                {short > 0 && (
                  <span className="hw-flag">{short} short week{short === 1 ? "" : "s"}</span>
                )}
              </span>
              <span className="hw-role" role="cell">{r.role}</span>
              <span className="hw-num hw-val" role="cell">{orDash(r.days_worked, String)}</span>
              <span className="hw-num hw-val hw-col-floor" role="cell">{orDash(r.span_hours, fmtHours)}</span>
              <span className="hw-num hw-val" role="cell">{orDash(r.paid_hours, fmtHours)}</span>
              <span className="hw-num hw-val-quiet" role="cell">{orDash(r.paid_holiday_hours, fmtHours)}</span>
              <span className="hw-num hw-val-quiet" role="cell">{orDash(r.sick_days, String)}</span>
              <span className="hw-num hw-val" role="cell">{fmtMoney(r.cost)}</span>
            </button>
          );
        })}

        {rows.length > 0 && totals && (
          <div className="hw-row hw-total" role="row">
            <span className="hw-total-label" role="rowheader">
              Total · {totals.people} {totals.people === 1 ? "person" : "people"}
            </span>
            <span role="cell" />
            <span className="hw-num hw-val" role="cell">{totals.days_worked}</span>
            <span className="hw-num hw-val hw-col-floor" role="cell">{fmtHours(totals.span_hours)}</span>
            <span className="hw-num hw-val" role="cell">{fmtHours(totals.paid_hours)}</span>
            <span className="hw-num hw-val" role="cell">{fmtHours(totals.paid_holiday_hours)}</span>
            <span className="hw-num hw-val" role="cell">{orDash(totals.sick_days, String)}</span>
            <span className="hw-num hw-total-cost" role="cell">{fmtMoney(totals.cost)}</span>
          </div>
        )}

        {filtered.length > 0 && (
          <div className="hw-foot">
            <span>Showing {shown.length} of {filtered.length} people</span>
            {filtered.length > shown.length && (
              <button type="button" className="hw-link" onClick={() => setVisible(filtered.length)}>
                Show all {filtered.length}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="hw-notes">
        <p>
          <strong>Paid hours</strong> are what you are billed for — hours on the floor
          {breaksPaid ? " with breaks included" : ", breaks excluded"}.{" "}
          <strong>Paid holiday</strong> is booked leave paid at the normal rate; it sits outside paid
          hours, so it is listed separately and is not floor time.
        </p>
        <p>
          <strong>{wholeWeeks} whole week{wholeWeeks === 1 ? "" : "s"}</strong> in this period counted
          towards contract checks — part weeks at either end are reported but not checked. Where
          somebody was rostered under their contracted hours in a whole week, it is flagged in amber
          beside their name as a <strong>short week</strong>.
        </p>
      </div>

      {detail && (
        <div className="hw-scrim" onClick={() => setDetailFor(null)}>
          <div
            className="hw-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={`Breakdown for ${detail.name}`}
            onClick={(e) => e.stopPropagation()}
          >
            <h2>{detail.name}</h2>
            <p className="hw-drawer-role">
              {detail.role} · {fmtRangeDay(start)} → {fmtRangeDay(end)}
            </p>

            <div className="hw-dl">
              <div className="hw-dl-row">
                <span className="hw-dl-label">Days worked</span>
                <span className="hw-dl-value">{detail.days_worked || 0}</span>
              </div>
              <div className="hw-dl-row">
                <span className="hw-dl-label">Hours on floor</span>
                <span className="hw-dl-value">{fmtHours(detail.span_hours || 0)}</span>
              </div>
              {!breaksPaid && (
                <div className="hw-dl-row">
                  <span className="hw-dl-label">Unpaid breaks</span>
                  <span className="hw-dl-value">{fmtHours(detail.break_hours || 0)}</span>
                </div>
              )}
              <div className="hw-dl-row">
                <span className="hw-dl-label">Paid hours</span>
                <span className="hw-dl-value">{fmtHours(detail.paid_hours || 0)}</span>
              </div>
              <div className="hw-dl-row">
                <span className="hw-dl-label">Paid holiday</span>
                <span className="hw-dl-value">{fmtHours(detail.paid_holiday_hours || 0)}</span>
              </div>
              <div className="hw-dl-row">
                <span className="hw-dl-label">Sick days</span>
                <span className="hw-dl-value">{detail.sick_days || 0}</span>
              </div>
              {detail.hourly_rate ? (
                <div className="hw-dl-row">
                  <span className="hw-dl-label">Hourly rate</span>
                  <span className="hw-dl-value">{fmtMoney(detail.hourly_rate, { decimals: 2 })}</span>
                </div>
              ) : null}
              <div className="hw-dl-row">
                <span className="hw-dl-label">Cost</span>
                <span className="hw-dl-value" data-accent="true">{fmtMoney(detail.cost || 0)}</span>
              </div>
            </div>

            {detail.short_weeks?.length > 0 && (
              <div className="hw-drawer-flag">
                <strong>
                  {detail.short_weeks.length} short week{detail.short_weeks.length === 1 ? "" : "s"}
                </strong>{" "}
                — rostered under contracted hours in{" "}
                {detail.short_weeks.join(", ")}. Only whole weeks inside the period are checked, so a
                part week at either end never counts as short.
              </div>
            )}

            <div className="hw-drawer-acts">
              <button type="button" className="hw-link" onClick={() => setDetailFor(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
