import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, DAYS, DAY_LABELS, DAY_SHORT, errorMessage, shiftHours } from "@/lib/api";
import { toast } from "sonner";
import { AlertTriangle, ChevronDown, Plus, X } from "lucide-react";

/**
 * Fixed & recurring shifts — week grid (handoff 1b).
 *
 * The flat "Templates (4)" list became a weekly coverage grid: one row per
 * employee, seven day columns, a block per pinned shift, a headcount tally
 * and a banner naming the days nobody is pinned to. The add form collapsed
 * into the compose bar above the grid.
 *
 * The point of the grid is the gap. A list of templates can be read for a
 * while before you notice Sunday is missing; a column of dashes cannot.
 *
 * Styling lives in .fx-* under index.css and follows the handoff's own
 * palette rather than the Carbon tokens — see the comment on that block.
 *
 * The list view is kept, not replaced: below 900px the grid is unusable and
 * the page falls back to it automatically.
 */

const VIEW_KEY = "roster_fixed_shifts_view";

/**
 * Per-employee accents, assigned by index so a person keeps their colour
 * across renders. Three hues from the handoff, cycled for shops with more
 * than three staff.
 */
const ACCENTS = [
  { tile: "rgba(47,224,143,.18)", ink: "#2fe08f", from: "#2fe08f", to: "#1fc17c", text: "#07130d" },
  { tile: "rgba(120,180,255,.16)", ink: "#8fc3ff", from: "#6fb6ff", to: "#4c94e8", text: "#04121f" },
  { tile: "rgba(255,196,120,.16)", ink: "#ffc478", from: "#ffc478", to: "#e8a94f", text: "#1f1405" },
];
const accentFor = (index) => ACCENTS[index % ACCENTS.length];

const DAY_INITIALS = { mon: "M", tue: "T", wed: "W", thu: "T", fri: "F", sat: "S", sun: "S" };

/** "06:00" reads as "06"; "06:30" keeps its minutes. Saves width in a 54px cell. */
const edge = (time) => (typeof time === "string" && time.endsWith(":00") ? time.slice(0, 2) : time || "");

const fmtPinned = (hours) => `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h pinned`;
const fmtCellHours = (hours) => `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`;

/** "Saturday and Sunday", "Friday, Saturday and Sunday" — never "Saturday, Sunday". */
function listDays(dayKeys) {
  const names = dayKeys.map((d) => DAY_LABELS[d]);
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export default function FixedShifts() {
  const [items, setItems] = useState([]);
  const [emps, setEmps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // The chosen view is remembered per browser; the narrow override is not
  // stored, so widening the window restores the grid rather than stranding
  // someone in the list forever.
  const [view, setView] = useState(() => (localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid"));
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.innerWidth < 900);

  const [empId, setEmpId] = useState("");
  const [days, setDays] = useState([]);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 899px)");
    const sync = (e) => setNarrow(e.matches);
    setNarrow(mq.matches);
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  const chooseView = (next) => {
    setView(next);
    localStorage.setItem(VIEW_KEY, next);
  };

  const load = useCallback(async () => {
    try {
      const [f, e] = await Promise.all([api.get("/fixed-shifts"), api.get("/employees")]);
      setItems(f.data || []);
      setEmps(e.data || []);
    } catch (error) {
      toast.error(errorMessage(error, "Could not load fixed shifts"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  /**
   * Everything the grid draws, derived once per change.
   *
   * `primaryId` is the template covering the most days for that person; any
   * other template of theirs renders at 60% alpha, which is how the handoff
   * distinguishes a main pattern from a one-off (John's Saturday 06–11).
   */
  const { blocks, pinnedHours, coverage, uncovered } = useMemo(() => {
    const blocks = {};
    const pinnedHours = {};
    const coverage = Object.fromEntries(DAYS.map((d) => [d, 0]));
    const spread = {};

    items.forEach((t) => {
      const count = (t.days || []).length;
      const current = spread[t.employee_id];
      if (!current || count > current.count) spread[t.employee_id] = { id: t.fixed_id, count };
    });

    items.forEach((t) => {
      const hours = shiftHours(t.start, t.end);
      const primary = spread[t.employee_id]?.id === t.fixed_id;
      (t.days || []).forEach((day) => {
        if (!DAYS.includes(day)) return;
        blocks[t.employee_id] = blocks[t.employee_id] || {};
        blocks[t.employee_id][day] = {
          id: t.fixed_id,
          start: t.start,
          end: t.end,
          hours,
          primary,
          overnight: t.end < t.start,
        };
        pinnedHours[t.employee_id] = (pinnedHours[t.employee_id] || 0) + hours;
        coverage[day] += 1;
      });
    });

    return {
      blocks,
      pinnedHours,
      coverage,
      uncovered: DAYS.filter((d) => coverage[d] === 0),
    };
  }, [items]);

  const empName = (id) => emps.find((e) => e.employee_id === id)?.name || "—";
  const selected = emps.find((e) => e.employee_id === empId);
  const canPin = Boolean(empId) && days.length > 0 && Boolean(start) && Boolean(end) && start !== end;

  const toggleDay = (day) =>
    setDays((current) => (current.includes(day) ? current.filter((d) => d !== day) : [...current, day]));

  const resetDraft = () => { setEmpId(""); setDays([]); };

  /** Load a cell into the compose bar rather than opening a second editor. */
  const prefill = (nextEmpId, day, times) => {
    if (nextEmpId) setEmpId(nextEmpId);
    if (day) setDays([day]);
    if (times) { setStart(times.start); setEnd(times.end); }
    document.getElementById("fx-start")?.focus();
  };

  /**
   * Pinning replaces whatever already covers those days for that person,
   * rather than stacking a second template on top of the first.
   *
   * The API has POST and DELETE and no update, so a replacement is
   * composed: create the new template, rebuild any partly-overlapped one
   * from the days it keeps, then delete the original. Creating before
   * deleting is deliberate — if a later call fails the person ends up with
   * a duplicate, which is visible and fixable, rather than a hole in their
   * week that nobody notices.
   */
  const pin = async () => {
    if (!canPin || saving) return;
    setSaving(true);

    const clashes = items.filter(
      (t) => t.employee_id === empId && (t.days || []).some((d) => days.includes(d)),
    );

    try {
      await api.post("/fixed-shifts", { employee_id: empId, days, start, end });

      for (const t of clashes) {
        const kept = (t.days || []).filter((d) => !days.includes(d));
        if (kept.length > 0) {
          await api.post("/fixed-shifts", {
            employee_id: t.employee_id,
            days: kept,
            start: t.start,
            end: t.end,
          });
        }
        await api.delete(`/fixed-shifts/${t.fixed_id}`);
      }

      const replaced = clashes.reduce(
        (n, t) => n + (t.days || []).filter((d) => days.includes(d)).length, 0,
      );
      toast.success(
        replaced > 0
          ? `Pinned ${empName(empId)} to ${listDays(days)} — replaced ${replaced} existing ${replaced === 1 ? "day" : "days"}`
          : `Pinned ${empName(empId)} to ${listDays(days)}`,
      );
      resetDraft();
      await load();
    } catch (error) {
      toast.error(errorMessage(error, "Could not pin that shift"));
      await load();
    } finally {
      setSaving(false);
    }
  };

  /**
   * Remove one day from a template without touching the rest of it.
   *
   * A Monday-to-Friday pin is a single record, so dropping just Wednesday
   * means rebuilding it from the four days that remain. Same create-first
   * ordering, for the same reason.
   */
  const removeDay = async (id, day) => {
    const template = items.find((t) => t.fixed_id === id);
    if (!template) return;
    const kept = (template.days || []).filter((d) => d !== day);

    if (kept.length === 0) {
      if (!window.confirm(
        `${DAY_LABELS[day]} is the only day on this template — removing it clears the pinned shift entirely. Continue?`
      )) return;
    }

    try {
      if (kept.length > 0) {
        await api.post("/fixed-shifts", {
          employee_id: template.employee_id,
          days: kept,
          start: template.start,
          end: template.end,
        });
      }
      await api.delete(`/fixed-shifts/${id}`);
      toast.success(
        kept.length > 0
          ? `Removed ${DAY_LABELS[day]}`
          : "Pinned shift removed",
      );
      await load();
    } catch (error) {
      toast.error(errorMessage(error, "Could not remove that day"));
      await load();
    }
  };

  /**
   * Deleting removes the template, which means every day block belonging to
   * it — so the confirm says how many, otherwise clicking one cell silently
   * clears four.
   */
  const remove = async (id) => {
    const template = items.find((t) => t.fixed_id === id);
    const spanned = template?.days?.length || 0;
    const detail = spanned > 1
      ? `This template covers ${spanned} days. Remove all of them?`
      : "Remove this pinned shift?";
    if (!window.confirm(detail)) return;
    try {
      await api.delete(`/fixed-shifts/${id}`);
      toast.success("Pinned shift removed");
      await load();
    } catch (error) {
      toast.error(errorMessage(error, "Could not remove that shift"));
    }
  };

  const showList = narrow || view === "list";

  return (
    <div className="fx-page">
      <header className="fx-head">
        <div>
          <div className="fx-eyebrow">TEMPLATES · FIXED SHIFTS</div>
          <h1 className="fx-h1">Weekly coverage from pinned shifts</h1>
        </div>
        {!narrow && (
          <div className="fx-seg" role="group" aria-label="View">
            <button type="button" aria-pressed={view === "grid"} onClick={() => chooseView("grid")}>Week grid</button>
            <button type="button" aria-pressed={view === "list"} onClick={() => chooseView("list")}>List</button>
          </div>
        )}
      </header>

      {/* Compose bar ------------------------------------------------ */}
      <div className="fx-compose">
        <div className="fx-field">
          <span className="fx-avatar-sm" aria-hidden="true">{selected ? selected.name.charAt(0).toUpperCase() : "?"}</span>
          <span className="fx-select-label" data-filled={Boolean(selected)}>
            {selected ? selected.name : "Select employee"}
          </span>
          <ChevronDown size={11} color="rgba(255,255,255,.4)" aria-hidden="true" />
          <select
            data-testid="fs-emp"
            className="fx-select"
            aria-label="Employee"
            value={empId}
            onChange={(e) => setEmpId(e.target.value)}
          >
            <option value="">Select employee…</option>
            {emps.map((e) => (
              <option key={e.employee_id} value={e.employee_id}>{e.name} · {e.role}</option>
            ))}
          </select>
        </div>

        <div className="fx-days" role="group" aria-label="Days">
          {DAYS.map((day) => (
            <button
              type="button"
              key={day}
              className="fx-day"
              aria-pressed={days.includes(day)}
              aria-label={DAY_LABELS[day]}
              onClick={() => toggleDay(day)}
            >
              {DAY_INITIALS[day]}
            </button>
          ))}
        </div>

        <div className="fx-field fx-time">
          <input
            id="fx-start"
            type="time"
            step="900"
            aria-label="Start time"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
          />
          <span className="fx-time-arrow" aria-hidden="true">→</span>
          <input
            type="time"
            step="900"
            aria-label="End time"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
          />
        </div>

        <div className="fx-spacer" />

        <button type="button" data-testid="btn-add-fixed" className="fx-pin" disabled={!canPin || saving} onClick={pin}>
          <Plus size={13} strokeWidth={2.4} aria-hidden="true" />
          {saving ? "Pinning…" : "Pin shift"}
        </button>
      </div>

      {/* Grid / list ------------------------------------------------ */}
      <div className="fx-panel">
        {loading ? (
          <div className="fx-empty">Loading…</div>
        ) : emps.length === 0 ? (
          <div className="fx-empty">No employees yet — add staff before pinning shifts.</div>
        ) : showList ? (
          <div className="fx-list">
            {items.length === 0 ? (
              <div className="fx-empty">No fixed shifts yet — pin your first one above</div>
            ) : items.map((t) => (
              <div key={t.fixed_id} className="fx-listrow">
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{empName(t.employee_id)}</div>
                  <div className="fx-listrow-meta">
                    {(t.days || []).map((d) => DAY_SHORT[d]).join(", ")} · {t.start}–{t.end} · {fmtCellHours(shiftHours(t.start, t.end))}
                  </div>
                </div>
                <button type="button" className="fx-del" aria-label={`Remove ${empName(t.employee_id)}'s pinned shift`} onClick={() => remove(t.fixed_id)}>
                  <X size={15} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div role="grid" aria-label="Weekly coverage from pinned shifts">
            <div className="fx-row fx-row-head" role="row">
              <div className="fx-colhead" role="columnheader">EMPLOYEE</div>
              {DAYS.map((day) => (
                <div key={day} className="fx-dayhead" role="columnheader">
                  {DAY_SHORT[day]}
                </div>
              ))}
            </div>

            {emps.map((employee, index) => {
              const accent = accentFor(index);
              const row = blocks[employee.employee_id] || {};
              return (
                <div className="fx-row fx-row-emp" role="row" key={employee.employee_id}>
                  <div className="fx-name" role="rowheader">
                    <span className="fx-avatar" style={{ background: accent.tile, color: accent.ink }} aria-hidden="true">
                      {employee.name.charAt(0).toUpperCase()}
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <span className="fx-name-main" title={employee.name}>{employee.name}</span>
                      <span className="fx-name-sub">{fmtPinned(pinnedHours[employee.employee_id] || 0)}</span>
                    </span>
                  </div>

                  {DAYS.map((day) => {
                    const block = row[day];
                    if (!block) {
                      return (
                        <div className="fx-cellwrap" role="gridcell" key={day}>
                          <button
                            type="button"
                            className="fx-cell fx-cell-empty"
                            aria-label={`${employee.name}, ${DAY_LABELS[day]}, no pinned shift. Add one.`}
                            onClick={() => prefill(employee.employee_id, day)}
                          >
                            <Plus size={14} aria-hidden="true" />
                          </button>
                        </div>
                      );
                    }
                    const alpha = block.primary ? 1 : 0.6;
                    return (
                      <div className="fx-cellwrap" role="gridcell" key={day}>
                        <button
                          type="button"
                          className="fx-cell fx-cell-filled"
                          style={{
                            background: `linear-gradient(160deg, ${accent.from}, ${accent.to})`,
                            color: accent.text,
                            opacity: alpha,
                          }}
                          aria-label={`${employee.name}, ${DAY_LABELS[day]}, ${block.start} to ${block.end}. Edit.`}
                          onClick={() => prefill(employee.employee_id, day, { start: block.start, end: block.end })}
                        >
                          <span className="fx-cell-time">{edge(block.start)}–{edge(block.end)}</span>
                          <span className="fx-cell-hours">{fmtCellHours(block.hours)}</span>
                          {block.overnight && <span className="fx-cell-next" aria-hidden="true">+1d</span>}
                        </button>
                        <button
                          type="button"
                          className="fx-cell-del"
                          aria-label={`Remove ${employee.name}'s ${DAY_LABELS[day]} shift`}
                          title={`Remove ${DAY_LABELS[day]} only`}
                          onClick={() => removeDay(block.id, day)}
                        >
                          <X size={12} color={accent.text} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              );
            })}

            {items.length === 0 && (
              <div className="fx-empty">No fixed shifts yet — pin your first one above</div>
            )}

            <div className="fx-row fx-row-foot" role="row">
              <div className="fx-cover-label" role="rowheader">DAILY COVER</div>
              {DAYS.map((day) => (
                <div
                  key={day}
                  className="fx-cover"
                  role="gridcell"
                  data-level={coverage[day] === 0 ? "none" : coverage[day] >= 2 ? "ok" : "one"}
                  aria-label={`${DAY_LABELS[day]}: ${coverage[day]} pinned`}
                >
                  {coverage[day]}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* The alert carries coverage in words, so it never rests on colour. */}
      {!loading && !showList && uncovered.length > 0 && emps.length > 0 && (
        <div className="fx-alert" role="status">
          <AlertTriangle size={16} color="#ff8f8f" style={{ flex: "none" }} aria-hidden="true" />
          <span className="fx-alert-text">
            <strong>
              {listDays(uncovered)} {uncovered.length === 1 ? "has" : "have"} no pinned cover.
            </strong>{" "}
            The AI will fill {uncovered.length === 1 ? "it" : "them"} from availability — pin someone if it must be fixed.
          </span>
          <div className="fx-spacer" />
          <button type="button" onClick={() => prefill(null, uncovered[0])}>
            Pin {DAY_LABELS[uncovered[0]]}
          </button>
        </div>
      )}
    </div>
  );
}
