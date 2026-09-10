import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, errorMessage, fmtMoney, CURRENCY, DAY_SHORT, DAY_LABELS, DAYS, shiftHours } from "@/lib/api";
import { toast } from "sonner";
import ContactImportPanel from "@/components/ContactImportPanel";
import { Plus, Search, ArrowLeft, ChevronDown, ChevronRight, GraduationCap, Sun, X, AlertTriangle } from "lucide-react";

/**
 * Employees — split view (handoff: Employees option B).
 *
 * Master/detail: the team on the left in reading order, one person's record
 * on the right. Selection lives in the URL (/employees/:employeeId) so the
 * pane is deep-linkable and back/forward work. Styling is the handoff's
 * palette, scoped to .esp-* in index.css.
 *
 * WHERE THIS DEPARTS FROM THE HANDOFF, AND WHY
 *
 * 1. Edit opens the existing full modal rather than turning the pane into
 *    five inline fields. The handoff edits role, rate, max hours, age and
 *    off days; the record also carries employment type, contract span and
 *    tolerance, availability windows, term-time caps, summer break, opening
 *    holiday and the active flag. Inline editing as drawn would leave
 *    fifteen fields with nowhere to go.
 *
 * 2. A shift carries no `source` field, so "fixed template" versus
 *    "AI-filled" is derived: a shift whose day, start and end match one of
 *    that person's fixed-shift templates is shown as fixed, anything else
 *    as solver-placed. That is the only signal available, and it can read
 *    wrong if a template was edited after the roster was generated — the
 *    caption says as much rather than implying certainty.
 *
 * 3. Leave is a fourth week-strip state. The handoff has fixed / AI / off,
 *    but a shift can be paid holiday, unpaid holiday or sick, and drawing
 *    those as a plain "Off" day would hide a booked absence.
 *
 * 4. The eyebrow reads "READING ORDER n OF N", not "SENIORITY n — FILLED
 *    FIRST". The list follows shop.employee_order, which the backend keeps
 *    deliberately separate from the ladder that decides who gets hours
 *    first. Printing "filled first" over it would be false.
 *
 * 5. BOOKED LEAVE shows the selected week only. Leave is stored as shifts
 *    on a roster, not as its own record, so anything further ahead would
 *    mean scanning every roster in the shop.
 *
 * 6. HISTORY is composed from the holiday balance — hours worked, accrued,
 *    booked, taken, and any manual adjustments — because no narrative
 *    history is recorded anywhere.
 */

const SORTS = [
  { key: "seniority", label: "Seniority" },
  { key: "managers", label: "Managers" },
  { key: "students", label: "Students" },
];

const PAGE_SIZE = 12;
const LOW_HOLIDAY_HOURS = 20;

/** Monday of the current week, as YYYY-MM-DD. */
function thisMonday() {
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

const fmtHours = (n) => `${Number.isInteger(n) ? n : Number(n).toFixed(1)}h`;
const edge = (t) => (typeof t === "string" && t.endsWith(":00") ? t.slice(0, 2) : t || "");

/** Paid holiday, unpaid holiday or sick — present but not working. */
const isLeave = (shift) => Boolean(shift.paid_holiday || shift.unpaid_holiday || shift.sick);

const leaveWord = (shift) =>
  shift.sick ? "Sick" : shift.unpaid_holiday ? "Unpaid" : "Holiday";

/** Tags for the identity block, at most four. */
function tagsFor(employee, balance, overBy) {
  const tags = [];
  if (employee.is_active === false) tags.push({ tone: "neutral", text: "Inactive" });
  if (overBy > 0) tags.push({ tone: "warn", text: `${fmtHours(overBy)} over max` });
  const left = balance?.available_hours;
  if (typeof left === "number" && left < LOW_HOLIDAY_HOURS) {
    tags.push({ tone: "warn", text: `${fmtHours(left)} holiday left` });
  }
  if (employee.age < 16) tags.push({ tone: "accent", text: "Under 16 · curfew" });
  if (employee.employment_type === "student" || (!employee.employment_type && employee.is_student)) {
    tags.push({ tone: "accent", text: "Student" });
  }
  if (employee.employment_type === "full_time_contract") {
    tags.push({ tone: "accent", text: `${employee.contract_span_hours || 42.5}h contract` });
  }
  return tags.slice(0, 4);
}
const emptyAvailability = {
  earliest_start: "",
  latest_finish: "",
  available_days: null,      // null = any day; a list = only those days
  preferred_shift: "any",
  can_work_overnight: true,
};

const emptySummerBreak = { start_date: "", end_date: "", max_weekly_hours: "" };

/**
 * How someone's hours are governed. The distinction matters because the two
 * numbers are measured differently:
 *
 *   full_time_contract — hours ON THE FLOOR, breaks included, and a fixed
 *       payslip whether they land on 41 or 42.5
 *   student / hourly   — PAID hours, with breaks excluded
 *
 * Conflating them is what made a 40h employee read as "1.8h over" for
 * taking the breaks they are entitled to.
 */
export const EMPLOYMENT_TYPES = [
  {
    key: "full_time_contract",
    label: "Full-time contract",
    hint: "Salaried. Must be on the floor 41–42.5h a week, breaks included. Pay is the same either way.",
  },
  {
    key: "student",
    label: "Student",
    hint: "Term-time hour cap, lifting during their summer break.",
  },
  {
    key: "hourly",
    label: "Hourly",
    hint: "Paid for what they work, up to their contracted hours.",
  },
];

const DEFAULT_CONTRACT_SPAN = 42.5;
const DEFAULT_CONTRACT_TOLERANCE = 1.5;
// Beyond this, "may fall short by" stops describing slack and starts
// switching the floor off. The tolerance exists to absorb the fact that a
// contract can rarely be hit exactly from whole shifts — half an hour here,
// an hour there. A whole shift's worth of it means a week can come in
// materially short and nothing will say so.
//
// Set to 23 on a 42.5h contract at the reference shop, the floor became
// 19.5h: somebody could work half their contract and the roster called it
// fine. It was visible on screen the whole time, in a sentence nobody had
// reason to re-read.
const TOLERANCE_WORTH_QUESTIONING = 4;

const emptyForm = {
  name: "", email: "", role: "Cashier", age: 22, hourly_rate: 15,
  max_weekly_hours: 40, preferred_days_off: [],
  is_active: true,
  availability: { ...emptyAvailability },
  employment_type: "hourly",
  contract_span_hours: "",
  contract_span_tolerance: "",
  is_student: false,
  term_time_max_hours: "",
  summer_break: { ...emptySummerBreak },
  opening_holiday_hours: "",
};

/** Fill in anything the server left off, so inputs are never uncontrolled. */
function toForm(employee) {
  return {
    ...emptyForm,
    ...employee,
    is_active: employee.is_active !== false,
    preferred_days_off: employee.preferred_days_off || [],
    availability: { ...emptyAvailability, ...(employee.availability || {}) },
    summer_break: { ...emptySummerBreak, ...(employee.summer_break || {}) },
    // Records written before employment_type existed still have is_student.
    employment_type: employee.employment_type
      || (employee.is_student ? "student" : "hourly"),
    contract_span_hours: employee.contract_span_hours ?? "",
    contract_span_tolerance: employee.contract_span_tolerance ?? "",
    term_time_max_hours: employee.term_time_max_hours ?? "",
    opening_holiday_hours: employee.opening_holiday_hours ?? "",
  };
}

/**
 * Turn the form back into what the API expects.
 *
 * Empty strings are the browser's way of saying "not set", but the backend
 * treats "" as a malformed time rather than an absent one, so blanks become
 * null here rather than being sent through.
 */
function toPayload(form) {
  const blankToNull = (v) => (v === "" || v === undefined ? null : v);
  // For REQUIRED numbers, where null would fail validation just as 0 does.
  // Leaving the key out lets the model's own default stand.
  const blankToUndefined = (v) =>
    (v === "" || v === null || v === undefined ? undefined : Number(v));
  const availability = {
    earliest_start: blankToNull(form.availability.earliest_start),
    latest_finish: blankToNull(form.availability.latest_finish),
    available_days: form.availability.available_days,
    preferred_shift: form.availability.preferred_shift || "any",
    can_work_overnight: form.availability.can_work_overnight !== false,
  };
  // If nothing was actually set, send no window at all rather than an object
  // full of nulls — it keeps stored records honest about what was configured.
  const hasAvailability =
    availability.earliest_start || availability.latest_finish ||
    availability.available_days || availability.preferred_shift !== "any" ||
    availability.can_work_overnight === false;

  const isStudent = form.employment_type === "student";
  const isContract = form.employment_type === "full_time_contract";

  const summer = isStudent && (form.summer_break.start_date || form.summer_break.end_date)
    ? {
        start_date: blankToNull(form.summer_break.start_date),
        end_date: blankToNull(form.summer_break.end_date),
        max_weekly_hours: form.summer_break.max_weekly_hours === ""
          ? null : Number(form.summer_break.max_weekly_hours),
      }
    : null;

  return {
    name: form.name,
    // An empty box means "no address", not an empty string — which would
    // fail validation and block the save on an optional field.
    email: (form.email || "").trim() || null,
    role: form.role,
    // AN EMPTY BOX IS NOT ZERO.
    //
    // `Number("")` is 0, and the API rejects 0 for these with "Input should
    // be greater than 0" — a message that names no field, so clearing the
    // weekly-hours box produced an error that looked like it came from
    // somewhere else entirely. Every optional number below already guarded
    // against "" and these three did not.
    //
    // Omitted rather than sent as 0 or null, so the documented default
    // applies (40h) instead of the save failing on a box the manager may
    // not even have meant to touch.
    age: blankToUndefined(form.age),
    hourly_rate: blankToUndefined(form.hourly_rate),
    max_weekly_hours: blankToUndefined(form.max_weekly_hours),
    preferred_days_off: form.preferred_days_off,
    departments: form.departments || ["Shop Floor"],
    is_active: form.is_active !== false,
    availability: hasAvailability ? availability : null,
    employment_type: form.employment_type,
    // Only meaningful for a salaried contract; sent as null otherwise so a
    // stored record never implies a band that does not apply.
    contract_span_hours: isContract && form.contract_span_hours !== ""
      ? Number(form.contract_span_hours) : null,
    contract_span_tolerance: isContract && form.contract_span_tolerance !== ""
      ? Number(form.contract_span_tolerance) : null,
    is_student: isStudent,
    term_time_max_hours: isStudent && form.term_time_max_hours !== ""
      ? Number(form.term_time_max_hours) : null,
    summer_break: summer,
    opening_holiday_hours: form.opening_holiday_hours === ""
      ? null : Number(form.opening_holiday_hours),
  };
}

/** One-line summary of an availability window, for the employee card. */
function availabilitySummary(employee) {
  const a = employee.availability;
  if (!a) return null;
  const parts = [];
  if (a.earliest_start) parts.push(`from ${a.earliest_start}`);
  if (a.latest_finish) parts.push(`until ${a.latest_finish}`);
  if (a.available_days?.length && a.available_days.length < 7) {
    parts.push(a.available_days.map((d) => DAY_SHORT[d]).join("/"));
  }
  if (a.preferred_shift && a.preferred_shift !== "any") parts.push(`${a.preferred_shift}s`);
  if (a.can_work_overnight === false) parts.push("no nights");
  return parts.length ? parts.join(" · ") : null;
}



export default function Employees() {
  const { employeeId } = useParams();
  const navigate = useNavigate();

  const [emps, setEmps] = useState([]);
  const [supervisory, setSupervisory] = useState([]);
  const [shop, setShop] = useState(null);
  const [balances, setBalances] = useState({});
  const [fixed, setFixed] = useState([]);
  const [roster, setRoster] = useState(null);
  const [loading, setLoading] = useState(true);

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("seniority");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [drag, setDrag] = useState(null);
  const [over, setOver] = useState(null);

  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [adjusting, setAdjusting] = useState(null);
  const listRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [e, b, h, f, r, sh] = await Promise.all([
        api.get("/employees"),
        api.get("/holiday-balance").catch(() => ({ data: [] })),
        api.get("/shop/hierarchy").catch(() => ({ data: {} })),
        api.get("/fixed-shifts").catch(() => ({ data: [] })),
        api.get("/rosters").catch(() => ({ data: [] })),
        api.get("/shop").catch(() => ({ data: null })),
      ]);
      setEmps(e.data || []);
      setSupervisory(h.data?.supervisory || []);
      setShop(sh.data || null);
      setFixed(f.data || []);
      const map = {};
      (b.data || []).forEach((x) => { map[x.employee_id] = x; });
      setBalances(map);
      const week = thisMonday();
      setRoster((r.data || []).find((x) => x.week_start === week) || null);
    } catch (err) {
      toast.error(errorMessage(err, "Could not load the team"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setAvail = (patch) => setForm((f) => ({ ...f, availability: { ...f.availability, ...patch } }));
  const setSummer = (patch) => setForm((f) => ({ ...f, summer_break: { ...f.summer_break, ...patch } }));

  const isManager = useCallback((e) => supervisory.includes(e.role), [supervisory]);

  /** Reading-order position, captured before any sort or filter. */
  const positions = useMemo(() => {
    const m = {};
    emps.forEach((e, i) => { m[e.employee_id] = i + 1; });
    return m;
  }, [emps]);

  /** This week's shifts per person, from the roster covering today. */
  const weekShifts = useMemo(() => {
    const m = {};
    (roster?.shifts || []).forEach((s) => {
      (m[s.employee_id] = m[s.employee_id] || []).push(s);
    });
    return m;
  }, [roster]);

  /**
   * Fixed-template lookup: "empId|day|start|end" for every pinned template.
   * A roster shift matching one of these came from the template rather than
   * the solver — the only way to tell them apart, since shifts record no
   * source of their own.
   */
  const fixedKeys = useMemo(() => {
    const set = new Set();
    fixed.forEach((t) => {
      (t.days || []).forEach((d) => set.add(`${t.employee_id}|${d}|${t.start}|${t.end}`));
    });
    return set;
  }, [fixed]);

  const hoursThisWeek = useCallback(
    (id) => (weekShifts[id] || [])
      .filter((s) => !isLeave(s) && s.start && s.end)
      .reduce((sum, s) => sum + shiftHours(s.start, s.end), 0),
    [weekShifts],
  );

  const overByFor = useCallback(
    (e) => {
      if (!roster) return 0;
      const max = Number(e.max_weekly_hours) || 0;
      return max ? Math.max(0, hoursThisWeek(e.employee_id) - max) : 0;
    },
    [roster, hoursThisWeek],
  );

  // --- list ---------------------------------------------------------

  const filtered = useMemo(() => {
    let list = emps;
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((e) =>
      e.name.toLowerCase().includes(q) || (e.role || "").toLowerCase().includes(q));
    if (sort === "managers") list = list.filter(isManager);
    if (sort === "students") list = list.filter(
      (e) => e.employment_type === "student" || (!e.employment_type && e.is_student));
    return list;
  }, [emps, query, sort, isManager]);

  const groups = useMemo(() => {
    if (sort !== "seniority") return [{ key: "all", label: null, list: filtered }];
    return [
      { key: "managers", label: "Managers", list: filtered.filter(isManager) },
      { key: "team", label: "Team", list: filtered.filter((e) => !isManager(e)) },
    ].filter((g) => g.list.length > 0);
  }, [filtered, sort, isManager]);

  const flat = useMemo(() => groups.flatMap((g) => g.list), [groups]);
  const selected = useMemo(
    () => emps.find((e) => e.employee_id === employeeId) || null,
    [emps, employeeId],
  );

  // Land on somebody rather than an empty pane, and recover if the person
  // in the URL has been deleted or filtered away.
  useEffect(() => {
    if (loading || flat.length === 0) return;
    if (!employeeId || !emps.some((e) => e.employee_id === employeeId)) {
      navigate(`/employees/${flat[0].employee_id}`, { replace: true });
    }
  }, [loading, employeeId, emps, flat, navigate]);

  const select = (id) => navigate(`/employees/${id}`);

  /** Up and down move the selection, as specified. */
  const onListKey = (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const i = flat.findIndex((x) => x.employee_id === employeeId);
    const next = e.key === "ArrowDown"
      ? Math.min(flat.length - 1, i + 1)
      : Math.max(0, i - 1);
    if (flat[next]) select(flat[next].employee_id);
  };

  // --- mutations ----------------------------------------------------

  const submit = async (e) => {
    e.preventDefault();
    try {
      const payload = toPayload(form);
      if (modal === "edit") {
        await api.put(`/employees/${form.employee_id}`, payload);
        toast.success("Employee updated");
      } else {
        const created = await api.post("/employees", payload);
        toast.success("Employee added");
        if (created?.data?.employee_id) navigate(`/employees/${created.data.employee_id}`);
      }
      setModal(null); setForm(emptyForm); load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save employee"));
    }
  };

  const del = async (employee) => {
    if (!window.confirm(
      `Remove ${employee.name}? Past rosters are kept.\n\n` +
      "If they have left, switching them to Inactive in Edit is usually better — " +
      "it keeps their history readable and stops them being rostered."
    )) return;
    const i = flat.findIndex((x) => x.employee_id === employee.employee_id);
    const next = flat[i + 1] || flat[i - 1] || null;
    try {
      await api.delete(`/employees/${employee.employee_id}`);
      toast.success("Removed");
      if (next) navigate(`/employees/${next.employee_id}`, { replace: true });
      else navigate("/employees", { replace: true });
      load();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  /** Drag writes shop.employee_order — reading order, not the ladder. */
  const canDrag = sort === "seniority" && !query.trim();

  const drop = async (targetId) => {
    if (!canDrag || !drag || drag === targetId) { setDrag(null); setOver(null); return; }
    const ids = emps.map((e) => e.employee_id);
    const from = ids.indexOf(drag);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) { setDrag(null); setOver(null); return; }
    const next = [...emps];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    const previous = emps;
    setEmps(next); setDrag(null); setOver(null);
    try {
      await api.put("/shop", { employee_order: next.map((e) => e.employee_id) });
      toast.success("Reading order saved");
    } catch (err) {
      setEmps(previous);
      toast.error(errorMessage(err, "Could not save the order"));
    }
  };

  /**
   * Export the team as CSV, built in the browser. Exports what is on
   * screen: the search and the Managers/Students filter both apply, so
   * "export the students" is just filter-then-export.
   */
  const exportTeam = () => {
    const list = filtered.length ? filtered : emps;
    if (list.length === 0) {
      toast.error("Nobody to export");
      return;
    }

    const escape = (v) => {
      const str = String(v ?? "");
      return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
    };

    const rows = [[
      "Name", "Role", "Manager", "Status", "Hourly rate", "Max weekly hours",
      "Age", "Employment type", "Guaranteed days off",
      "Hours this week", "Holiday hours left",
    ]];

    list.forEach((e) => {
      const balance = balances[e.employee_id];
      const left = balance?.available_hours;
      rows.push([
        e.name,
        e.role || "",
        isManager(e) ? "Yes" : "No",
        e.is_active === false ? "Inactive" : "Active",
        Number(e.hourly_rate || 0).toFixed(2),
        e.max_weekly_hours ?? "",
        e.age ?? "",
        e.employment_type || (e.is_student ? "student" : ""),
        (e.preferred_days_off || []).map((d) => DAY_LABELS[d]).join(" / "),
        roster ? hoursThisWeek(e.employee_id).toFixed(1) : "",
        typeof left === "number" ? left.toFixed(1) : "",
      ]);
    });

    const csv = rows.map((r) => r.map(escape).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `employees-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${list.length} ${list.length === 1 ? "person" : "people"}`);
  };

  // --- detail pane --------------------------------------------------

  const detail = () => {
    if (!selected) return <div className="esp-empty">Nobody selected.</div>;

    const balance = balances[selected.employee_id];
    const worked = hoursThisWeek(selected.employee_id);
    const max = Number(selected.max_weekly_hours) || 0;
    const overBy = overByFor(selected);
    const left = balance?.available_hours;
    const tags = tagsFor(selected, balance, overBy);
    const mine = weekShifts[selected.employee_id] || [];
    const byDay = {};
    mine.forEach((s) => { byDay[s.day] = s; });
    const leaveDays = mine.filter(isLeave);

    return (
      <>
        <div className="esp-ident">
          <div style={{ minWidth: 0 }}>
            <div className="esp-ident-label">
              READING ORDER {positions[selected.employee_id]} OF {emps.length}
            </div>
            <h2 className="esp-name">{selected.name}</h2>
            {tags.length > 0 && (
              <div className="esp-tags">
                {tags.map((t) => (
                  <span key={t.text} className="esp-tag" data-tone={t.tone}>{t.text}</span>
                ))}
              </div>
            )}
          </div>
          <div className="esp-ident-acts">
            <button
              type="button"
              data-testid={`btn-edit-${selected.employee_id}`}
              className="esp-act esp-act-1"
              onClick={() => { setForm(toForm(selected)); setModal("edit"); }}
            >
              Edit
            </button>
            {balance && (
              <button type="button" className="esp-act esp-act-2"
                onClick={() => setAdjusting({ employee: selected, balance })}>
                Adjust holiday
              </button>
            )}
            <button type="button" className="esp-act esp-act-2" onClick={() => del(selected)}>
              Delete
            </button>
          </div>
        </div>

        <div className="esp-stats">
          <div className="esp-stat">
            <div className="esp-stat-label">Hourly rate</div>
            <div className="esp-stat-value">{fmtMoney(selected.hourly_rate, { decimals: 2 })}</div>
          </div>
          <div className="esp-stat">
            <div className="esp-stat-label">Max per week</div>
            <div className="esp-stat-value">{max ? `${max}h` : "—"}</div>
          </div>
          <div className="esp-stat">
            <div className="esp-stat-label">This week</div>
            <div className="esp-stat-value" data-tone={!roster ? "none" : overBy > 0 ? "warn" : "on"}>
              {roster ? fmtHours(worked) : "—"}
            </div>
          </div>
          <div className="esp-stat">
            <div className="esp-stat-label">Holiday left</div>
            <div
              className="esp-stat-value"
              data-tone={typeof left !== "number" ? "none" : left < LOW_HOLIDAY_HOURS ? "warn" : undefined}
            >
              {typeof left === "number" ? fmtHours(left) : "—"}
            </div>
          </div>
        </div>

        <div className="esp-band">
          <div className="esp-label">Week at a glance</div>
          {roster ? (
            <>
              <div className="esp-week" role="table" aria-label={`${selected.name}'s week`}>
                {DAYS.map((day) => {
                  const s = byDay[day];
                  const leave = s && isLeave(s);
                  const key = s && !leave
                    ? `${selected.employee_id}|${day}|${s.start}|${s.end}`
                    : null;
                  const kind = !s ? "off" : leave ? "leave" : fixedKeys.has(key) ? "fixed" : "ai";
                  const label = !s
                    ? `${DAY_LABELS[day]}, off`
                    : leave
                      ? `${DAY_LABELS[day]}, ${leaveWord(s).toLowerCase()}`
                      : `${DAY_LABELS[day]}, ${s.start} to ${s.end}, ${kind === "fixed" ? "fixed" : "solver-placed"}`;
                  return (
                    <div key={day} role="cell">
                      <div className="esp-day-label">{DAY_SHORT[day]}</div>
                      <div className="esp-block" data-kind={kind} aria-label={label} title={label}>
                        {!s ? (
                          <span className="esp-block-off">Off</span>
                        ) : leave ? (
                          <span className="esp-block-off">{leaveWord(s)}</span>
                        ) : (
                          <>
                            <span className="esp-block-time">{edge(s.start)}–{edge(s.end)}</span>
                            <span className="esp-block-hours">{fmtHours(shiftHours(s.start, s.end))}</span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="esp-caption">
                Bright green came from a fixed template, darker green was placed by the solver, an outline
                is a day off and a bordered block is booked leave. Fixed is matched on day and times, so a
                template edited after this roster was generated may read as solver-placed.
              </p>
            </>
          ) : (
            <p className="esp-caption">
              No roster exists for the week of {thisMonday()}, so there is nothing to show yet. Generate one
              from the Roster page and this strip fills in.
            </p>
          )}
        </div>

        <div className="esp-band esp-twoup">
          <div>
            <div className="esp-label">Guaranteed off days</div>
            <div className="esp-chips">
              {DAYS.map((d) => (
                <span
                  key={d}
                  className="esp-chip"
                  data-on={Boolean(selected.preferred_days_off?.includes(d))}
                >
                  {DAY_SHORT[d]}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="esp-label">Booked leave this week</div>
            {leaveDays.length > 0 ? (
              leaveDays.map((s) => (
                <div key={s.day} className="esp-leave">
                  {DAY_LABELS[s.day]} — {leaveWord(s)}
                </div>
              ))
            ) : (
              <div className="esp-leave-none">
                {roster ? "None booked this week." : "No roster for this week yet."}
              </div>
            )}
          </div>
        </div>

        <div className="esp-band">
          <div className="esp-label">History</div>
          <p className="esp-history">
            {balance ? (
              <>
                {selected.name} has worked <strong>{fmtHours(balance.hours_worked || 0)}</strong> on record,
                accruing <strong>{fmtHours(balance.accrued_hours || 0)}</strong> of holiday.{" "}
                <strong>{fmtHours(balance.used_hours || 0)}</strong> has been taken
                {balance.booked_hours ? <>, and <strong>{fmtHours(balance.booked_hours)}</strong> is booked</> : null}, leaving{" "}
                <strong>{fmtHours(balance.available_hours || 0)}</strong> available
                {balance.opening_hours ? <> on top of an opening balance of {fmtHours(balance.opening_hours)}</> : null}.
                {balance.adjustments?.length > 0 && (
                  <> {balance.adjustments.length} manual adjustment
                    {balance.adjustments.length === 1 ? " has" : "s have"} been made by hand.</>
                )}
              </>
            ) : (
              <>No holiday record for {selected.name} yet.</>
            )}
          </p>
        </div>
      </>
    );
  };

  const listItem = (e) => {
    const overBy = overByFor(e);
    const mark = overBy > 0
      ? { kind: "over", text: `+${fmtHours(overBy)}` }
      : e.age < 16
        ? { kind: "minor", text: "U16" }
        : { kind: "pos", text: positions[e.employee_id] };
    return (
      <button
        type="button"
        key={e.employee_id}
        role="option"
        aria-selected={e.employee_id === employeeId}
        className="esp-item"
        data-testid={`employee-card-${e.employee_id}`}
        data-dragging={drag === e.employee_id}
        data-dropbefore={over === e.employee_id && drag !== e.employee_id}
        draggable={canDrag}
        onDragStart={() => canDrag && setDrag(e.employee_id)}
        onDragOver={(ev) => { if (canDrag && drag) { ev.preventDefault(); setOver(e.employee_id); } }}
        onDragLeave={() => setOver((o) => (o === e.employee_id ? null : o))}
        onDrop={(ev) => { ev.preventDefault(); drop(e.employee_id); }}
        onDragEnd={() => { setDrag(null); setOver(null); }}
        onClick={() => select(e.employee_id)}
      >
        <span className="esp-item-main">
          <span className="esp-item-name">{e.name}</span>
          <span className="esp-item-sub">
            {e.role}{e.max_weekly_hours ? ` · ${e.max_weekly_hours}h` : ""}
          </span>
        </span>
        <span className="esp-mark" data-kind={mark.kind}>{mark.text}</span>
      </button>
    );
  };

  const shownCount = Math.min(visible, filtered.length);

  return (
    <div className="esp-page">
      <header className="esp-head">
        <div>
          <div className="esp-eyebrow">TEAM</div>
          <h1 className="esp-h1">Employees</h1>
          <p className="esp-sub">
            Pick a person on the left — everything about them opens beside it.
          </p>
        </div>
        <div className="esp-actions">
          <button
            type="button"
            className="esp-btn esp-btn-2"
            onClick={exportTeam}
          >
            Export
          </button>
          <button
            type="button"
            data-testid="btn-add-employee"
            className="esp-btn esp-btn-1"
            onClick={() => { setForm(emptyForm); setModal("new"); }}
          >
            <Plus size={15} strokeWidth={2} /> Add employee
          </button>
        </div>
      </header>

      {emps.length > 0 && (
        <div style={{ padding: "0 28px 20px" }}>
          <ContactImportPanel
            missingCount={emps.filter((e) => e.is_active !== false && !(e.email || "").trim()).length}
            total={emps.filter((e) => e.is_active !== false).length}
            onDone={load}
          />
        </div>
      )}

      <div className="esp-split">
        <div className="esp-left" data-hidden={Boolean(employeeId)}>
          <div className="esp-search">
            <Search size={14} color="#8c8c8c" strokeWidth={1.8} aria-hidden="true" />
            <input
              value={query}
              onChange={(ev) => setQuery(ev.target.value)}
              placeholder={`Search ${emps.length} ${emps.length === 1 ? "person" : "people"}`}
              aria-label="Search people"
            />
          </div>

          <div className="esp-pills" role="group" aria-label="Sort and filter">
            {SORTS.map((s) => (
              <button
                key={s.key}
                type="button"
                className="esp-pill"
                aria-pressed={sort === s.key}
                onClick={() => setSort(s.key)}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div role="listbox" aria-label="People" tabIndex={0} ref={listRef} onKeyDown={onListKey}>
            {loading ? (
              <div className="esp-empty">Loading…</div>
            ) : filtered.length === 0 ? (
              <div className="esp-empty">
                {emps.length === 0 ? "No employees yet." : "Nobody matches that."}
              </div>
            ) : (
              groups.map((g) => {
                const slice = g.list.slice(0, visible);
                if (slice.length === 0) return null;
                return (
                  <div key={g.key}>
                    {g.label && (
                      <div className="esp-grouphead">{g.label} ({g.list.length})</div>
                    )}
                    {slice.map(listItem)}
                  </div>
                );
              })
            )}
          </div>

          {filtered.length > shownCount && (
            <div className="esp-listfoot">
              <button type="button" className="esp-link" onClick={() => setVisible(emps.length)}>
                Show all {filtered.length}
              </button>
            </div>
          )}
        </div>

        <div className="esp-right" data-hidden={!employeeId}>
          {employeeId && (
            <div className="esp-back">
              <button type="button" className="esp-link" onClick={() => navigate("/employees")}>
                <ArrowLeft size={13} style={{ display: "inline", verticalAlign: "-2px" }} /> All people
              </button>
            </div>
          )}
          {loading ? <div className="esp-empty">Loading…</div> : detail()}
        </div>
      </div>

      <p className="esp-note">
        The list follows the shop's <strong>reading order</strong> — how the sheet is laid out. Dragging a
        person changes that order only; <strong>who gets hours first follows the job ladder</strong> and is
        set in shop settings. Amber marks something to act on: over max hours this week, or a holiday
        balance running low. <strong>Delete keeps past rosters</strong>; for someone who has left, Inactive
        in Edit is usually the better switch.
      </p>
      {modal && (
        <Modal onClose={() => setModal(null)}>
          <form onSubmit={submit} className="space-y-4">
            <h2 className="text-2xl font-light mb-4">
              {modal === "edit" ? "Edit" : "New"} employee
            </h2>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Name">
                <input data-testid="emp-name" required value={form.name}
                  onChange={(e) => set({ name: e.target.value })}
                  className="w-full px-3 py-2.5 rounded-lg" />
              </Field>
              {/* Not required: staff read from a spreadsheet arrive without
                  one, and demanding it here would block the manager from
                  correcting their pay. Dispatch names anyone it cannot
                  reach rather than pretending to send. */}
              <Field label="Email">
                <input data-testid="emp-email" type="email" value={form.email || ""}
                  onChange={(e) => set({ email: e.target.value })}
                  placeholder="Optional — needed to email their roster"
                  className="w-full px-3 py-2.5 rounded-lg" />
              </Field>
              <Field label="Role">
                <input data-testid="emp-role" list="role-suggestions" required value={form.role}
                  onChange={(e) => set({ role: e.target.value })}
                  className="w-full px-3 py-2.5 rounded-lg"
                  placeholder="Type any role (e.g. Barista, Cook)" />
                <datalist id="role-suggestions">
                  {(shop?.role_hierarchy?.length ? shop.role_hierarchy : shop?.roles || [])
                    .map((r) => <option key={r} value={r} />)}
                </datalist>
              </Field>
              <Field label="Age">
                <input data-testid="emp-age" type="number" min={13} max={80} required value={form.age}
                  onChange={(e) => set({ age: Number(e.target.value) })}
                  className="w-full px-3 py-2.5 rounded-lg font-mono" />
              </Field>
              <Field label={`Hourly rate (${CURRENCY})`}>
                <input data-testid="emp-rate" type="number" step="0.5" required value={form.hourly_rate}
                  onChange={(e) => set({ hourly_rate: Number(e.target.value) })}
                  className="w-full px-3 py-2.5 rounded-lg font-mono" />
              </Field>
              <Field label="Contracted weekly hours">
                <input data-testid="emp-max" type="number" min={1} max={168} step="0.5" required
                  value={form.max_weekly_hours}
                  onChange={(e) => set({ max_weekly_hours: Number(e.target.value) })}
                  className="w-full px-3 py-2.5 rounded-lg font-mono" />
              </Field>
            </div>
            <p className="text-[11px] text-white/40 -mt-1">
              Contracted hours are paid hours. Unpaid breaks sit on top, so a
              40h contract is rostered as roughly 44–45h of shift time.
            </p>

            <Field label="Preferred days off">
              <div className="flex gap-2 flex-wrap">
                {DAYS.map((d) => {
                  const on = form.preferred_days_off.includes(d);
                  return (
                    <button
                      type="button" key={d}
                      onClick={() => set({
                        preferred_days_off: on
                          ? form.preferred_days_off.filter((x) => x !== d)
                          : [...form.preferred_days_off, d],
                      })}
                      className={`px-3 py-1.5 rounded-full text-xs ${on ? "neon-btn" : "glass-solid text-white/70"}`}
                    >
                      {DAY_SHORT[d]}
                    </button>
                  );
                })}
              </div>
            </Field>

            {/* ---------------- Advanced availability ---------------- */}
            <Section
              title="Advanced options"
              subtitle="Availability limits and employment status"
              testId="section-advanced"
              badge={availabilitySummary({ availability: form.availability })}
            >
              <div className="grid grid-cols-2 gap-3">
                <Field label="Earliest start">
                  <input data-testid="avail-earliest" type="time"
                    value={form.availability.earliest_start || ""}
                    onChange={(e) => setAvail({ earliest_start: e.target.value })}
                    className="w-full px-3 py-2.5 rounded-lg font-mono" />
                </Field>
                <Field label="Latest finish">
                  <input data-testid="avail-latest" type="time"
                    value={form.availability.latest_finish || ""}
                    onChange={(e) => setAvail({ latest_finish: e.target.value })}
                    className="w-full px-3 py-2.5 rounded-lg font-mono" />
                </Field>
              </div>

              <Field label="Preferred shift">
                <select data-testid="avail-shift"
                  value={form.availability.preferred_shift || "any"}
                  onChange={(e) => setAvail({ preferred_shift: e.target.value })}
                  className="w-full px-3 py-2.5 rounded-lg">
                  <option value="any">Any</option>
                  <option value="morning">Morning</option>
                  <option value="afternoon">Afternoon</option>
                  <option value="evening">Evening</option>
                </select>
              </Field>
              <p className="text-[11px] text-white/40 -mt-2">
                A preference, not a limit — it is followed where possible but
                will not be allowed to leave the shop unattended.
              </p>

              <Field label="Days they can work at all">
                <div className="flex gap-2 flex-wrap">
                  {DAYS.map((d) => {
                    const days = form.availability.available_days;
                    const on = !days || days.includes(d);
                    return (
                      <button
                        type="button" key={d}
                        onClick={() => {
                          const current = days || [...DAYS];
                          const next = on
                            ? current.filter((x) => x !== d)
                            : [...current, d];
                          // Back to all seven means "no restriction", which is
                          // stored as null rather than a full list.
                          setAvail({
                            available_days: next.length === 7 ? null : next,
                          });
                        }}
                        className={`px-3 py-1.5 rounded-full text-xs ${on ? "neon-btn" : "glass-solid text-white/30 line-through"}`}
                      >
                        {DAY_SHORT[d]}
                      </button>
                    );
                  })}
                </div>
              </Field>
              <p className="text-[11px] text-white/40 -mt-2">
                Unlike preferred days off, a day switched off here is a hard
                no — they are never rostered on it.
              </p>

              <Toggle
                testId="avail-overnight"
                checked={form.availability.can_work_overnight !== false}
                onChange={(v) => setAvail({ can_work_overnight: v })}
                label="Can work overnight shifts"
              />

              <Toggle
                testId="emp-active"
                checked={form.is_active !== false}
                onChange={(v) => set({ is_active: v })}
                label="Active"
                hint="Turn off for leavers. They keep their history but are never rostered."
              />
            </Section>

            {/* ---------------- Employment ---------------- */}
            <Section
              title="Employment type"
              subtitle="How this person's hours are governed"
              testId="section-employment"
              icon={GraduationCap}
              badge={EMPLOYMENT_TYPES.find((t) => t.key === form.employment_type)?.label}
            >
              <div className="space-y-2">
                {EMPLOYMENT_TYPES.map((type) => (
                  <label key={type.key} className="flex items-start gap-2.5 cursor-pointer">
                    <input
                      type="radio"
                      name="employment_type"
                      data-testid={`emp-type-${type.key}`}
                      checked={form.employment_type === type.key}
                      onChange={() => set({ employment_type: type.key })}
                      className="mt-1 shrink-0"
                      style={{ minHeight: 0, accentColor: "var(--primary)" }}
                    />
                    <span className="min-w-0">
                      <span className="text-sm block">{type.label}</span>
                      <span className="text-[11px] block" style={{ color: "var(--ink-mute-2)" }}>
                        {type.hint}
                      </span>
                    </span>
                  </label>
                ))}
              </div>

              {form.employment_type === "full_time_contract" && (
                <div className="pt-3 border-t" style={{ borderColor: "var(--hairline-cool)" }}>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Contracted hours on the floor">
                      <input data-testid="emp-contract-span" type="number" min={1} max={168} step="0.5"
                        value={form.contract_span_hours}
                        onChange={(e) => set({ contract_span_hours: e.target.value })}
                        placeholder={`${DEFAULT_CONTRACT_SPAN}`}
                        className="w-full px-3 py-2.5 rounded-lg font-mono" />
                    </Field>
                    <Field label="May fall short by">
                      <input data-testid="emp-contract-tolerance" type="number" min={0} max={24} step="0.5"
                        value={form.contract_span_tolerance}
                        onChange={(e) => set({ contract_span_tolerance: e.target.value })}
                        placeholder={`${DEFAULT_CONTRACT_TOLERANCE}`}
                        className="w-full px-3 py-2.5 rounded-lg font-mono" />
                    </Field>
                  </div>
                  <p className="text-[11px] mt-2" style={{ color: "var(--ink-mute-2)" }}>
                    Clock in to clock out, breaks included — not paid hours. They
                    must land between{" "}
                    <span style={{ color: "var(--ink)" }}>
                      {(Number(form.contract_span_hours || DEFAULT_CONTRACT_SPAN)
                        - Number(form.contract_span_tolerance ?? DEFAULT_CONTRACT_TOLERANCE)).toFixed(1)}h
                      {" and "}
                      {Number(form.contract_span_hours || DEFAULT_CONTRACT_SPAN).toFixed(1)}h
                    </span>
                    . A week broken by holiday or sickness is allowed to come in under.
                  </p>

                  {/* A large tolerance does not look wrong — it looks like a
                      number in a box. Saying what it COSTS is the only way it
                      gets noticed, because the sentence above already showed
                      the band and was read past. */}
                  {Number(form.contract_span_tolerance || 0) > TOLERANCE_WORTH_QUESTIONING && (
                    <div className="status-warn p-3 mt-3 text-[11px]">
                      Falling short by up to{" "}
                      {Number(form.contract_span_tolerance).toFixed(1)}h is a
                      wide margin — roughly{" "}
                      {(Number(form.contract_span_tolerance) / 8).toFixed(1)} shifts.
                      A week as low as{" "}
                      {(Number(form.contract_span_hours || DEFAULT_CONTRACT_SPAN)
                        - Number(form.contract_span_tolerance)).toFixed(1)}h
                      {" "}will pass without a word, so you will not be told when
                      they are under their contract. Usually this should be an
                      hour or two.
                    </div>
                  )}
                </div>
              )}

              {form.employment_type === "student" && (
                <>
                  <Field label="Term-time maximum weekly hours">
                    <input data-testid="emp-term-hours" type="number" min={1} max={168} step="0.5"
                      value={form.term_time_max_hours}
                      onChange={(e) => set({ term_time_max_hours: e.target.value })}
                      placeholder={`Defaults to ${form.max_weekly_hours}h`}
                      className="w-full px-3 py-2.5 rounded-lg font-mono" />
                  </Field>

                  <div className="pt-2 border-t border-white/5">
                    <div className="text-[11px] text-white/60 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <Sun size={12} /> Summer break availability
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label="Break starts">
                        <input data-testid="summer-start" type="date"
                          value={form.summer_break.start_date || ""}
                          onChange={(e) => setSummer({ start_date: e.target.value })}
                          className="w-full px-3 py-2.5 rounded-lg font-mono" />
                      </Field>
                      <Field label="Break ends">
                        <input data-testid="summer-end" type="date"
                          value={form.summer_break.end_date || ""}
                          onChange={(e) => setSummer({ end_date: e.target.value })}
                          className="w-full px-3 py-2.5 rounded-lg font-mono" />
                      </Field>
                    </div>
                    <Field label="Maximum weekly hours during the break">
                      <input data-testid="summer-hours" type="number" min={1} max={168} step="0.5"
                        value={form.summer_break.max_weekly_hours}
                        onChange={(e) => setSummer({ max_weekly_hours: e.target.value })}
                        placeholder="e.g. 40"
                        className="w-full px-3 py-2.5 rounded-lg font-mono" />
                    </Field>
                    <p className="text-[11px] text-white/40">
                      Inside these dates the term-time cap lifts and this
                      figure applies instead.
                    </p>
                  </div>
                </>
              )}
            </Section>

            {/* ---------------- Holiday ---------------- */}
            <Section
              title="Holiday entitlement"
              subtitle="Balance carried in from your previous system"
              testId="section-holiday"
              badge={form.opening_holiday_hours !== "" ? `${form.opening_holiday_hours}h` : null}
            >
              <Field label="Opening holiday hours">
                <input data-testid="emp-opening-holiday" type="number" min={0} step="0.5"
                  value={form.opening_holiday_hours}
                  onChange={(e) => set({ opening_holiday_hours: e.target.value })}
                  placeholder="0"
                  className="w-full px-3 py-2.5 rounded-lg font-mono" />
              </Field>
              <p className="text-[11px] text-white/40">
                Set this once, when you first add someone. From then on the
                balance is earned from hours actually worked, at 12.07%.
                Later corrections belong in Adjust, which records a reason.
              </p>
            </Section>

            {form.age < 16 && (
              <div className="text-xs text-amber-400 flex items-center gap-2">
                <AlertTriangle size={12} />
                Under-16 curfew will apply: no shifts before 08:00 or after 19:00.
              </div>
            )}

            <button data-testid="btn-save-employee" className="neon-btn w-full py-3 rounded-full text-sm">
              Save
            </button>
          </form>
        </Modal>
      )}

      {adjusting && (
        <AdjustModal
          employee={adjusting.employee}
          balance={adjusting.balance}
          onClose={() => setAdjusting(null)}
          onSaved={() => { setAdjusting(null); load(); }}
        />
      )}
    </div>
  );
}

/**
 * Manual balance correction. Deliberately requires a reason: an entitlement
 * that changed without explanation is impossible to defend when the employee
 * asks about it.
 */
function AdjustModal({ employee, balance, onClose, onSaved }) {
  const [hours, setHours] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post(`/holiday-balance/${employee.employee_id}/adjust`, {
        hours: Number(hours), reason,
      });
      toast.success("Balance adjusted");
      onSaved();
    } catch (err) {
      toast.error(errorMessage(err, "Could not adjust balance"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <h2 className="text-2xl font-light">Adjust holiday</h2>
        <div className="text-sm text-white/60">{employee.name}</div>

        <div className="glass-solid rounded-xl p-4 space-y-1.5 text-xs">
          <Row label="Carried in" value={`${balance.opening_hours}h`} />
          <Row label="Earned from hours worked" value={`+${balance.accrued_hours}h`} />
          {balance.adjustment_hours !== 0 && (
            <Row label="Previous adjustments" value={`${balance.adjustment_hours > 0 ? "+" : ""}${balance.adjustment_hours}h`} />
          )}
          <Row label="Paid holiday taken" value={`−${balance.used_hours}h`} />
          {balance.booked_hours > 0 && (
            <Row label="Paid holiday booked" value={`−${balance.booked_hours}h`} />
          )}
          <div className="pt-1.5 border-t border-white/10">
            <Row label="Available" value={`${balance.available_hours}h`} strong />
          </div>
        </div>

        <Field label="Adjustment in hours (negative deducts)">
          <input data-testid="adjust-hours" type="number" step="0.5" required
            value={hours} onChange={(e) => setHours(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg font-mono" />
        </Field>
        <Field label="Reason">
          <input data-testid="adjust-reason" required minLength={3}
            value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Carried over from last holiday year"
            className="w-full px-3 py-2.5 rounded-lg" />
        </Field>

        <button disabled={saving} className="neon-btn w-full py-3 rounded-full text-sm disabled:opacity-50">
          {saving ? "Saving…" : "Save adjustment"}
        </button>
      </form>
    </Modal>
  );
}

const Row = ({ label, value, strong }) => (
  <div className="flex justify-between">
    <span className="text-white/50">{label}</span>
    <span className={`font-mono ${strong ? "text-cyan-400" : "text-white/80"}`}>{value}</span>
  </div>
);

const Field = ({ label, children }) => (
  <label className="block">
    <div className="text-[11px] text-white/50 mb-1">{label}</div>
    {children}
  </label>
);

/** A collapsible block of optional settings. */
function Section({ title, subtitle, badge, icon: Icon, testId, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-white/10 rounded-xl overflow-hidden">
      <button
        type="button"
        data-testid={testId}
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-white/5"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {Icon && <Icon size={14} className="text-white/50" />}
        <div className="flex-1 min-w-0">
          <div className="text-sm">{title}</div>
          <div className="text-[11px] text-white/40 truncate">{subtitle}</div>
        </div>
        {badge && !open && (
          <span className="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 shrink-0">
            {badge}
          </span>
        )}
      </button>
      {open && <div className="px-4 pb-4 pt-1 space-y-4">{children}</div>}
    </div>
  );
}

function Toggle({ checked, onChange, label, hint, testId }) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <input
        type="checkbox" data-testid={testId}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 w-4 h-4 shrink-0 accent-cyan-400"
      />
      <span className="min-w-0">
        <span className="text-sm block">{label}</span>
        {hint && <span className="text-[11px] text-white/40 block">{hint}</span>}
      </span>
    </label>
  );
}

function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="max-w-lg w-full my-8 bg-[#0A0B10] border border-white/10 rounded-3xl p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute top-4 right-4 text-white/40 hover:text-white z-10">
          <X size={16} />
        </button>
        {children}
      </div>
    </div>
  );
}
