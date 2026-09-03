import React, { useEffect, useState } from "react";
import { api, errorMessage, fmtMoney, roleClass, CURRENCY, DAY_SHORT, DAYS } from "@/lib/api";
import { toast } from "sonner";
import ContactImportPanel from "@/components/ContactImportPanel";
import {
  Plus, Pencil, Trash2, AlertTriangle, X, ChevronDown, ChevronRight,
  GraduationCap, Sun, Clock, UserX, Scale, Briefcase,
} from "lucide-react";

/**
 * An employee record has grown well beyond name-and-rate, so the form is
 * split into a always-visible core and three collapsible sections. The
 * sections are collapsed by default because most staff need none of them —
 * showing every field to everyone would bury the four that always matter.
 */

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
  const [emps, setEmps] = useState([]);
  const [shop, setShop] = useState(null);
  const [balances, setBalances] = useState({});
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [adjusting, setAdjusting] = useState(null);

  const load = async () => {
    const [e, s, b] = await Promise.all([
      api.get("/employees"),
      api.get("/shop"),
      api.get("/holiday-balance").catch(() => ({ data: [] })),
    ]);
    setEmps(e.data);
    setShop(s.data);
    const map = {};
    (b.data || []).forEach((x) => { map[x.employee_id] = x; });
    setBalances(map);
  };
  useEffect(() => { load(); }, []);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setAvail = (patch) =>
    setForm((f) => ({ ...f, availability: { ...f.availability, ...patch } }));
  const setSummer = (patch) =>
    setForm((f) => ({ ...f, summer_break: { ...f.summer_break, ...patch } }));

  const submit = async (e) => {
    e.preventDefault();
    try {
      const payload = toPayload(form);
      if (modal === "edit") {
        await api.put(`/employees/${form.employee_id}`, payload);
        toast.success("Employee updated");
      } else {
        await api.post("/employees", payload);
        toast.success("Employee added");
      }
      setModal(null); setForm(emptyForm); load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save employee"));
    }
  };

  const del = async (id) => {
    if (!window.confirm(
      "Remove this employee?\n\nIf they have left, consider switching them to " +
      "Inactive instead — that keeps their past rosters readable."
    )) return;
    try {
      await api.delete(`/employees/${id}`);
      toast.success("Removed");
      load();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <div className="max-w-7xl">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Team</div>
          <h1 className="text-4xl font-light">Employees</h1>
          <p className="text-xs text-white/40 mt-2">
            Listed in seniority order — the same order the roster fills hours.
          </p>
        </div>
        <button
          data-testid="btn-add-employee"
          onClick={() => { setForm(emptyForm); setModal("new"); }}
          className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2"
        >
          <Plus size={14} /> Add employee
        </button>
      </div>

      {/* Only shown once there is somebody to match against — on an empty
          shop it would be an upload with nothing to attach to. */}
      {emps.length > 0 && (
        <ContactImportPanel
          missingCount={emps.filter(
            (e) => e.is_active !== false && !(e.email || "").trim()
          ).length}
          total={emps.filter((e) => e.is_active !== false).length}
          onDone={load}
        />
      )}

      {emps.length === 0 ? (
        <div className="glass rounded-3xl p-12 text-center text-white/50">
          No employees yet. Add your first team member to start scheduling.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {emps.map((e) => {
            const inactive = e.is_active === false;
            const window = availabilitySummary(e);
            const balance = balances[e.employee_id];
            return (
              <div
                key={e.employee_id}
                data-testid={`employee-card-${e.employee_id}`}
                className={`glass rounded-2xl p-6 relative ${inactive ? "opacity-50" : ""}`}
              >
                <div className="min-w-0">
                  <div className="font-medium truncate">{e.name}</div>
                  <div className="text-[11px] truncate" style={{ color: "var(--ink-mute-2)" }}>
                    {e.email || "No email — cannot be sent their roster"}
                  </div>
                  <div className="mt-2 flex items-center gap-2 flex-wrap">
                    <span className={`text-[11px] px-2 py-0.5 rounded-md ${roleClass(e.role)}`}>{e.role}</span>
                    {inactive && <Tag tone="slate" icon={UserX}>Inactive</Tag>}
                    {(e.employment_type === "full_time_contract") && (
                      <Tag tone="violet" icon={Briefcase}>
                        {(e.contract_span_hours || 42.5)}h contract
                      </Tag>
                    )}
                    {(e.employment_type === "student" || (!e.employment_type && e.is_student)) && (
                      <Tag tone="violet" icon={GraduationCap}>Student</Tag>
                    )}
                    {e.age < 16 && <Tag tone="amber" icon={AlertTriangle}>Under 16</Tag>}
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 mt-4 text-xs">
                  <Stat label="Age" value={e.age} />
                  <Stat label="Rate" value={fmtMoney(e.hourly_rate, { decimals: 2 })} />
                  <Stat label="Max" value={`${e.max_weekly_hours}h`} />
                </div>

                {balance && (
                  <div className="mt-3 glass-solid rounded-lg px-3 py-2 flex items-center justify-between text-xs">
                    <span className="text-white/50">Holiday available</span>
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-cyan-400">
                        {balance.available_hours}h
                      </span>
                      <button
                        type="button"
                        title="Adjust balance"
                        onClick={() => setAdjusting({ employee: e, balance })}
                        className="text-white/40 hover:text-white"
                      >
                        <Scale size={12} />
                      </button>
                    </span>
                  </div>
                )}

                {window && (
                  <div className="mt-3 text-[11px] text-white/50 flex items-start gap-1.5">
                    <Clock size={11} className="mt-0.5 shrink-0" />
                    <span className="text-white/70">{window}</span>
                  </div>
                )}

                {e.preferred_days_off?.length > 0 && (
                  <div className="mt-2 text-[11px] text-white/50">
                    Off: <span className="text-white/70 font-mono">
                      {e.preferred_days_off.map((d) => DAY_SHORT[d]).join(", ")}
                    </span>
                  </div>
                )}

                <div className="flex gap-2 mt-4">
                  <button
                    data-testid={`btn-edit-${e.employee_id}`}
                    onClick={() => { setForm(toForm(e)); setModal("edit"); }}
                    className="flex-1 px-3 py-2 rounded-lg glass-solid text-xs flex items-center justify-center gap-1"
                  >
                    <Pencil size={12} /> Edit
                  </button>
                  <button
                    onClick={() => del(e.employee_id)}
                    className="px-3 py-2 rounded-lg text-red-400 hover:bg-red-500/10 text-xs"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

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

const Stat = ({ label, value }) => (
  <div className="glass-solid rounded-lg px-3 py-2">
    <div className="text-[10px] text-white/40 uppercase tracking-wider">{label}</div>
    <div className="font-mono text-white">{value}</div>
  </div>
);

const TONES = {
  amber: "bg-amber-500/10 border-amber-500/30 text-amber-400",
  violet: "bg-violet-500/10 border-violet-500/30 text-violet-300",
  slate: "bg-white/5 border-white/20 text-white/50",
};

const Tag = ({ tone, icon: Icon, children }) => (
  <span className={`text-[10px] px-2 py-0.5 rounded-md border flex items-center gap-1 ${TONES[tone]}`}>
    {Icon && <Icon size={10} />} {children}
  </span>
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
