import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { toast } from "sonner";
import { Calendar, Download, Plus } from "lucide-react";

/**
 * Sick leave — HR report (handoff: Sick leave).
 *
 * Read-only reporting apart from Record illness. The scheduler never reads
 * this page and nothing here touches a roster. Styling is the handoff's
 * palette, scoped to .sk-* in index.css.
 *
 * TWO SOURCES, AND THEY DESCRIBE DIFFERENT THINGS
 *
 * The handoff assumes one `incidents` array carrying both hours and a paid
 * flag. The API has no such thing:
 *
 *   GET /reports/sick-leave    absence records from the holidays collection
 *                              — dates, day counts, a free-text label. This
 *                              is the incident log, and it updates the
 *                              moment an illness is recorded.
 *
 *   GET /reports/sick-balance  `sick` shifts read off APPROVED ROSTERS —
 *                              hours, entitlement, remaining, exhausted.
 *                              An illness recorded today does not appear
 *                              here until a roster covering it is approved.
 *
 * So the allowance figures lag the incident log, sometimes by weeks. The
 * per-person table is therefore built from the incident log and priced with
 * the balance's own conversion rate, rather than read straight off the
 * balance — otherwise recording an illness would leave the table unchanged
 * and the page would look broken.
 *
 * The paid/unpaid tag is DERIVED, because the log has no such field. It
 * applies the same rule as sick_balance.compute_sick_balance — charge
 * incidents oldest-first at that person's usual day length, paid until the
 * entitlement runs out, unpaid after. Where the backend has also seen the
 * illness the two agree; where it has not, this is the answer the backend
 * will reach once the roster is approved. The footer says so.
 *
 * Other deviations, all forced by the API:
 *   - Neither endpoint takes a year, so the year picker filters the log
 *     client-side. Allowance is only defined for the current leave year, so
 *     selecting an earlier year hides that table rather than showing figures
 *     that belong to a different period.
 *   - "certified" is not a field. Record illness writes the reason into the
 *     record's label, which is what the log displays.
 */

const REASONS = [
  { key: "Sick", hint: "Called in unwell." },
  { key: "Certified", hint: "Doctor's note on file." },
  { key: "Other", hint: "Anything else — add a note." },
];

const FILTERS = [
  { key: "used", label: "Used any" },
  { key: "gone", label: "Allowance gone" },
  { key: "all", label: "Everyone" },
];

const PAGE = 5;

const parseDay = (iso) => new Date(`${iso}T00:00:00`);

const fmtDay = (iso) => {
  const d = parseDay(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
};

const yearOf = (iso) => String(iso || "").slice(0, 4);

const fmtHours = (n) => `${Number(n || 0) % 1 === 0 ? Number(n) : Number(n).toFixed(2)}h`;
const fmtDays = (n) => `${Number(n || 0) % 1 === 0 ? Number(n) : Number(n).toFixed(1)}d`;

const daysBetween = (start, end) => {
  const a = parseDay(start);
  const b = parseDay(end || start);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return 1;
  return Math.max(1, Math.round((b - a) / 86400000) + 1);
};

/** The reason sits at the front of the label; anything after it is the note. */
function readReason(label) {
  const text = String(label || "").trim();
  const match = REASONS.find((r) => text.toLowerCase().startsWith(r.key.toLowerCase()));
  if (!match) return { reason: "Sick", note: text };
  return { reason: match.key, note: text.slice(match.key.length).replace(/^[\s—·-]+/, "") };
}

export default function SickReport() {
  const [log, setLog] = useState([]);
  const [balance, setBalance] = useState(null);
  const [emps, setEmps] = useState([]);
  const [loading, setLoading] = useState(true);

  const [year, setYear] = useState(null);
  const [filter, setFilter] = useState("used");
  const [personFilter, setPersonFilter] = useState(null);
  const [visibleUsed, setVisibleUsed] = useState(PAGE);
  const [visibleInc, setVisibleInc] = useState(PAGE);

  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      // The incident log comes from /holidays rather than
      // /reports/sick-leave: the report aggregates the same records but
      // drops their holiday_id, and without an id there is nothing to
      // delete by. /holidays is a superset — same records, ids intact.
      const [l, b, e] = await Promise.all([
        api.get("/holidays"),
        api.get("/reports/sick-balance").catch(() => ({ data: null })),
        api.get("/employees").catch(() => ({ data: [] })),
      ]);
      setLog(l.data || []);
      setBalance(b.data);
      setEmps(e.data || []);
    } catch (err) {
      toast.error(errorMessage(err, "Could not load the sick leave report"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const empMap = useMemo(
    () => Object.fromEntries(emps.map((e) => [e.employee_id, e])),
    [emps],
  );
  const balanceMap = useMemo(
    () => Object.fromEntries((balance?.rows || []).map((r) => [r.employee_id, r])),
    [balance],
  );

  const entitlementDays = balance?.entitlement_days ?? 5;
  const currentYear = balance?.leave_year || String(new Date().getFullYear());

  /**
   * Someone's usual day length — the rate that converts an entitlement in
   * days into hours. The balance knows it from real shifts; for anyone the
   * balance has not seen, fall back to their contract over five days, the
   * same assumption the booking form makes.
   */
  const dayHoursFor = useCallback((employeeId) => {
    const known = balanceMap[employeeId]?.usual_day_hours;
    if (known) return known;
    const contract = Number(empMap[employeeId]?.max_weekly_hours) || 40;
    return Math.round((contract / 5) * 100) / 100;
  }, [balanceMap, empMap]);

  /** Every sick record, newest first. */
  const allIncidents = useMemo(() => {
    const out = [];
    (Array.isArray(log) ? log : []).forEach((h) => {
      if (h.scope !== "sick" || !h.employee_id) return;
      const { reason, note } = readReason(h.label);
      const employee = empMap[h.employee_id];
      out.push({
        id: h.holiday_id,
        employee_id: h.employee_id,
        name: employee?.name || "Unknown",
        role: employee?.role || "",
        start: h.date,
        end: h.end_date || h.date,
        days: daysBetween(h.date, h.end_date || h.date),
        reason,
        note,
      });
    });
    return out.sort((a, b) => String(b.start).localeCompare(String(a.start)));
  }, [log, empMap]);

  const years = useMemo(() => {
    const set = new Set(allIncidents.map((i) => yearOf(i.start)).filter(Boolean));
    set.add(currentYear);
    return [...set].sort().reverse();
  }, [allIncidents, currentYear]);

  const activeYear = year || currentYear;
  const isCurrentYear = activeYear === currentYear;

  const incidents = useMemo(
    () => allIncidents.filter((i) => yearOf(i.start) === activeYear),
    [allIncidents, activeYear],
  );

  /**
   * Paid or unpaid, per incident: oldest first, charged at that person's
   * usual day length, paid until the entitlement is spent.
   */
  const payByIncident = useMemo(() => {
    const running = {};
    const out = {};
    [...incidents]
      .sort((a, b) => String(a.start).localeCompare(String(b.start)))
      .forEach((i) => {
        const dayHours = dayHoursFor(i.employee_id);
        const allowance = entitlementDays * dayHours;
        const before = running[i.employee_id] || 0;
        out[i.id] = before < allowance - 1e-6;
        running[i.employee_id] = before + i.days * dayHours;
      });
    return out;
  }, [incidents, dayHoursFor, entitlementDays]);

  /** Per-person allowance rows for the selected year. */
  const perPerson = useMemo(() => {
    const byEmployee = {};
    incidents.forEach((i) => {
      const row = byEmployee[i.employee_id] || {
        employee_id: i.employee_id,
        name: i.name,
        role: i.role,
        incidents: 0,
        days: 0,
        last: null,
        certified: false,
      };
      row.incidents += 1;
      row.days += i.days;
      if (!row.last || i.start > row.last) row.last = i.start;
      if (i.reason === "Certified") row.certified = true;
      byEmployee[i.employee_id] = row;
    });

    const rows = Object.values(byEmployee).map((row) => {
      const dayHours = dayHoursFor(row.employee_id);
      const allowance = Math.round(entitlementDays * dayHours * 100) / 100;
      const used = Math.round(row.days * dayHours * 100) / 100;
      const remaining = Math.max(0, Math.round((allowance - used) * 100) / 100);
      return {
        ...row,
        dayHours,
        allowanceHours: allowance,
        usedHours: used,
        remainingHours: remaining,
        remainingDays: dayHours ? Math.round((remaining / dayHours) * 10) / 10 : 0,
        unpaidDays: dayHours
          ? Math.max(0, Math.round(((used - allowance) / dayHours) * 10) / 10)
          : 0,
        exhausted: used >= allowance - 1e-6,
      };
    });

    // "Everyone" pads the list with people who have had no illness at all.
    if (filter === "all") {
      const seen = new Set(rows.map((r) => r.employee_id));
      emps
        .filter((e) => !e.past_staff && !seen.has(e.employee_id))
        .forEach((e) => {
          const dayHours = dayHoursFor(e.employee_id);
          const allowance = Math.round(entitlementDays * dayHours * 100) / 100;
          rows.push({
            employee_id: e.employee_id,
            name: e.name,
            role: e.role,
            incidents: 0, days: 0, last: null, certified: false,
            dayHours,
            allowanceHours: allowance,
            usedHours: 0,
            remainingHours: allowance,
            remainingDays: entitlementDays,
            unpaidDays: 0,
            exhausted: false,
          });
        });
    }

    return rows.sort((a, b) => b.usedHours - a.usedHours);
  }, [incidents, dayHoursFor, entitlementDays, filter, emps]);

  const goneCount = useMemo(
    () => perPerson.filter((r) => r.exhausted && r.incidents > 0).length,
    [perPerson],
  );
  const teamSize = balance?.team_size ?? emps.filter((e) => !e.past_staff).length;

  const usedRows = useMemo(() => {
    if (filter === "gone") return perPerson.filter((r) => r.exhausted && r.incidents > 0);
    if (filter === "all") return perPerson;
    return perPerson.filter((r) => r.incidents > 0);
  }, [perPerson, filter]);

  const stats = useMemo(() => ({
    incidents: incidents.length,
    days: incidents.reduce((n, i) => n + i.days, 0),
    affected: new Set(incidents.map((i) => i.employee_id)).size,
    unpaidDays: Math.round(perPerson.reduce((n, r) => n + r.unpaidDays, 0) * 10) / 10,
  }), [incidents, perPerson]);

  const shownIncidents = useMemo(
    () => (personFilter ? incidents.filter((i) => i.employee_id === personFilter) : incidents),
    [incidents, personFilter],
  );

  // --- record illness ------------------------------------------------

  const draftDays = draft ? daysBetween(draft.date, draft.end_date || draft.date) : 0;
  const draftDayHours = draft?.employee_id ? dayHoursFor(draft.employee_id) : 0;
  const draftRow = draft ? perPerson.find((r) => r.employee_id === draft.employee_id) : null;
  const draftAllowance = Math.round(entitlementDays * draftDayHours * 100) / 100;
  const draftUsed = draftRow?.usedHours || 0;
  const draftHours = Math.round(draftDays * draftDayHours * 100) / 100;
  const draftOver = Boolean(draft) && draftUsed + draftHours > draftAllowance + 1e-6;

  const canSave = Boolean(draft?.employee_id && draft?.date)
    && (!draft.end_date || draft.end_date >= draft.date);

  const save = async () => {
    if (!canSave || saving) return;
    setSaving(true);
    try {
      const label = draft.note?.trim()
        ? `${draft.reason} — ${draft.note.trim()}`
        : draft.reason;
      await api.post("/holidays", {
        scope: "sick",
        employee_id: draft.employee_id,
        date: draft.date,
        end_date: draft.end_date || undefined,
        label,
      });
      toast.success(
        `Recorded for ${empMap[draft.employee_id]?.name || "this employee"} — no roster was changed.`
      );
      setDraft(null);
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not record that illness"));
    } finally {
      setSaving(false);
    }
  };

  // --- export --------------------------------------------------------

  const exportCsv = () => {
    if (incidents.length === 0 && usedRows.length === 0) {
      toast.error(`Nothing to export for ${activeYear}`);
      return;
    }
    const escape = (v) => {
      const str = String(v ?? "");
      return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
    };
    const rows = [
      ["ALLOWANCE USED", activeYear],
      ["Name", "Role", "Incidents", "Last incident", "Hours used",
        "Allowance hours", "Days left", "Unpaid days"],
      ...usedRows.map((r) => [
        r.name, r.role || "", r.incidents, r.last || "",
        r.usedHours.toFixed(2), r.allowanceHours.toFixed(2),
        r.remainingDays, r.unpaidDays,
      ]),
      [],
      ["EVERY INCIDENT", activeYear],
      ["Date", "End date", "Name", "Role", "Reason", "Note", "Days", "Pay"],
      ...incidents.map((i) => [
        i.start, i.end || i.start, i.name, i.role || "",
        i.reason, i.note || "", i.days,
        payByIncident[i.id] ? "Paid" : "Unpaid",
      ]),
    ];
    const csv = rows.map((r) => r.map(escape).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `sick-leave-${activeYear}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${activeYear}`);
  };

  /**
   * Remove a mis-recorded illness. Deletes the underlying absence record,
   * which is what both this log and the allowance figures are built from,
   * so the whole page recomputes afterwards.
   */
  const removeIncident = async (incident) => {
    if (!incident.id) {
      toast.error("This record has no id and cannot be removed here");
      return;
    }
    const span = incident.days > 1
      ? `${incident.days} days from ${fmtDay(incident.start)}`
      : fmtDay(incident.start);
    if (!window.confirm(
      `Delete ${incident.name}'s illness — ${span}?\n\n` +
      "It is removed from the record entirely and their allowance is recalculated. " +
      "No roster is changed."
    )) return;
    try {
      await api.delete(`/holidays/${incident.id}`);
      toast.success("Illness record deleted");
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not delete that record"));
      await load();
    }
  };

  const showHistory = (employeeId) => {
    setPersonFilter(employeeId);
    setVisibleInc(PAGE);
    requestAnimationFrame(() => document
      .getElementById("sk-incidents")
      ?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  // --- render --------------------------------------------------------

  return (
    <div className="sk-page">
      <header className="sk-head">
        <div>
          <div className="sk-eyebrow">HR REPORT</div>
          <h1 className="sk-h1">Sick leave</h1>
          <p className="sk-sub">Never used by AI scheduling. Purely for HR visibility.</p>
        </div>
        <div className="sk-actions">
          <label className="sk-picker">
            <Calendar size={14} color="var(--t-muted)" strokeWidth={1.6} aria-hidden="true" />
            <select
              value={activeYear}
              onChange={(e) => {
                setYear(e.target.value);
                setVisibleUsed(PAGE);
                setVisibleInc(PAGE);
              }}
              aria-label="Year"
            >
              {years.map((y) => (
                <option key={y} value={y}>{y === currentYear ? `${y} to date` : y}</option>
              ))}
            </select>
          </label>
          <button type="button" className="sk-btn sk-btn-2" onClick={exportCsv}>
            <Download size={15} strokeWidth={1.6} /> Export
          </button>
          <button
            type="button"
            data-testid="btn-record-illness"
            className="sk-btn sk-btn-1"
            onClick={() => setDraft({
              employee_id: "",
              date: new Date().toISOString().slice(0, 10),
              end_date: "",
              reason: "Sick",
              note: "",
            })}
          >
            <Plus size={15} strokeWidth={2} /> Record illness
          </button>
        </div>
      </header>

      <div className="sk-stats">
        <div className="sk-stat">
          <div className="sk-stat-label">Total incidents</div>
          <div className="sk-stat-value">{stats.incidents}</div>
        </div>
        <div className="sk-stat">
          <div className="sk-stat-label">Total days</div>
          <div className="sk-stat-value">{stats.days}</div>
        </div>
        <div className="sk-stat">
          <div className="sk-stat-label">Employees affected</div>
          <div className="sk-stat-value">
            {stats.affected}<span className="sk-stat-of">/{teamSize}</span>
          </div>
        </div>
        <div className="sk-stat">
          <div className="sk-stat-label">Unpaid days</div>
          <div className="sk-stat-value" data-warn={stats.unpaidDays > 0}>{stats.unpaidDays}</div>
        </div>
      </div>

      <div className="sk-band">
        <div>
          <div className="sk-band-label">Paid sick entitlement</div>
          <p className="sk-band-body">
            {entitlementDays} day{entitlementDays === 1 ? "" : "s"} a year each, converted to hours
            from the shifts each person actually works. Illness past the allowance is still
            recorded — <strong>it is unpaid</strong>.
          </p>
        </div>
        <button
          type="button"
          className="sk-link"
          onClick={() => toast(
            "A day is worth that person's average worked shift, so a 4h Saturday and a 12h night are not charged the same."
          )}
        >
          How hours are worked out
        </button>
      </div>

      {isCurrentYear ? (
        <>
          <div className="sk-section">
            <h2 className="sk-h2">
              Allowance used <span>({usedRows.length} of {teamSize})</span>
            </h2>
            <div className="sk-pills" role="group" aria-label="Filter people">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className="sk-pill"
                  aria-pressed={filter === f.key}
                  onClick={() => { setFilter(f.key); setVisibleUsed(PAGE); }}
                >
                  {f.label}
                  {f.key === "gone" ? ` (${goneCount})` : f.key === "all" ? ` (${teamSize})` : ""}
                </button>
              ))}
            </div>
          </div>

          <div className="sk-table" role="table" aria-label="Allowance used">
            <div className="sk-row-used sk-colhead" role="row">
              <span role="columnheader">Who</span>
              <span role="columnheader">Incidents · last one</span>
              <span role="columnheader">Hours</span>
              <span role="columnheader">Left</span>
              <span role="columnheader" aria-label="Actions" />
            </div>

            {loading ? (
              <div className="sk-emptyrow">Loading…</div>
            ) : usedRows.length === 0 ? (
              <div className="sk-emptyrow">No sick leave recorded in {activeYear}.</div>
            ) : usedRows.slice(0, visibleUsed).map((r) => {
              const employee = empMap[r.employee_id];
              const minor = employee?.age != null && employee.age < 18;
              return (
                <div className="sk-row-used sk-data" role="row" key={r.employee_id}>
                  <div role="cell" style={{ minWidth: 0 }}>
                    <div className="sk-name">{r.name}</div>
                    <span className="sk-role">
                      {r.role || employee?.role || "—"}{minor ? " · under 18" : ""}
                    </span>
                  </div>
                  <div className="sk-meta" role="cell">
                    {r.incidents === 0 ? "None this year" : (
                      <>
                        {r.incidents} incident{r.incidents === 1 ? "" : "s"}
                        {r.last && <span className="sk-meta-date"> · {fmtDay(r.last)}</span>}
                        {r.certified && <span className="sk-meta-date"> · certified</span>}
                      </>
                    )}
                  </div>
                  <div className="sk-num" role="cell" data-warn={r.usedHours > r.allowanceHours + 1e-6}>
                    {fmtHours(r.usedHours)} of {fmtHours(r.allowanceHours)}
                  </div>
                  <div className="sk-num" role="cell" data-ok={!r.exhausted} data-warn={r.exhausted}>
                    {r.exhausted ? `${fmtDays(r.unpaidDays)} unpaid` : fmtDays(r.remainingDays)}
                  </div>
                  <div className="sk-acts" role="cell">
                    <button
                      type="button"
                      className="sk-link"
                      onClick={() => showHistory(r.employee_id)}
                      aria-label={`Show ${r.name}'s incident history`}
                    >
                      History
                    </button>
                  </div>
                </div>
              );
            })}

            {usedRows.length > 0 && (
              <div className="sk-foot">
                <span>
                  Showing {Math.min(visibleUsed, usedRows.length)} of {usedRows.length}
                  {filter === "used" ? " who have used any allowance" : ""}
                </span>
                {usedRows.length > visibleUsed && (
                  <button
                    type="button"
                    className="sk-link"
                    onClick={() => setVisibleUsed(usedRows.length)}
                  >
                    Show all {usedRows.length}
                  </button>
                )}
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="sk-section sk-section-plain" style={{ paddingBottom: 20 }}>
          <p className="sk-hint" style={{ maxWidth: 860 }}>
            Allowance is only calculated for the current leave year ({currentYear}), so those figures are
            hidden while viewing {activeYear}. The incident log below is complete for that year.
          </p>
        </div>
      )}

      <div className="sk-section" id="sk-incidents">
        <h2 className="sk-h2">
          {personFilter
            ? <>Incidents for {empMap[personFilter]?.name || "this person"} <span>({shownIncidents.length})</span></>
            : <>Every incident <span>({shownIncidents.length})</span></>}
        </h2>
        {personFilter ? (
          <button type="button" className="sk-link" onClick={() => setPersonFilter(null)}>
            Show everyone
          </button>
        ) : (
          <span className="sk-hint">Newest first</span>
        )}
      </div>

      <div className="sk-table" role="table" aria-label="Every incident">
        <div className="sk-row-inc sk-colhead" role="row">
          <span role="columnheader">Date</span>
          <span role="columnheader">Who</span>
          <span role="columnheader">Reason</span>
          <span role="columnheader">Days</span>
          <span role="columnheader">Pay</span>
          <span role="columnheader" aria-label="Actions" />
        </div>

        {loading ? (
          <div className="sk-emptyrow">Loading…</div>
        ) : shownIncidents.length === 0 ? (
          <div className="sk-emptyrow">
            {personFilter
              ? `Nothing recorded for ${empMap[personFilter]?.name || "this person"} in ${activeYear}.`
              : `No sick leave recorded in ${activeYear}.`}
          </div>
        ) : shownIncidents.slice(0, visibleInc).map((i) => {
          const paid = payByIncident[i.id];
          const employee = empMap[i.employee_id];
          return (
            <div className="sk-row-inc sk-data" role="row" key={i.id}>
              <div className="sk-date" role="cell">{fmtDay(i.start)}</div>
              <div role="cell" style={{ minWidth: 0 }}>
                <div className="sk-name-inc">{i.name}</div>
                <span className="sk-role">{i.role || employee?.role || "—"}</span>
              </div>
              <div className="sk-reason" role="cell">
                {i.reason}
                {i.note
                  ? ` · ${i.note}`
                  : i.reason === "Certified" ? " · doctor's note on file" : ""}
                {!paid && " · allowance already gone"}
              </div>
              <div className="sk-num" role="cell">{i.days}</div>
              <div role="cell">
                <span className="sk-tag" data-tone={paid ? "paid" : "unpaid"}>
                  {paid ? "Paid" : "Unpaid"}
                </span>
              </div>
              <div className="sk-acts" role="cell">
                <button
                  type="button"
                  className="sk-link sk-link-del"
                  onClick={() => removeIncident(i)}
                  aria-label={`Delete ${i.name}'s illness on ${fmtDay(i.start)}`}
                >
                  Delete
                </button>
              </div>
            </div>
          );
        })}

        {shownIncidents.length > 0 && (
          <div className="sk-foot">
            <span>
              Showing {Math.min(visibleInc, shownIncidents.length)} of {shownIncidents.length} incidents
              in {activeYear}
            </span>
            {shownIncidents.length > visibleInc && (
              <button
                type="button"
                className="sk-link"
                onClick={() => setVisibleInc(shownIncidents.length)}
              >
                Show all {shownIncidents.length}
              </button>
            )}
          </div>
        )}
      </div>

      <p className="sk-note">
        <strong>This page is for HR only</strong> — the scheduler never reads it, and recording an
        illness here does not change any roster. Paid allowance is {entitlementDays} days a year,
        converted to hours at <strong>each person's own average shift length</strong>, so a part-timer
        and a full-timer are charged what they actually lose. Illness past the allowance is still
        recorded and shows as <strong>unpaid</strong>. Pay status is worked out oldest-incident-first
        against that allowance; where an illness has not yet reached an approved roster this is the
        figure it will settle at once it does. Treat everything here as sensitive.
      </p>

      {draft && (
        <div className="sk-scrim" onClick={() => !saving && setDraft(null)}>
          <div
            className="sk-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Record illness"
            onClick={(e) => e.stopPropagation()}
          >
            <h2>Record illness</h2>
            <p className="sk-drawer-sub">
              Logged for HR only. This does not change any roster, and the scheduler will not see it.
            </p>

            <div className="sk-field">
              <label className="sk-label" htmlFor="sk-who">Who</label>
              <select
                id="sk-who"
                className="sk-input"
                value={draft.employee_id}
                onChange={(e) => setDraft({ ...draft, employee_id: e.target.value })}
              >
                <option value="">Select employee…</option>
                {emps.filter((e) => !e.past_staff).map((e) => (
                  <option key={e.employee_id} value={e.employee_id}>{e.name} · {e.role}</option>
                ))}
              </select>
            </div>

            <div className="sk-field sk-two">
              <div>
                <label className="sk-label" htmlFor="sk-from">First day</label>
                <input
                  id="sk-from"
                  type="date"
                  className="sk-input"
                  value={draft.date}
                  onChange={(e) => setDraft({ ...draft, date: e.target.value })}
                />
              </div>
              <div>
                <label className="sk-label" htmlFor="sk-to">Last day</label>
                <input
                  id="sk-to"
                  type="date"
                  className="sk-input"
                  value={draft.end_date}
                  min={draft.date}
                  onChange={(e) => setDraft({ ...draft, end_date: e.target.value })}
                />
              </div>
            </div>

            <div className="sk-field">
              <label className="sk-label" htmlFor="sk-reason">Reason</label>
              <select
                id="sk-reason"
                className="sk-input"
                value={draft.reason}
                onChange={(e) => setDraft({ ...draft, reason: e.target.value })}
              >
                {REASONS.map((r) => (
                  <option key={r.key} value={r.key}>{r.key} — {r.hint}</option>
                ))}
              </select>
            </div>

            <div className="sk-field">
              <label className="sk-label" htmlFor="sk-note">Note (optional)</label>
              <textarea
                id="sk-note"
                className="sk-textarea"
                rows={3}
                value={draft.note}
                onChange={(e) => setDraft({ ...draft, note: e.target.value })}
                placeholder="Anything HR should have on record."
              />
            </div>

            {draft.employee_id && (
              <div className="sk-computed" data-warn={draftOver}>
                {draftDays} day{draftDays === 1 ? "" : "s"} at <strong>{fmtHours(draftDayHours)}</strong>{" "}
                a day = <strong>{fmtHours(draftHours)}</strong>.{" "}
                {draftOver
                  ? <>That takes {empMap[draft.employee_id]?.name || "them"} past their{" "}
                      {fmtHours(draftAllowance)} allowance — the excess is recorded as unpaid.</>
                  : <>Inside their {fmtHours(draftAllowance)} allowance;{" "}
                      {fmtHours(Math.max(0, draftAllowance - draftUsed - draftHours))} would remain.</>}
              </div>
            )}

            <div className="sk-drawer-acts">
              <button
                type="button"
                data-testid="btn-save-illness"
                className="sk-btn sk-btn-1"
                disabled={!canSave || saving}
                onClick={save}
              >
                {saving ? "Recording…" : "Record illness"}
              </button>
              <button
                type="button"
                className="sk-link sk-link-mute"
                disabled={saving}
                onClick={() => setDraft(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
