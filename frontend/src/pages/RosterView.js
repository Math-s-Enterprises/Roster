import React, { useEffect, useMemo, useState } from "react";
import { api, errorMessage, refusalReasons, availabilityConflict, leaveConflict, DAY_LABELS, DAY_SHORT, DAYS, mondayOf, fmtHours, fmtMoney, roleClass, shiftHours, shiftPaidHours, dateForDay, fmtDayDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import RosterPrintSheet from "@/components/RosterPrintSheet";
import ShiftWarningModal from "@/components/ShiftWarningModal";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import confetti from "canvas-confetti";
import jsPDF from "jspdf";
import { Calendar, Wand2, Send, Check, Printer, AlertTriangle, RefreshCw, X, UserX, UserPlus, ChevronUp, ChevronDown, Pin, Unlock } from "lucide-react";

/** "Mon 7 – Sun 13 Sept" — the week itself, which is the page's title. */
function weekRangeLabel(weekStart) {
  const from = new Date(`${weekStart}T00:00:00`);
  const to = new Date(from);
  to.setDate(to.getDate() + 6);
  const day = (d) => d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
  const month = (d) => d.toLocaleDateString(undefined, { month: "short" });
  return from.getMonth() === to.getMonth()
    ? `${day(from)} – ${day(to)} ${month(to)}`
    : `${day(from)} ${month(from)} – ${day(to)} ${month(to)}`;
}

function fmtApproved(iso) {
  if (!iso) return "already approved";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "already approved";
  return d.toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
}

/**
 * Unsocial hours get their own fill. Derived rather than stored: no shift
 * carries a flag for this, and the threshold is the same one a manager
 * would use reading the grid — starts before 07:00 or finishes after 22:00,
 * including anything that runs past midnight.
 */
function isUnsocial(shift) {
  if (!shift?.start || !shift?.end) return false;
  if (shift.end < shift.start) return true;
  return shift.start < "07:00" || shift.end > "22:00";
}

export default function RosterView() {
  const { user } = useAuth();
  // Past Rosters links here as /roster?week=YYYY-MM-DD. That parameter was
  // never read, so opening an archived week always landed on the current
  // one. mondayOf normalises whatever date arrives to its Monday, so a link
  // pointing at any day of the week resolves to the right roster.
  const [searchParams, setSearchParams] = useSearchParams();
  const weekParam = searchParams.get("week");
  const rosterParam = searchParams.get("roster");
  const [week, setWeek] = useState(() => mondayOf(weekParam || undefined));

  // Handles arriving at a different week without the component remounting.
  useEffect(() => {
    if (!weekParam) return;
    const monday = mondayOf(weekParam);
    setWeek((current) => (current === monday ? current : monday));
  }, [weekParam]);

  /** Keep the URL honest so the week can be linked to and navigated back. */
  const chooseWeek = (value) => {
    const monday = mondayOf(value);
    setWeek(monday);
    // Drop any pinned version — it belongs to the week being left.
    setSearchParams({ week: monday }, { replace: true });
  };
  const [roster, setRoster] = useState(null);
  const [emps, setEmps] = useState([]);
  const [holidays, setHolidays] = useState([]);
  const [shop, setShop] = useState(null);
  const [department, setDepartment] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [rosters, setRosters] = useState([]);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState(null);
  const [editShift, setEditShift] = useState(null);
  const [dragging, setDragging] = useState(null);
  const [pendingApproval, setPendingApproval] = useState(null);
  const [suggesting, setSuggesting] = useState(null);
  // A refused change gets a dialog rather than a toast: it needs reading and
  // acting on, and a toast that has already faded is no help.
  const [refused, setRefused] = useState(null);
  const [shiftWarning, setShiftWarning] = useState(null);
  const [confirmUnapprove, setConfirmUnapprove] = useState(false);
  const [sickShift, setSickShift] = useState(null);
  const [extraOpen, setExtraOpen] = useState(false);
  // How many sheets of paper the printed rota may use, and whether the
  // chooser is open. Two separate things: closing the dialog must not reset
  // the choice, or the sheet re-renders at one page in the moment between
  // dismissing the dialog and the print job reading the DOM — silently
  // printing something other than what was asked for.
  const [printPages, setPrintPages] = useState(1);
  const [printOpen, setPrintOpen] = useState(false);
  // Which rules this week breaks, per person. Refetched after every save,
  // because the manager is editing while they read it — a cached answer is
  // wrong the moment they move a shift.
  const [audit, setAudit] = useState(null);
  const [breachFor, setBreachFor] = useState(null);
  const [forceOpen, setForceOpen] = useState(false);
  // How many drafts this week has been through. Counted from the
  // stored version rather than a local tally, so it survives a
  // reload and is honest about what actually happened.
  const attempts = Number(String(roster?.version || "v1.0")
    .replace(/^v\d+\./, "")) + 1 || 1;
  const [undoSick, setUndoSick] = useState(null);

  // Shell state for the tabbed layout. The tab survives a week change
  // on purpose: a manager checking "against the usual" across three
  // weeks should not have to reselect it every time.
  const [tab, setTab] = useState("attention");
  const [visiblePeople, setVisiblePeople] = useState(8);
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [highlight, setHighlight] = useState(null);

  const load = async () => {
    const [e, r, s, h] = await Promise.all([
      api.get("/employees"), api.get("/rosters"), api.get("/shop"), api.get("/holidays"),
    ]);
    setEmps(e.data); setRosters(r.data); setShop(s.data); setHolidays(h.data);
    // An explicit ?roster= wins over the week lookup. Past Rosters links a
    // specific version, and matching on week alone would open whichever
    // roster for that week came back first — usually the approved one,
    // which is precisely not the version that was clicked.
    const byId = rosterParam && r.data.find((x) => x.roster_id === rosterParam);
    const found = byId
      || r.data.find((x) => x.week_start === week && (x.department || null) === (department || null));
    setRoster(found || null);
  };
  useEffect(() => { load(); }, [week, department]);

  const totalRosters = rosters.length;
  const freeLimit = 4;
  const overLimit = false; // DEV: paywall disabled

  /**
   * Move a row up or down and remember it.
   *
   * Presentation only — it changes how the sheet reads, never who is
   * considered first for hours. That stays on the job ladder.
   *
   * Applied locally before the request so the row moves on the click rather
   * than after a round trip; a failure puts it back and says so.
   */
  const moveEmployee = async (employeeId, delta) => {
    const from = emps.findIndex((e) => e.employee_id === employeeId);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= emps.length) return;

    const next = [...emps];
    [next[from], next[to]] = [next[to], next[from]];
    const previous = emps;
    setEmps(next);

    try {
      await api.put("/shop", { employee_order: next.map((e) => e.employee_id) });
    } catch (err) {
      setEmps(previous);
      toast.error(errorMessage(err, "Could not save the new order"));
    }
  };

  const resetOrder = async () => {
    try {
      await api.put("/shop", { employee_order: [] });
      toast.success("Back to seniority order");
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not reset the order"));
    }
  };

  const customOrder = (shop?.employee_order || []).length > 0;

  // Mirrors the backend rule: a finished week is the record of what people
  // actually worked, so it stays closed. A week still running does not — that
  // is exactly when somebody calls in sick and the rest has to move.
  const weekHasEnded = useMemo(() => {
    const end = new Date(`${week}T00:00:00`);
    end.setDate(end.getDate() + 7);
    return end <= new Date(new Date().toDateString());
  }, [week]);

  // Hours the solver refused to fill, grouped by day. Left blank rather than
  // given to somebody unsuitable, so the day header is marked and the
  // manager decides.
  const gapsByDay = useMemo(() => {
    const map = {};
    (roster?.gaps || []).forEach((g) => {
      if (g.severity !== "uncovered") return;
      (map[g.day] = map[g.day] || []).push(g);
    });
    return map;
  }, [roster]);

  /**
   * Build a roster.
   *
   * `keepPinned` is the difference between Rebalance and Regenerate. Shifts
   * you changed by hand are pinned; rebalancing holds them and re-solves
   * everyone else around them, so a small correction does not cost you the
   * rest of your edits.
   *
   * `onlyDay` narrows it to one day. "Two people are off on Wednesday" does
   * not want the whole week rearranged — every other day that moves is
   * something you have to read and mostly undo. The other six days are held
   * exactly as they are, though their hours still count, so a change on
   * Wednesday cannot push somebody over their week.
   *
   * Regenerate (no pins, no day) also varies the shifts nobody has a settled
   * claim on, so pressing it twice offers genuinely different arrangements
   * without handing back somebody's regular opening.
   */
  const generate = async (keepPinned = false, onlyDay = null) => {
    setGenerating(true);
    try {
      const r = await api.post("/roster/generate", {
        week_start: week, department, keep_pinned: keepPinned,
        only_day: onlyDay,
      });
      setRoster(r.data);
      const held = (r.data.shifts || []).filter((s) => s.pinned).length;
      toast.success(
        onlyDay
          ? `${DAY_LABELS[onlyDay]} re-solved — the rest of the week is untouched`
          : keepPinned
            ? `Rebalanced around ${held} pinned shift${held === 1 ? "" : "s"}`
            : `Generated ${r.data.version} · coverage ${r.data.compliance_score}`,
      );
      load();
    } catch (err) {
      // An approved week is refused outright, and the manager has to unapprove
      // it first — that needs a dialog they act on, not a toast that fades.
      const detail = err.response?.data?.detail;
      if (err.response?.status === 409 && detail?.reasons) {
        setRefused(detail);
        return;
      }
      toast.error(errorMessage(err, "Could not generate the roster"));
    } finally { setGenerating(false); }
  };

  /**
   * Reopen an approved roster.
   *
   * Approving does two things — it makes the roster the schedule people work,
   * and it adds the week to what the scheduler learns this shop's habits
   * from. Reopening undoes both, so it is one deliberate action rather than
   * an "edit anyway" override.
   */
  const unapprove = async () => {
    try {
      await api.post(`/rosters/${roster.roster_id}/unapprove`);
      toast.success("Reopened — this week no longer counts towards learning");
      setConfirmUnapprove(false);
      load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (detail?.reasons) {
        setConfirmUnapprove(false);
        setRefused(detail);
        return;
      }
      toast.error(errorMessage(err, "Could not reopen the roster"));
    }
  };

  const pinnedCount = (roster?.shifts || []).filter((s) => s.pinned).length;

  /** Release a pin so the solver may move that person again. */
  const unpin = async (shift) => {
    const clean = (roster.shifts || []).map(
      ({ employee_id, day, start, end, paid_holiday, unpaid_holiday, sick, pinned }) => ({
        employee_id, day, start, end,
        paid_holiday: !!paid_holiday, unpaid_holiday: !!unpaid_holiday, sick: !!sick,
        pinned: shift.shift_id === undefined
          ? !!pinned
          : (employee_id === shift.employee_id && day === shift.day ? false : !!pinned),
      }),
    );
    try {
      const r = await api.put(`/rosters/${roster.roster_id}`, { shifts: clean });
      setRoster(r.data);
      toast.success("Unpinned — the solver can move this again");
      setEditShift(null);
    } catch (err) {
      toast.error(errorMessage(err, "Could not unpin that shift"));
    }
  };

  /**
   * Approve, refusing while the shop would be left unattended.
   *
   * The backend returns 409 when hours are uncovered. Rather than dead-end,
   * we ask — approving a week with known gaps is sometimes the right call,
   * but it should be a decision rather than a click that looked clean.
   */
  useEffect(() => {
    if (!roster?.roster_id) { setAudit(null); return; }
    api.get(`/rosters/${roster.roster_id}/audit`)
      .then((r) => setAudit(r.data))
      // A failed audit must not blank the grid. Worst case the names are not
      // highlighted and approval still refuses on the server, which is the
      // check that actually matters.
      .catch(() => setAudit(null));
  }, [roster?.roster_id, roster?.shifts]);

  /* RE-CHECK THE RULES, NOT THE ROSTER.
   *
   * The manager changes a contract, a custom rule or the opening hours in
   * another screen and comes straight back to the week they were working on.
   * Regenerate would answer the question and throw away every edit they have
   * made, which is why they stopped pressing it.
   *
   * So this refetches the roster and the audit and touches NO shifts. The
   * backend derives coverage, breaches, contracts and rule status on read
   * (§5), so everything on the page is re-evaluated against the rules as
   * they stand right now.
   *
   * `load()` is included because the shop and the employee list feed the
   * grid itself — changing somebody's name or hours has to show there too.
   */
  const [rechecking, setRechecking] = useState(false);
  const recheck = async () => {
    if (!roster?.roster_id) return;
    setRechecking(true);
    try {
      const [, a] = await Promise.all([
        load(),
        api.get(`/rosters/${roster.roster_id}/audit`),
      ]);
      setAudit(a.data);
    } catch {
      // A failed re-check must leave the page as it was rather than blanking
      // it. The manager can press it again; nothing has been lost.
    } finally {
      setRechecking(false);
    }
  };

  const breachesFor = (employeeId) =>
    (audit?.people || []).find((p) => p.employee_id === employeeId);

  // Live if the audit has answered, stored otherwise. `?? ` rather than `||`
  // on purpose: an audit that returns an EMPTY list means nobody is short,
  // and falling back to the stored list there would resurrect a warning the
  // manager has just fixed.
  const underContract = audit?.under_contract ?? roster?.under_contract ?? [];
  const inactiveRules = audit?.inactive_rules ?? [];

  const approve = async (acknowledgeGaps = false, force = null) => {
    try {
      const url = `/rosters/${roster.roster_id}/approve`
        + (acknowledgeGaps ? "?acknowledge_gaps=true" : "");
      const r = await api.post(url, force || undefined);
      if (!r.data.approved_with_gaps) {
        confetti({
          particleCount: 140, spread: 80, origin: { y: 0.4 },
          colors: ["#3ECF8E", "#4ADE9E", "#EDEDED"],
        });
      }
      toast.success(
        r.data.approved_with_gaps
          ? `Approved with ${r.data.approved_with_gaps} uncovered hour(s)`
          : "Roster approved",
      );
      load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      // Two different 409s land here. "Uncovered hours" is a plain sentence
      // and can be forced; a rival approved roster is structured and cannot.
      // Checked by shape, because rendering the object would crash the page.
      if (err.response?.status === 409 && typeof detail === "string") {
        setPendingApproval(detail);
        return;
      }
      // A week that breaks rules can still be approved, by somebody who
      // proves who they are. A week that breaks the HARD floor cannot, and
      // that refusal must not offer a password box — implying the right
      // credentials would help would be a lie.
      if (err.response?.status === 409 && detail?.needs_force) {
        setForceOpen(true);
        return;
      }
      if (detail?.reasons) {
        setRefused(detail);
        return;
      }
      toast.error(errorMessage(err, "Could not approve the roster"));
    }
  };

  const dispatch = async () => {
    setDispatching(true);
    try {
      const r = await api.post(`/roster/${roster.roster_id}/dispatch`);
      setDispatchResult(r.data);
      toast.success(`Sent ${r.data.sent.length} of ${r.data.total} emails`);
      confetti({ particleCount: 200, spread: 100, origin: { y: 0.6 }, colors: ["#00E5FF", "#7C4DFF"] });
    } catch (err) {
      toast.error("Dispatch failed");
    } finally { setDispatching(false); }
  };

  const empMap = useMemo(() => Object.fromEntries(emps.map((e) => [e.employee_id, e])), [emps]);

  const shiftsByDay = useMemo(() => {
    const m = {}; DAYS.forEach((d) => (m[d] = []));
    (roster?.shifts || []).forEach((s) => m[s.day]?.push(s));
    return m;
  }, [roster]);

  // Which cells the solver wants confirmed, keyed for O(1) lookup while
  // rendering the grid rather than scanning the list for every cell.
  const needsConfirming = useMemo(() => new Set(
    (roster?.confirmations || []).map((c) => `${c.employee_id}|${c.day}`)
  ), [roster]);

  // Leavers stay in the database so their past rosters remain readable, but
  // a permanently empty row in every future grid is just noise.
  const gridEmployees = useMemo(() => emps.filter(
    (e) => e.is_active !== false
      || (roster?.shifts || []).some((s) => s.employee_id === e.employee_id)
  ), [emps, roster]);

  const saveShift = async (payload, confirmed = false) => {
    if (payload && shiftHours(payload.start, payload.end) > 11) {
      toast.error("Shift exceeds 11h limit"); return;
    }
    const employee = payload && empMap[payload.employee_id];
    const warnings = payload && [
      leaveConflict(holidays, employee, roster.week_start, payload.day),
      availabilityConflict(employee, payload.day, payload.start, payload.end),
    ].filter(Boolean);
    if (warnings?.length && !confirmed) {
      setShiftWarning({
        warnings,
        confirmLabel: "Save shift anyway",
        action: () => saveShift(payload, true),
      });
      return;
    }
    const shifts = (roster.shifts || []).filter((s) => s.shift_id !== editShift.shift_id);
    if (payload) {
      const dup = shifts.find((s) => s.employee_id === payload.employee_id && s.day === payload.day);
      if (dup) { toast.error("Employee already has a shift that day"); return; }
      shifts.push(payload);
    }
    const clean = shifts.map(({ employee_id, day, start, end, paid_holiday, unpaid_holiday, sick }) => ({ employee_id, day, start, end, paid_holiday: !!paid_holiday, unpaid_holiday: !!unpaid_holiday, sick: !!sick }));
    try {
      const r = await api.put(`/rosters/${roster.roster_id}`, { shifts: clean });
      setRoster(r.data);
      setEditShift(null);
      toast.success(payload ? "Shift saved" : "Shift removed");
      // Things the edit is allowed to do but you probably want to know about
      // — over contract, outside someone's availability, an unusual shift.
      (r.data.edit_warnings || []).slice(0, 3).forEach((w) => toast.warning(w));
    } catch (err) {
      // errorMessage flattens a validation response into a sentence. Passing
      // err.response.data.detail straight through crashed the page: a 422
      // body is a LIST of error objects, and React cannot render those.
      const refusal = refusalReasons(err);
      if (refusal) setRefused(refusal);
      else toast.error(errorMessage(err, "Could not save the shift"));
    }
  };

  /**
   * Drop a shift on another cell. If that cell is taken, the two SWAP.
   *
   * It used to refuse with "that slot already has a shift", which was the
   * wrong answer to the commonest reason for dragging in the first place:
   * two people trading shifts. The manager then had to move one out to an
   * empty cell, move the other across, and move the first back — three drags
   * and an intermediate roster that broke the rules, to express one decision.
   *
   * A shift is identified here by (employee, day) rather than by shift_id.
   * Both work today — the server stamps a shift_id on every path that creates
   * one — so this is not fixing a bug. It is the pairing the rest of the
   * codebase already treats as a shift's identity: the validator refuses two
   * rows sharing one, and corrections.diff_roster keys on it. Using the same
   * identity here means the swap cannot produce a roster those two would
   * disagree about, and it does not depend on shift_id surviving a round trip
   * that strips it (`clean` below drops it before every PUT).
   */
  const moveShift = async (shift, toEmpId, toDay, confirmed = false) => {
    if (shift.employee_id === toEmpId && shift.day === toDay) return;

    const at = (s, employeeId, day) => s.employee_id === employeeId && s.day === day;
    const occupant = (roster.shifts || []).find(
      (s) => at(s, toEmpId, toDay) && !at(s, shift.employee_id, shift.day)
    );

    // Leave is not swappable for the same reason it is not draggable: the
    // holiday record lives outside the roster, so moving the cell would leave
    // the two disagreeing about which day somebody is actually off. The drop
    // handler already blocks landing ON leave; this covers being called any
    // other way.
    if (occupant && (occupant.paid_holiday || occupant.unpaid_holiday || occupant.sick)) {
      toast.error(`${empMap[toEmpId]?.name || "They"} are on leave that day`);
      return;
    }

    const moveWarnings = [
      leaveConflict(holidays, empMap[toEmpId], roster.week_start, toDay),
      availabilityConflict(empMap[toEmpId], toDay, shift.start, shift.end),
      occupant && leaveConflict(
        holidays, empMap[shift.employee_id], roster.week_start, shift.day,
      ),
      occupant && availabilityConflict(
        empMap[shift.employee_id], shift.day, occupant.start, occupant.end,
      ),
    ].filter(Boolean);
    if (moveWarnings.length && !confirmed) {
      setShiftWarning({
        warnings: moveWarnings,
        confirmLabel: occupant ? "Swap anyway" : "Move anyway",
        action: () => moveShift(shift, toEmpId, toDay, true),
      });
      return;
    }

    const shifts = (roster.shifts || []).map((s) => {
      if (at(s, shift.employee_id, shift.day)) {
        return { ...s, employee_id: toEmpId, day: toDay };
      }
      if (occupant && at(s, toEmpId, toDay)) {
        // The hours travel with the shift, not with the person: this is the
        // two of them trading shifts, so each works what the other had.
        return { ...s, employee_id: shift.employee_id, day: shift.day };
      }
      return s;
    });

    const clean = shifts.map(({ employee_id, day, start, end, paid_holiday, unpaid_holiday, sick }) => ({ employee_id, day, start, end, paid_holiday: !!paid_holiday, unpaid_holiday: !!unpaid_holiday, sick: !!sick }));
    try {
      const r = await api.put(`/rosters/${roster.roster_id}`, { shifts: clean });
      setRoster(r.data);
      toast.success(
        occupant
          ? `Swapped ${empMap[shift.employee_id]?.name || "them"} and ${empMap[toEmpId]?.name || "them"}`
          : "Shift moved"
      );
      // Warnings, not refusals — a swap can leave somebody short of their
      // rest gap, and the manager may know something the app does not. It is
      // approval that refuses (compliance.py), not the edit.
      (r.data.edit_warnings || []).slice(0, 3).forEach((w) => toast.warning(w));
    } catch (err) {
      const refusal = refusalReasons(err);
      if (refusal) setRefused(refusal);
      else toast.error(errorMessage(err, occupant ? "Could not swap those shifts" : "Could not move the shift"));
    }
  };

  const exportCSV = () => {
    const rows = [["Employee", "Role", "Department", "Day", "Date", "Start", "End", "Hours"]];
    (roster.shifts || []).forEach((s) => {
      const e = empMap[s.employee_id] || {};
      const d = dateForDay(roster.week_start, s.day);
      const label = s.paid_holiday ? "Holiday" : s.unpaid_holiday ? "N/A" : s.sick ? "Sick" : "";
      rows.push([
        e.name, e.role, (e.departments || []).join("/"), DAY_LABELS[s.day],
        d.toISOString().slice(0, 10),
        s.start || label, s.end || label,
        shiftPaidHours(s, !!shop?.breaks_are_paid).toFixed(1),
      ]);
    });
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `roster-${week}-${roster.version}.csv`;
    a.click();
  };

  const exportPDF = () => {
    const pdf = new jsPDF({ orientation: "landscape" });
    // Header
    pdf.setFillColor(15, 15, 20); pdf.rect(0, 0, 297, 22, "F");
    pdf.setTextColor(255, 255, 255); pdf.setFontSize(18);
    pdf.text(shop?.name || "Roster", 14, 13);
    pdf.setFontSize(10); pdf.setTextColor(180);
    pdf.text(`Week of ${roster.week_start} · ${roster.version}${roster.department ? " · " + roster.department : ""}`, 14, 19);
    pdf.setTextColor(0, 0, 0);
    // Column headers
    const colX = [14, 60, 95, 130, 165, 200, 235];
    let y = 32;
    pdf.setFontSize(9); pdf.setFont(undefined, "bold");
    ["Employee", "Role", "Day", "Date", "Start–End", "Hours"].forEach((h, i) => pdf.text(h, colX[i], y));
    pdf.setDrawColor(200); pdf.line(14, y + 2, 283, y + 2);
    y += 8; pdf.setFont(undefined, "normal");
    const sorted = [...(roster.shifts || [])].sort((a, b) => (DAYS.indexOf(a.day) - DAYS.indexOf(b.day)) || a.start.localeCompare(b.start));
    sorted.forEach((s) => {
      const e = empMap[s.employee_id] || {};
      const d = dateForDay(roster.week_start, s.day);
      const label = s.paid_holiday ? "Holiday" : s.unpaid_holiday ? "N/A" : s.sick ? "Sick" : "";
      pdf.text(String(e.name || "").slice(0, 24), colX[0], y);
      pdf.text(String(e.role || ""), colX[1], y);
      pdf.text(DAY_LABELS[s.day], colX[2], y);
      pdf.text(fmtDayDate(d), colX[3], y);
      pdf.text(s.start && s.end ? `${s.start} – ${s.end}` : label, colX[4], y);
      pdf.text(`${shiftPaidHours(s, !!shop?.breaks_are_paid).toFixed(1)}h`, colX[5], y);
      y += 6; if (y > 195) { pdf.addPage(); y = 20; }
    });
    // Footer
    pdf.setFontSize(8); pdf.setTextColor(120);
    pdf.text(`Compliance ${roster.compliance_score}/100 · Labour ${fmtMoney(roster.labor_cost)} · ${roster.total_hours}h total`, 14, 205);
    pdf.save(`roster-${week}-${roster.version}.pdf`);
  };

  if (emps.length === 0) {
    return (
      <div className="max-w-2xl card p-12 text-center">
        <Wand2 size={32} className="mx-auto mb-4" style={{ color: "var(--ink-mute-2)" }} />
        <h2 className="mb-2">No employees yet</h2>
        <p className="text-sm mb-5" style={{ color: "var(--ink-mute)" }}>
          Add your team before generating a roster.
        </p>
        <Link to="/employees" className="btn btn-primary">Add employees</Link>
      </div>
    );
  }

  // ---- findings, grouped the way the tab strip reads them ----------
  //
  // Every one of these comes from something already computed on this page:
  // the roster document, or the live audit. Nothing here is invented, and
  // nothing that used to be shown has been dropped — the panels below are
  // the same lists the stacked version had, reached by tab instead of by
  // scrolling past all of them.
  const critical = roster?.critical_issues || [];
  const confirmations = roster?.confirmations || [];
  const editWarnings = roster?.edit_warnings || [];
  const advisories = roster?.issues || [];
  const staffing = audit?.staffing || [];
  const unrostered = roster?.unrostered || [];
  const weekVersions = rosters.filter((r) => r.week_start === week);

  // Needs attention is everything that wants a decision before approval:
  // uncovered hours, unfamiliar shifts, people owed contracted hours, and
  // rules that could not be read. Ordered worst first.
  const attention = [
    ...critical.map((text, i) => ({
      key: `crit-${i}`,
      severity: "bad",
      title: "Nobody in the shop",
      body: String(text).replace(/^CRITICAL:\s*/, ""),
      span: true,
    })),
    ...underContract.map((u) => ({
      key: `uc-${u.employee_id}`,
      severity: "warn",
      title: u.name,
      delta: `${u.short_hours}h short`,
      body: `${u.rostered_hours}h against a ${u.contracted_hours}h contract — they are owed the difference.`,
      employeeId: u.employee_id,
    })),
    ...confirmations.map((c, i) => ({
      key: `conf-${i}`,
      severity: "warn",
      title: `${empMap[c.employee_id]?.name || "Someone"} · ${DAY_SHORT[c.day]}`,
      delta: "please confirm",
      body: `${c.start}–${c.end} — ${c.message}`,
      employeeId: c.employee_id,
    })),
    ...inactiveRules.map((title, i) => ({
      key: `rule-${i}`,
      severity: "warn",
      title: String(title),
      delta: "not applied",
      body: "Switched on but could not be read, so the roster does not follow it. Reword it plainly, then Re-check rules.",
      rule: true,
      span: true,
    })),
  ];

  const TABS = [
    { key: "attention", label: "Needs attention", count: attention.length },
    { key: "edits", label: "From your edits", count: editWarnings.length },
    { key: "advisories", label: "Advisories", count: advisories.length + unrostered.length },
    { key: "usual", label: "Against the usual", count: staffing.length },
  ];

  /** Which fill a shift gets. Colour never carries this alone — the meta
   *  line under the time says "fixed", "pinned", "extra" or "night" too. */
  const cellKind = (s) => {
    if (!s) return "empty";
    if (s.paid_holiday || s.unpaid_holiday || s.sick) return "leave";
    if (s.fixed) return "template";
    if (isUnsocial(s)) return "unsocial";
    return "ai";
  };

  const cellMeta = (s) => {
    const bits = [];
    if (s.extra) bits.push("extra");
    else if (s.pinned) bits.push("pinned");
    if (s.fixed) bits.push("fixed");
    else if (isUnsocial(s)) bits.push("night");
    return bits.join(" · ");
  };

  const leaveLabel = (s) =>
    s.paid_holiday ? "Holiday" : s.unpaid_holiday ? "N/A" : "Sick";

  /** The click behaviour is unchanged from the previous layout — an
   *  approved week only accepts a sick report, everything else asks you
   *  to reopen it first. */
  const onCell = (s, employee, day, isLeaveCell) => {
    if (roster.approved) {
      if (weekHasEnded) {
        toast.error("This week has been worked and can no longer be changed");
      } else if (s?.sick) {
        setUndoSick({ ...s, employee_name: employee.name });
      } else if (s && !isLeaveCell && s.start) {
        setSickShift({ ...s, employee_name: employee.name });
      } else {
        setConfirmUnapprove(true);
      }
      return;
    }
    setEditShift(s || {
      shift_id: `new_${Date.now()}`,
      employee_id: employee.employee_id,
      day,
      start: "09:00",
      end: "17:00",
    });
  };

  const cellTitle = (s, isLeaveCell, confirm) =>
    roster.approved
      ? (s?.sick ? "Marked sick — click to undo"
        : s && !isLeaveCell && s.start ? "Approved — click to report sick and arrange cover"
          : "Approved — unapprove the week to edit it")
      : isLeaveCell ? "Booked leave — change it on the Holidays page"
        : s?.pinned ? "Pinned — kept when you rebalance"
          : confirm ? "Unfamiliar shift — please confirm" : undefined;

  // "Pinned only" narrows to the people who actually have a fixed or
  // pinned shift this week — the ones whose week is already decided.
  const gridPeople = pinnedOnly
    ? gridEmployees.filter((e) =>
        (roster?.shifts || []).some((s) => s.employee_id === e.employee_id && (s.pinned || s.fixed)))
    : gridEmployees;
  const shownPeople = gridPeople.slice(0, visiblePeople);

  const hoursFor = (id) => (roster?.shifts || [])
    .filter((s) => s.employee_id === id && s.start && s.end
      && !s.paid_holiday && !s.unpaid_holiday && !s.sick)
    .reduce((a, s) => a + shiftPaidHours(s, !!shop?.breaks_are_paid), 0);

  const headcount = (day) =>
    (shiftsByDay[day] || []).filter((s) => s.start && !s.paid_holiday && !s.unpaid_holiday && !s.sick).length;

  const panel = () => {
    if (tab === "usual") {
      return (
        <div className="wr-panel no-print">
          <div className="wr-panel-head">
            <div className="wr-panel-label">AGAINST THE USUAL</div>
          </div>
          {staffing.length === 0 ? (
            <div className="wr-panel-empty">Nothing to look at here — this week runs like the shop usually does.</div>
          ) : (
            <div className="wr-items">
              {staffing.map((note, i) => (
                <div key={i} className="wr-item" data-span={i === staffing.length - 1 && staffing.length % 2 === 1}>
                  <div className="wr-item-body" style={{ marginTop: 0 }}>{note.message}</div>
                </div>
              ))}
            </div>
          )}
          <p className="wr-panel-say">
            Compared with the last {audit?.learned_from_weeks ?? 0} weeks this shop has worked,
            recent weeks counting for more.
            {audit?.seasonal_weeks > 0
              ? " The same week last year is included."
              : " There is under a year of history, so nothing here knows about Christmas yet."}
            {" "}Nothing here blocks approval — if you have decided to run leaner, keep rostering
            it this way and the shop's usual will follow within a few months.
          </p>
        </div>
      );
    }

    if (tab === "advisories") {
      const items = [
        ...advisories.map((text, i) => ({ key: `adv-${i}`, body: String(text) })),
        ...unrostered.map((u) => ({
          key: `un-${u.employee_id}`,
          title: u.name,
          delta: "not rostered",
          body: u.reason,
        })),
      ];
      return (
        <div className="wr-panel no-print">
          <div className="wr-panel-head">
            <div className="wr-panel-label">ADVISORIES</div>
          </div>
          {items.length === 0 ? (
            <div className="wr-panel-empty">Nothing to look at here.</div>
          ) : (
            <div className="wr-items">
              {items.map((it, i) => (
                <div key={it.key} className="wr-item" data-span={i === items.length - 1 && items.length % 2 === 1}>
                  {it.title && (
                    <div className="wr-item-title">{it.title} · <em>{it.delta}</em></div>
                  )}
                  <div className="wr-item-body" style={it.title ? undefined : { marginTop: 0 }}>{it.body}</div>
                </div>
              ))}
            </div>
          )}
          <p className="wr-panel-say">
            What the generator did while building the week, and anyone it could not use.
            Background information — none of it blocks approval.
          </p>
        </div>
      );
    }

    if (tab === "edits") {
      return (
        <div className="wr-panel no-print">
          <div className="wr-panel-head">
            <div className="wr-panel-label">FROM YOUR EDITS</div>
          </div>
          {editWarnings.length === 0 ? (
            <div className="wr-panel-empty">Nothing to look at here — you have not edited this week.</div>
          ) : (
            <div className="wr-items">
              {editWarnings.map((w, i) => (
                <div key={i} className="wr-item" data-span={i === editWarnings.length - 1 && editWarnings.length % 2 === 1}>
                  <div className="wr-item-body" style={{ marginTop: 0 }}>{w}</div>
                </div>
              ))}
            </div>
          )}
          <p className="wr-panel-say">
            These were allowed because they are your call, but they are not what the
            generator would have produced.
          </p>
        </div>
      );
    }

    // Needs attention
    const blocking = critical.length > 0;
    return (
      <div className="wr-panel no-print">
        <div className="wr-panel-head">
          <div className="wr-panel-label">NEEDS ATTENTION</div>
          <div className="wr-panel-acts">
            <button
              type="button"
              data-testid="btn-recheck"
              className="wr-link"
              disabled={rechecking || generating || !roster}
              onClick={recheck}
            >
              {rechecking ? "Re-checking…" : "Re-check rules"}
            </button>
          </div>
        </div>
        {attention.length === 0 ? (
          <div className="wr-panel-empty">Nothing to look at here.</div>
        ) : (
          <div className="wr-items">
            {attention.map((it, i) => (
              <div
                key={it.key}
                className="wr-item"
                data-span={it.span || (i === attention.length - 1 && attention.length % 2 === 1)}
              >
                <div className="wr-item-title">
                  {it.title}{it.delta && <> · <em>{it.delta}</em></>}
                </div>
                <div className="wr-item-body">{it.body}</div>
                {it.employeeId && (
                  <button type="button" className="wr-item-link" onClick={() => {
                      setHighlight(it.employeeId);
                      setVisiblePeople(gridEmployees.length);
                      requestAnimationFrame(() => document
                        .querySelector(`[data-testid="cell-${it.employeeId}-mon"]`)
                        ?.scrollIntoView({ behavior: "smooth", block: "center" }));
                    }}>
                    Show in the grid
                  </button>
                )}
                {it.rule && (
                  <Link className="wr-item-link" to="/rules">Open the rule editor</Link>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="wr-panel-say">
          {attention.length === 0
            ? "Nothing needs a decision — this week is ready to approve."
            : blocking
              ? `${critical.length} of these leave nobody in the shop. Add staff, extend someone's hours, or adjust leave before approving.`
              : `Nothing here blocks approval — ${underContract.length} ${underContract.length === 1 ? "person is" : "people are"} owed hours${inactiveRules.length ? `, ${inactiveRules.length} ${inactiveRules.length === 1 ? "rule" : "rules"} could not be read` : ""}.`}
        </p>
      </div>
    );
  };

  return (
    <div className="wr-page">
      <header className="wr-head no-print">
        <div>
          <div className="wr-eyebrow">WEEKLY ROSTER</div>
          <h1 className="wr-h1">{weekRangeLabel(week)}</h1>
          {roster && (
            <div className="wr-status">
              <span className="wr-tag" data-tone={roster.approved ? "approved" : "draft"}>
                {roster.approved ? "Approved" : "Draft"} · {roster.version}
              </span>
              <span className="wr-signed">
                {roster.approved
                  ? `Signed off ${fmtApproved(roster.approved_at)}`
                  : attempts >= 3 && pinnedCount === 0
                    ? `Draft ${attempts} of this week — edit a shift and rebalance rather than regenerating`
                    : "Not approved yet"}
              </span>
            </div>
          )}
        </div>

        <div className="wr-headacts">
          {shop?.multi_department && user?.pro && (
            <span className="wr-picker">
              <select
                data-testid="dept-switch"
                value={department || ""}
                onChange={(e) => setDepartment(e.target.value || null)}
                aria-label="Department"
              >
                <option value="">All departments</option>
                {(shop.departments || []).map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </span>
          )}
          <label
            className="wr-picker"
            onClick={(e) => {
              const input = e.currentTarget.querySelector("input");
              try { input?.showPicker?.(); } catch { /* not supported here */ }
            }}
          >
            <Calendar size={14} color="var(--t-muted)" strokeWidth={1.6} aria-hidden="true" />
            <input
              data-testid="week-picker"
              type="date"
              value={week}
              onChange={(e) => chooseWeek(e.target.value)}
              aria-label="Week"
            />
          </label>

          {roster?.approved ? (
            <button
              data-testid="btn-unapprove"
              onClick={() => setConfirmUnapprove(true)}
              disabled={weekHasEnded}
              className="wr-btn wr-btn-2"
              title={weekHasEnded
                ? "This week has been worked and can no longer be reopened"
                : "Reopen this roster for editing"}
            >
              <Unlock size={14} /> Unapprove to edit
            </button>
          ) : (
            <>
              {pinnedCount > 0 && (
                <button
                  data-testid="btn-rebalance"
                  onClick={() => generate(true)}
                  disabled={generating || overLimit}
                  className="wr-btn wr-btn-1"
                  title={`Re-solve the week, keeping your ${pinnedCount} pinned shift(s)`}
                >
                  {generating ? <RefreshCw size={14} className="animate-spin" /> : <Pin size={14} />}
                  Rebalance ({pinnedCount})
                </button>
              )}
              {roster && (
                <button
                  data-testid="btn-extra"
                  onClick={() => setExtraOpen(true)}
                  className="wr-btn wr-btn-2"
                  title="Roster somebody on top of the normal cover — a delivery, a renovation, an unusually busy day"
                >
                  <UserPlus size={14} /> Add extra
                </button>
              )}
              <button
                data-testid="btn-generate"
                onClick={() => generate(false)}
                disabled={generating || overLimit}
                className={pinnedCount > 0 ? "wr-btn wr-btn-2" : "wr-btn wr-btn-1"}
                title={pinnedCount > 0 ? "Start over, discarding your pinned shifts" : undefined}
              >
                {generating ? <RefreshCw size={14} className="animate-spin" /> : <Wand2 size={14} />}
                {roster ? "Regenerate" : "Generate"}
              </button>
            </>
          )}
        </div>
      </header>

      {overLimit && (
        <div className="wr-panel no-print" style={{ borderTop: "1px solid #262626" }}>
          <div className="wr-panel-label">FREE PLAN LIMIT REACHED ({freeLimit} ROSTERS)</div>
          <p className="wr-panel-say">
            Upgrade to Pro for unlimited generations, AI learning and multi-department.{" "}
            <Link className="wr-link" to="/pricing">Upgrade</Link>
          </p>
        </div>
      )}

      {!roster ? (
        <div className="wr-empty no-print">
          No roster for this week yet — press {pinnedCount > 0 ? "Rebalance" : "Generate"} to build one.
        </div>
      ) : (
        <>
          <div className="wr-stats no-print">
            <div className="wr-stat">
              <div className="wr-stat-label">Coverage</div>
              <div
                className="wr-stat-value"
                data-tone={roster.compliance_score >= 90 ? "good" : roster.compliance_score >= 70 ? "warn" : "bad"}
              >
                {roster.compliance_score}<span className="wr-stat-suffix">/100</span>
              </div>
            </div>
            <div className="wr-stat">
              <div className="wr-stat-label">Weekly hours</div>
              <div className="wr-stat-value">{fmtHours(roster.total_hours)}</div>
            </div>
            <div className="wr-stat">
              <div className="wr-stat-label">Labour cost</div>
              <div className="wr-stat-value">{fmtMoney(roster.labor_cost)}</div>
            </div>
            <div className="wr-stat">
              <div className="wr-stat-label">Utilisation</div>
              <div className="wr-stat-value">{roster.utilization}%</div>
            </div>
          </div>

          <div className="wr-tabs no-print">
            <div className="wr-tabs-row" role="tablist" aria-label="What to look at">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.key}
                  className="wr-tab"
                  onClick={() => setTab(t.key)}
                >
                  {t.label}
                  {t.count !== undefined && (
                    <> <span className="wr-tab-count">({t.count})</span></>
                  )}
                </button>
              ))}
            </div>
          </div>

          {panel()}

          {roster.ai_summary && (
            <div className="wr-panel no-print" style={{ paddingTop: 0 }}>
              <p className="wr-panel-say" style={{ marginTop: 0 }}>{roster.ai_summary}</p>
            </div>
          )}

          <div className="wr-gridwrap" id="roster-print">
            <div className="wr-gridhead">
              <h2 className="wr-h2">
                The week <span>({gridEmployees.length} {gridEmployees.length === 1 ? "person" : "people"})</span>
              </h2>
              <div className="wr-panel-acts">
                {customOrder && (
                  <button type="button" data-testid="btn-reset-order" className="wr-link" onClick={resetOrder}>
                    Reset order
                  </button>
                )}
                <button
                  type="button"
                  className="wr-link wr-link-mute"
                  aria-pressed={pinnedOnly}
                  onClick={() => setPinnedOnly((v) => !v)}
                >
                  {pinnedOnly ? "Showing pinned only" : "Pinned only"}
                </button>
              </div>
            </div>

            {/* Wide: person × day matrix */}
            <div className="wr-grid" role="grid" aria-label="Weekly roster">
              <div className="wr-row wr-colhead" role="row">
                <div className="wr-colhead-label" role="columnheader">Employee</div>
                {DAYS.map((d) => {
                  const dt = dateForDay(week, d);
                  const dayGaps = gapsByDay[d] || [];
                  return (
                    <div key={d} className="wr-dayhead" role="columnheader">
                      <div className="wr-dayname">{DAY_SHORT[d]}</div>
                      <div className="wr-daydate">{fmtDayDate(dt)}</div>
                      {dayGaps.length > 0 && (
                        <button
                          type="button"
                          data-testid={`gap-${d}`}
                          className="wr-daylink wr-daylink-gap"
                          onClick={() => setSuggesting({ day: d, gaps: dayGaps })}
                        >
                          {dayGaps.length}h unfilled
                        </button>
                      )}
                      {!roster.approved && (
                        <button
                          type="button"
                          data-testid={`rebalance-${d}`}
                          disabled={generating}
                          className="wr-daylink wr-daylink-mute"
                          onClick={() => generate(true, d)}
                          title={`Re-solve ${DAY_LABELS[d]} only — every other day stays exactly as it is`}
                        >
                          rebalance day
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              {shownPeople.map((e, rowIndex) => {
                const empHours = hoursFor(e.employee_id);
                const trouble = breachesFor(e.employee_id);
                const max = Number(e.max_weekly_hours) || 0;
                const over = max > 0 && empHours > max;
                return (
                  <div
                    className="wr-row wr-personrow"
                    role="row"
                    key={e.employee_id}
                    data-highlight={highlight === e.employee_id}
                  >
                    <div className="wr-namecell" role="rowheader">
                      <div style={{ minWidth: 0, flex: 1 }}>
                        {trouble ? (
                          <button
                            type="button"
                            data-testid={`breach-${e.employee_id}`}
                            className="wr-name"
                            data-trouble="true"
                            onClick={() => setBreachFor(trouble)}
                            title="Click to see which rules this breaks"
                          >
                            {e.name}
                          </button>
                        ) : (
                          <div className="wr-name">{e.name}</div>
                        )}
                        <div className="wr-namesub" data-over={over} title={e.role}>
                          {e.role} · {over ? `${empHours.toFixed(1)}h of ${max}h` : `${empHours.toFixed(1)}h`}
                        </div>
                      </div>
                      <div className="wr-nudge">
                        <button
                          type="button"
                          data-testid={`move-up-${e.employee_id}`}
                          aria-label={`Move ${e.name} up`}
                          disabled={rowIndex === 0}
                          onClick={() => moveEmployee(e.employee_id, -1)}
                        >
                          <ChevronUp size={13} />
                        </button>
                        <button
                          type="button"
                          data-testid={`move-down-${e.employee_id}`}
                          aria-label={`Move ${e.name} down`}
                          disabled={rowIndex === shownPeople.length - 1}
                          onClick={() => moveEmployee(e.employee_id, 1)}
                        >
                          <ChevronDown size={13} />
                        </button>
                      </div>
                    </div>

                    {DAYS.map((d) => {
                      const s = (shiftsByDay[d] || []).find((x) => x.employee_id === e.employee_id);
                      const isLeaveCell = !!s && (s.paid_holiday || s.unpaid_holiday || s.sick);
                      const confirm = s && needsConfirming.has(`${e.employee_id}|${d}`);
                      const kind = cellKind(s);
                      const meta = s && !isLeaveCell ? cellMeta(s) : "";
                      const dur = s && !isLeaveCell ? shiftHours(s.start, s.end) : 0;
                      const name = s
                        ? isLeaveCell
                          ? `${e.name}, ${DAY_LABELS[d]}, ${leaveLabel(s).toLowerCase()}`
                          : `${e.name}, ${DAY_LABELS[d]}, ${s.start} to ${s.end}${s.fixed ? ", from a fixed template" : ""}${s.pinned ? ", pinned" : ""}`
                        : `${e.name}, ${DAY_LABELS[d]}, open slot`;
                      return (
                        <button
                          key={d}
                          role="gridcell"
                          data-testid={`cell-${e.employee_id}-${d}`}
                          className="wr-cell"
                          data-kind={kind}
                          data-confirm={Boolean(confirm)}
                          aria-label={name}
                          title={cellTitle(s, isLeaveCell, confirm)}
                          draggable={!!s && !isLeaveCell}
                          onDragStart={() => s && !isLeaveCell && setDragging(s)}
                          onDragOver={(ev) => { if (dragging && !isLeaveCell) ev.preventDefault(); }}
                          onDrop={(ev) => {
                            ev.preventDefault();
                            if (dragging && !isLeaveCell) moveShift(dragging, e.employee_id, d);
                            setDragging(null);
                          }}
                          onDragEnd={() => setDragging(null)}
                          onClick={() => onCell(s, e, d, isLeaveCell)}
                        >
                          {!s ? (
                            <span aria-hidden="true">+</span>
                          ) : isLeaveCell ? (
                            <span className="wr-cell-leave">{leaveLabel(s)}</span>
                          ) : (
                            <>
                              <span className="wr-cell-time">{s.start}–{s.end}</span>
                              <span className="wr-cell-meta">
                                {dur.toFixed(1)}h{meta ? ` · ${meta}` : ""}
                              </span>
                            </>
                          )}
                        </button>
                      );
                    })}
                  </div>
                );
              })}

              <div className="wr-row wr-totals" role="row">
                <div className="wr-totals-label" role="rowheader">On each day</div>
                {DAYS.map((d) => (
                  <div
                    key={d}
                    className="wr-total"
                    role="gridcell"
                    data-short={(gapsByDay[d] || []).length > 0}
                    aria-label={`${DAY_LABELS[d]}: ${headcount(d)} on`}
                  >
                    {headcount(d)}
                  </div>
                ))}
              </div>
            </div>

            {/* Narrow: a person × 7-day matrix is unusable at phone width, so
                the same data is read a day at a time. */}
            <div className="wr-daylist">
              {DAYS.map((d) => {
                const lines = shownPeople
                  .map((e) => ({ e, s: (shiftsByDay[d] || []).find((x) => x.employee_id === e.employee_id) }))
                  .filter((x) => x.s);
                return (
                  <div key={d} className="wr-dayblock">
                    <div className="wr-dayblock-head">
                      {DAY_LABELS[d]} <span>{fmtDayDate(dateForDay(week, d))} · {headcount(d)} on</span>
                    </div>
                    {lines.length === 0 ? (
                      <div className="wr-namesub">Nobody rostered.</div>
                    ) : lines.map(({ e, s }) => {
                      const isLeaveCell = s.paid_holiday || s.unpaid_holiday || s.sick;
                      return (
                        <button
                          key={e.employee_id}
                          type="button"
                          className="wr-dayline"
                          onClick={() => onCell(s, e, d, isLeaveCell)}
                        >
                          <span className="wr-dayline-name">{e.name}</span>
                          <span className="wr-dayline-time" data-kind={cellKind(s)}>
                            {isLeaveCell ? leaveLabel(s) : `${s.start}–${s.end}`}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>

            <div className="wr-gridfoot">
              <span>
                Showing {shownPeople.length} of {gridPeople.length}{" "}
                {gridPeople.length === 1 ? "person" : "people"} · dashed cells are open slots you can fill
              </span>
              {gridPeople.length > shownPeople.length && (
                <button type="button" className="wr-link" onClick={() => setVisiblePeople(gridPeople.length)}>
                  Show all {gridPeople.length}
                </button>
              )}
            </div>
          </div>

          <div className="wr-share no-print">
            {roster.approved ? (
              <span className="wr-tag">Approved</span>
            ) : (
              <button data-testid="btn-approve" className="wr-btn wr-btn-1" onClick={() => approve(false)}>
                <Check size={14} /> Approve
              </button>
            )}
            {roster.approved && !weekHasEnded && (
              <button
                type="button"
                data-testid="btn-unapprove-inline"
                className="wr-link wr-link-mute"
                onClick={() => setConfirmUnapprove(true)}
              >
                Unapprove to edit
              </button>
            )}
            <button type="button" className="wr-link" onClick={() => setDispatchOpen(true)}>Email team</button>
            <button type="button" className="wr-link" onClick={exportPDF}>PDF</button>
            <button type="button" className="wr-link" onClick={exportCSV}>CSV</button>
            <button type="button" className="wr-link" onClick={() => setPrintOpen(true)}>Print</button>
          </div>

          {weekVersions.length > 1 && (
            <div className="wr-versions no-print">
              <div className="wr-versions-label">VERSIONS THIS WEEK</div>
              <div className="wr-pills">
                {weekVersions.map((r) => (
                  <button
                    key={r.roster_id}
                    type="button"
                    className="wr-vpill"
                    data-active={r.roster_id === roster.roster_id}
                    onClick={() => {
                      setRoster(r);
                      setSearchParams({ week, roster: r.roster_id }, { replace: true });
                    }}
                  >
                    {r.version}{r.approved ? " · approved" : ""}
                  </button>
                ))}
              </div>
            </div>
          )}

          <p className="wr-note no-print">
            <strong>An approved week is read-only</strong> — reopening it starts a new draft and stops
            the week counting towards what the scheduler has learned. The one exception is somebody
            calling in sick, which an approved week accepts directly. <strong>Bright green came from a
            fixed template</strong>, mid green was placed by the solver, dark green is unsocial hours,
            and a bordered cell is booked leave — the label under each time says which, so the colour is
            never doing the work alone. <strong>Dashed cells are open slots</strong>: click one to fill it.
          </p>
        </>
      )}

      {editShift && (
        <ShiftModal
          shift={editShift}
          employee={empMap[editShift.employee_id]}
          onClose={() => setEditShift(null)}
          onSave={(p) => saveShift(p)}
          onDelete={() => saveShift(null)}
          onUnpin={unpin}
          isNew={editShift.shift_id?.startsWith("new_")}
        />
      )}

      {shiftWarning && (
        <ShiftWarningModal
          warnings={shiftWarning.warnings}
          confirmLabel={shiftWarning.confirmLabel}
          onClose={() => setShiftWarning(null)}
          onConfirm={() => {
            const action = shiftWarning.action;
            setShiftWarning(null);
            action();
          }}
        />
      )}

      {refused && (
        <RefusedModal
          message={refused.message}
          reasons={refused.reasons}
          onClose={() => setRefused(null)}
        />
      )}

      {undoSick && (
        <UndoSickModal
          rosterId={roster.roster_id}
          shift={undoSick}
          onClose={() => setUndoSick(null)}
          onDone={() => { setUndoSick(null); load(); }}
        />
      )}

      {/* Always rendered, never visible on screen — the print stylesheet
          hides the interactive grid and shows this instead. Rendering it
          only on demand would mean the browser printing before React had
          laid it out. */}
      {roster && (
        <RosterPrintSheet
          roster={roster}
          employees={gridEmployees}
          shop={shop}
          pages={printPages}
        />
      )}

      {printOpen && (
        <PrintDialog
          value={printPages}
          onChange={setPrintPages}
          people={gridEmployees.length}
          onClose={() => setPrintOpen(false)}
        />
      )}

      {breachFor && (
        <BreachModal person={breachFor} onClose={() => setBreachFor(null)} />
      )}

      {forceOpen && (
        <ForceApproveModal
          audit={audit}
          onClose={() => setForceOpen(false)}
          onConfirm={async (password, reason) => {
            await approve(false, { force: true, password, reason });
            setForceOpen(false);
          }}
        />
      )}

      {extraOpen && (
        <ExtraStaffModal
          rosterId={roster?.roster_id}
          employees={emps}
          week={week}
          onClose={() => setExtraOpen(false)}
          onDone={() => { setExtraOpen(false); load(); }}
        />
      )}

      {sickShift && (
        <SickCoverModal
          rosterId={roster.roster_id}
          shift={sickShift}
          onClose={() => setSickShift(null)}
          onDone={() => { setSickShift(null); load(); }}
        />
      )}

      {confirmUnapprove && (
        <Modal onClose={() => setConfirmUnapprove(false)}>
          <div className="flex items-center gap-2 mb-3">
            <Unlock size={18} style={{ color: "var(--ink-mute)" }} />
            <h2>Reopen this roster?</h2>
          </div>
          <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
            Week of <span className="font-mono">{week}</span> goes back to a draft
            you can edit, regenerate and rebalance.
          </p>
          <ul className="text-[13px] space-y-1.5 mb-5" style={{ color: "var(--ink-mute)" }}>
            <li>· It stops counting towards what the scheduler has learned, so
              future rosters will no longer copy this week's patterns.</li>
            <li>· If you have already sent it to staff, they are working from
              the old copy until you approve and send again.</li>
          </ul>
          <div className="flex gap-2">
            <button onClick={() => setConfirmUnapprove(false)} className="btn btn-secondary flex-1">
              Keep it approved
            </button>
            <button
              data-testid="btn-unapprove-confirm"
              onClick={unapprove}
              className="btn btn-primary flex-1"
            >
              Reopen for editing
            </button>
          </div>
        </Modal>
      )}

      {pendingApproval && (
        <Modal onClose={() => setPendingApproval(null)}>
          <div className="flex items-center gap-2 mb-3" style={{ color: "var(--danger)" }}>
            <AlertTriangle size={18} />
            <h2>Approve with gaps?</h2>
          </div>
          <p className="text-[13px] mb-5" style={{ color: "var(--ink-secondary)" }}>
            {pendingApproval}
          </p>
          <div className="flex gap-2">
            <button onClick={() => setPendingApproval(null)} className="btn btn-secondary flex-1">
              Go back and fix
            </button>
            <button
              data-testid="btn-approve-anyway"
              onClick={() => { setPendingApproval(null); approve(true); }}
              className="btn btn-danger"
            >
              Approve anyway
            </button>
          </div>
        </Modal>
      )}

      {suggesting && roster && (
        <SuggestionModal
          rosterId={roster.roster_id}
          day={suggesting.day}
          gaps={suggesting.gaps}
          onClose={() => setSuggesting(null)}
        />
      )}

      {dispatchOpen && roster && (
        <DispatchModal
          roster={roster}
          emps={emps}
          observers={shop?.roster_recipients || []}
          onClose={() => { setDispatchOpen(false); setDispatchResult(null); }}
          onSend={dispatch}
          sending={dispatching}
          result={dispatchResult}
        />
      )}
    </div>
  );
}

/**
 * Shown when a change is refused outright.
 *
 * A dialog rather than a toast: the manager has to read it and do something
 * else instead, and a notification that fades after four seconds is no use
 * for that.
 */
function RefusedModal({ message, reasons, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-md w-full card elevated p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>
        <div className="flex items-center gap-2 mb-3" style={{ color: "var(--danger)" }}>
          <AlertTriangle size={18} />
          <h3 style={{ color: "var(--danger)" }}>Change not applied</h3>
        </div>
        <p className="text-[13px] mb-4" style={{ color: "var(--ink-secondary)" }}>
          {message}
        </p>
        <ul className="status-danger p-4 space-y-2 text-[13px]">
          {reasons.map((reason, idx) => (
            <li key={idx} className="flex gap-2">
              <span aria-hidden>•</span><span>{reason}</span>
            </li>
          ))}
        </ul>
        <button onClick={onClose} className="btn btn-secondary w-full mt-5">
          Back to the roster
        </button>
      </div>
    </div>
  );
}

/**
 * Who could take an hour the solver refused to fill.
 *
 * The solver leaves a slot blank rather than give it to somebody unsuitable.
 * This shows the ranked alternatives and states plainly what is wrong with
 * each — the manager still decides, but without holding two dozen people's
 * constraints in their head.
 */
function SuggestionModal({ rosterId, day, gaps, onClose }) {
  const [candidates, setCandidates] = useState(null);
  const [error, setError] = useState(null);

  // The whole uncovered run, so one suggestion can close the gap.
  const start = `${String(Math.min(...gaps.map((g) => g.hour))).padStart(2, "0")}:00`;
  const end = `${String((Math.max(...gaps.map((g) => g.hour)) + 1) % 24).padStart(2, "0")}:00`;

  useEffect(() => {
    api.get(`/rosters/${rosterId}/suggestions`, { params: { day, start, end } })
      .then((r) => setCandidates(r.data.candidates))
      .catch((err) => setError(errorMessage(err, "Could not load suggestions")));
  }, [rosterId, day, start, end]);

  return (
    <Modal onClose={onClose}>
      <h2 className="mb-1">Nobody on {DAY_LABELS[day]}</h2>
      <p className="text-[13px] mb-5" style={{ color: "var(--ink-mute)" }}>
        {gaps.length} uncovered hour{gaps.length === 1 ? "" : "s"},{" "}
        <span className="font-mono">{start}–{end}</span>. Left blank rather
        than given to somebody who has never worked it.
      </p>

      {error && <div className="status-danger p-3 text-[13px]">{error}</div>}
      {!candidates && !error && (
        <div className="text-[13px]" style={{ color: "var(--ink-mute)" }}>Checking everybody…</div>
      )}

      <ul className="space-y-2 max-h-80 overflow-y-auto scroll-thin">
        {(candidates || []).map((c) => (
          <li key={c.employee_id} className="card-soft p-3">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[13px]">{c.name}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${roleClass(c.role)}`}>
                {c.role}
              </span>
              {c.already_working && <span className="pill">already on {DAY_SHORT[day]}</span>}
              {!c.blocked && c.reasons.length === 0 && !c.already_working && (
                <span className="pill" style={{ color: "var(--primary)" }}>can take it</span>
              )}
              {c.blocked && <span className="pill pill-danger">not allowed</span>}
            </div>
            {c.reasons.length > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {c.reasons.map((r, i) => (
                  <li key={i} className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
                    {r}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      <p className="text-[11px] mt-4" style={{ color: "var(--ink-mute-2)" }}>
        To use somebody, click their cell for {DAY_LABELS[day]} in the grid and
        set the times. Anything marked “not allowed” will still be refused.
      </p>
    </Modal>
  );
}

/** Shared shell for the dialogs on this page. */
/**
 * Report a shift sick and arrange cover.
 *
 * The list is never empty while anybody could physically do it. People who
 * can cover cleanly come first; below them, people who can only cover by
 * breaking something, each labelled with what it costs. That is the choice a
 * manager actually faces at 6am — not "covered or uncovered" but "which rule
 * do I bend, and who do I ask".
 */
function SickCoverModal({ rosterId, shift, onClose, onDone }) {
  const [options, setOptions] = useState(null);
  const [chosen, setChosen] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/rosters/${rosterId}/cover`, {
      params: { employee_id: shift.employee_id, day: shift.day },
    })
      .then((r) => setOptions(r.data))
      .catch((err) => {
        toast.error(errorMessage(err, "Could not look up cover"));
        setOptions({ candidates: [] });
      });
  }, [rosterId, shift]);

  const picked = options?.candidates?.find((c) => c.employee_id === chosen);

  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/rosters/${rosterId}/sick`, {
        employee_id: shift.employee_id,
        day: shift.day,
        cover_employee_id: chosen || null,
        reason: reason.trim() || null,
        overrides: (picked?.breaks || []).map((b) => b.rule),
      });
      toast.success(
        data.covered_by
          ? `Marked sick — ${data.covered_by} is covering`
          : "Marked sick — the shift is now uncovered",
      );
      onDone();
    } catch (err) {
      toast.error(errorMessage(err, "Could not record that"));
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose}>
      <div className="flex items-center gap-2 mb-1">
        <UserX size={18} style={{ color: "var(--warn)" }} />
        <h2>{shift.employee_name} off sick</h2>
      </div>
      <p className="text-[13px] mb-4" style={{ color: "var(--ink-secondary)" }}>
        {DAY_LABELS[shift.day]} <span className="font-mono">{shift.start}–{shift.end}</span>.
        The week stays approved — only this shift changes.
      </p>

      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (optional) — e.g. Flu"
        className="w-full px-3 py-2 rounded-lg text-sm mb-4"
      />

      {!options ? (
        <div className="flex items-center gap-2 text-sm py-4" style={{ color: "var(--ink-mute)" }}>
          <RefreshCw size={14} className="animate-spin" /> Finding cover…
        </div>
      ) : (
        <div className="max-h-72 overflow-y-auto scroll-thin space-y-1 mb-4">
          <label
            className="flex items-center gap-3 p-2.5 rounded-lg cursor-pointer"
            style={{ background: chosen === "" ? "var(--canvas-soft)" : "transparent" }}
          >
            <input type="radio" checked={chosen === ""} onChange={() => setChosen("")} />
            <span className="text-[13px]">Leave it uncovered for now</span>
          </label>

          {options.candidates.map((c) => (
            <label
              key={c.employee_id}
              data-testid={`cover-${c.employee_id}`}
              className="flex items-start gap-3 p-2.5 rounded-lg cursor-pointer"
              style={{
                background: chosen === c.employee_id ? "var(--canvas-soft)" : "transparent",
              }}
            >
              <input
                type="radio" className="mt-1"
                checked={chosen === c.employee_id}
                onChange={() => setChosen(c.employee_id)}
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 flex-wrap">
                  <span className="text-[13px]">{c.name}</span>
                  <span className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
                    {c.role}
                  </span>
                  {c.clean && <span className="pill">No rules broken</span>}
                </span>
                <span className="block text-[11px] mt-0.5" style={{ color: "var(--ink-mute)" }}>
                  {c.why}
                </span>
                {/* Stated per rule rather than as one lump, because "6th day"
                    and "2h over contract" are different decisions. */}
                {c.breaks.map((b) => (
                  <span key={b.rule} className="block text-[11px] mt-0.5"
                        style={{ color: "var(--warn)" }}>
                    ⚠ {b.detail}
                  </span>
                ))}
              </span>
            </label>
          ))}

          {options.candidates.length === 0 && (
            <p className="text-[13px] py-3" style={{ color: "var(--ink-mute)" }}>
              Nobody can take this shift — everyone is either on leave, already
              working those hours, or under 16 and curfew-bound.
            </p>
          )}
        </div>
      )}

      {picked && !picked.clean && (
        <p className="text-[12px] mb-3" style={{ color: "var(--warn)" }}>
          Choosing {picked.name} breaks {picked.breaks.length === 1 ? "a rule" : "rules"} you
          set. It will be recorded against this roster.
        </p>
      )}

      <div className="flex gap-2">
        <button onClick={onClose} className="btn btn-secondary flex-1">Cancel</button>
        <button
          data-testid="btn-confirm-sick"
          onClick={submit}
          disabled={busy}
          className="btn btn-primary flex-1"
        >
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <UserX size={14} />}
          {chosen ? "Mark sick and assign cover" : "Mark sick"}
        </button>
      </div>
    </Modal>
  );
}

/**
 * Take back a sick call recorded by mistake.
 *
 * Says what will happen to the cover as well as to the shift, because the
 * manager may have phoned somebody in and needs to know they are about to be
 * stood down.
 */
function UndoSickModal({ rosterId, shift, onClose, onDone }) {
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await api.delete(`/rosters/${rosterId}/sick`, {
        params: { employee_id: shift.employee_id, day: shift.day },
      });
      toast.success(
        data.cover_removed
          ? "Sick call removed — the cover shift has been taken off too"
          : "Sick call removed",
      );
      onDone();
    } catch (err) {
      toast.error(errorMessage(err, "Could not remove that"));
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose}>
      <div className="flex items-center gap-2 mb-3">
        <RefreshCw size={18} style={{ color: "var(--ink-mute)" }} />
        <h2>Remove this sick call?</h2>
      </div>
      <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
        {shift.employee_name} goes back to working {DAY_LABELS[shift.day]}{" "}
        <span className="font-mono">{shift.start}–{shift.end}</span>.
      </p>
      <ul className="text-[13px] space-y-1.5 mb-5" style={{ color: "var(--ink-mute)" }}>
        <li>· Anyone brought in to cover this shift is taken off it.</li>
        <li>· The absence stops counting against their sick leave.</li>
        <li>· The week stays approved.</li>
      </ul>
      <div className="flex gap-2">
        <button onClick={onClose} className="btn btn-secondary flex-1">Keep it</button>
        <button
          data-testid="btn-undo-sick"
          onClick={submit}
          disabled={busy}
          className="btn btn-primary flex-1"
        >
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
          Remove sick call
        </button>
      </div>
    </Modal>
  );
}

function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-md w-full card elevated p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>
        {children}
      </div>
    </div>
  );
}

const LEAVE_LABELS = {
  paid_holiday: "Paid holiday",
  unpaid_holiday: "N/A — unpaid leave",
  sick: "Sick leave",
};

/**
 * Edit one cell of the grid.
 *
 * Deliberately only edits WORK shifts. Leave is booked on the Holidays page,
 * which checks the balance before allowing it, prices the day correctly and
 * writes a holiday record. The same three tick-boxes used to live here too
 * and wrote the flag straight onto the shift — bypassing all of that, so
 * somebody could be marked down for paid holiday they had not earned.
 *
 * Two ways to record the same fact is one way too many when one of them
 * skips the rules.
 */
function ShiftModal({ shift, employee, onClose, onSave, onDelete, onUnpin, isNew }) {
  const [start, setStart] = useState(shift.start || "09:00");
  const [end, setEnd] = useState(shift.end || "17:00");

  const leaveKind = shift.paid_holiday ? "paid_holiday"
    : shift.unpaid_holiday ? "unpaid_holiday"
      : shift.sick ? "sick" : null;

  const under16 = employee?.age < 16;
  const conflict = under16 && (start < "08:00" || end > "19:00");
  const availability = availabilityConflict(employee, shift.day, start, end);

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-md w-full card elevated p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2"><X size={16} /></button>
        <div className="mb-6">
          <div className="font-medium">{employee?.name}</div>
          <div className="text-[13px]" style={{ color: "var(--ink-mute)" }}>
            {DAY_LABELS[shift.day]} · {leaveKind ? LEAVE_LABELS[leaveKind] : isNew ? "New shift" : "Edit shift"}
          </div>
        </div>

        {leaveKind ? (
          /* Booked leave. Read-only here so the roster and the holiday
             record cannot disagree — changing it means changing the
             booking, which lives on the Holidays page. */
          <>
            <div className="card-soft p-4 text-[13px]" style={{ color: "var(--ink-secondary)" }}>
              {employee?.name} is booked off this day as{" "}
              <span style={{ color: "var(--ink)" }}>{LEAVE_LABELS[leaveKind].toLowerCase()}</span>
              {shift.label ? ` (${shift.label})` : ""}.
              {leaveKind === "paid_holiday" && " The hours have been taken from their balance."}
            </div>
            <Link to="/calendar" className="btn btn-secondary w-full mt-4">
              Change this on the Holidays page
            </Link>
          </>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>Start</div>
                <input data-testid="edit-start" type="time" value={start}
                       onChange={(e) => setStart(e.target.value)}
                       className="w-full px-3 py-2 font-mono" />
              </label>
              <label className="block">
                <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>End</div>
                <input data-testid="edit-end" type="time" value={end}
                       onChange={(e) => setEnd(e.target.value)}
                       className="w-full px-3 py-2 font-mono" />
              </label>
            </div>

            {shift.pinned ? (
              <div className="card-soft p-3 mt-3 flex items-start gap-2">
                <Pin size={13} className="mt-0.5 shrink-0" style={{ color: "var(--ink-mute)" }} />
                <div className="text-[11px] flex-1" style={{ color: "var(--ink-mute)" }}>
                  Pinned, so rebalancing will keep it exactly as it is.
                  <button
                    type="button"
                    data-testid="btn-unpin"
                    onClick={() => onUnpin(shift)}
                    className="ml-1 underline"
                    style={{ color: "var(--ink)" }}
                  >
                    Unpin
                  </button>{" "}
                  to let the solver move it again.
                </div>
              </div>
            ) : (
              <p className="text-[11px] mt-3" style={{ color: "var(--ink-mute-2)" }}>
                Saving a change pins this shift, so a rebalance keeps it.
                Booking time off? Use the Holidays page — it checks the
                balance and records whether the day is paid.
              </p>
            )}

            {conflict && (
              <div className="status-danger mt-4 p-3 text-[13px] flex items-center gap-2">
                <AlertTriangle size={13} /> Under-16 curfew: shift must be within 08:00–19:00.
              </div>
            )}

            {availability && (
              <div className="status-warn mt-4 p-3 text-[13px] flex items-center gap-2">
                <AlertTriangle size={13} /> {availability} You will be asked to confirm before saving.
              </div>
            )}

            <div className="flex gap-2 mt-6">
              <button
                onClick={() => onSave({
                  shift_id: shift.shift_id,
                  employee_id: shift.employee_id,
                  day: shift.day,
                  start, end,
                  paid_holiday: false, unpaid_holiday: false, sick: false,
                  fixed: false,
                })}
                className="btn btn-primary flex-1"
              >
                Save
              </button>
              {!isNew && <button onClick={onDelete} className="btn btn-danger">Remove</button>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function DispatchModal({ roster, emps, observers = [], onClose, onSend, sending, result }) {
  // Everyone who will actually receive something. The modal used to count
  // only the STAFF, so a shop with a recipient configured was told "Send 2
  // emails" and then sent three — and with nobody configured there was no
  // way to tell from this screen whether the feature existed at all. That is
  // what made an absent attachment look like a broken feature.
  const total = emps.length + observers.length;
  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-2xl w-full card elevated p-8 relative max-h-[85vh] overflow-y-auto scroll-thin" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2"><X size={16} /></button>
        <h2 className="mb-1">Dispatch <span className="font-mono">{roster.version}</span></h2>
        <p className="text-[13px] mb-6" style={{ color: "var(--ink-mute)" }}>
          Each person gets their own shifts.
          {observers.length > 0 && (
            <> {observers.length} other recipient
              {observers.length !== 1 ? "s" : ""} get the whole week, with a
              PDF attached.</>
          )}
        </p>

        {!result ? (
          <>
            <div className="grid grid-cols-2 gap-2 mb-6">
              {emps.map((e) => {
                const count = roster.shifts.filter((s) => s.employee_id === e.employee_id).length;
                return (
                  <div key={e.employee_id} className="card-soft p-3">
                    <div className="min-w-0">
                      <div className="text-[13px] truncate">{e.name}</div>
                      <div className="text-[11px] truncate" style={{ color: "var(--ink-mute-2)" }}>{e.email}</div>
                      <div className="text-[11px] font-mono mt-0.5" style={{ color: "var(--ink-mute)" }}>
                        {count} shift{count !== 1 ? "s" : ""}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            {observers.length > 0 && (
              <div className="mb-6">
                <div className="eyebrow mb-2">Also sent the whole roster</div>
                <div className="grid grid-cols-2 gap-2">
                  {observers.map((o) => (
                    <div key={o.email} className="card-soft p-3">
                      <div className="text-[13px] truncate">{o.name || o.email}</div>
                      <div className="text-[11px] truncate" style={{ color: "var(--ink-mute-2)" }}>
                        {o.email}
                      </div>
                      <div className="text-[11px] mt-0.5" style={{ color: "var(--ink-mute)" }}>
                        every shift · PDF attached
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <button data-testid="btn-send-emails" onClick={onSend} disabled={sending} className="btn btn-primary w-full py-3">
              {sending ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
              {sending ? "Sending…" : `Send ${total} email${total !== 1 ? "s" : ""}`}
            </button>
          </>
        ) : (
          <div>
            <div className="card-soft p-4 mb-4 text-sm">
              <span className="font-mono">{result.sent.length}</span> sent ·{" "}
              <span className="font-mono" style={{ color: result.failed.length ? "var(--danger)" : "var(--ink-mute)" }}>
                {result.failed.length}
              </span>{" "}
              failed
            </div>
            {result.observers && (
              (result.observers.sent || []).length > 0
              || (result.observers.failed || []).length > 0
            ) && (
              <div className="card-soft p-3 mb-4 text-[12px]">
                <div className="eyebrow mb-1">Whole roster</div>
                {(result.observers.sent || []).map((o) => (
                  <div key={o.email} className="flex items-center gap-2"
                       style={{ color: "var(--ink-mute)" }}>
                    <Check size={12} style={{ color: "var(--primary-deep)" }} />
                    {o.name || o.email} · PDF attached
                  </div>
                ))}
                {(result.observers.failed || []).map((o) => (
                  <div key={o.email} style={{ color: "var(--danger)" }}>
                    <div className="flex items-center gap-2">
                      <X size={12} /> {o.name || o.email}
                    </div>
                    <div style={{ color: "var(--ink-mute-2)" }}>{o.error}</div>
                  </div>
                ))}
              </div>
            )}
            <ul className="space-y-2 max-h-80 overflow-y-auto scroll-thin">
              {result.sent.map((s) => (
                <li key={s.employee_id} className="text-[13px] flex items-center gap-2" style={{ color: "var(--ink-mute)" }}>
                  <Check size={13} style={{ color: "var(--primary-deep)" }} /> {s.name} · {s.email}
                </li>
              ))}
              {result.failed.map((s) => (
                <li key={s.employee_id} className="text-[13px] flex items-start gap-2" style={{ color: "var(--danger)" }}>
                  <X size={13} className="mt-0.5 shrink-0" />
                  <div>
                    <div>{s.name} · {s.email}</div>
                    <div style={{ color: "var(--ink-mute-2)" }}>{s.error}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}


/**
 * Roster somebody ABOVE the normal cover.
 *
 * The inverse of pinning, and the difference matters. Pinning says "*this*
 * person fills that slot", so the solver places one fewer person. Adding
 * somebody as extra says "this person *as well as* the usual cover", so the
 * normal shifts are all still filled and they are on top.
 *
 * That is why this is its own action rather than a checkbox on the shift
 * editor: clicking an empty cell and saving means "put them here", which
 * pins. Choosing "Add extra" means something genuinely different, and the two
 * should not look like the same gesture.
 *
 * The hours are real — they count against the weekly cap, the contract and
 * the five-day limit — and the legal limits still apply. The server refuses
 * with named reasons rather than this form guessing at them, because it is
 * the only place that can see the whole week.
 */
function ExtraStaffModal({ rosterId, employees, week, onClose, onDone }) {
  const [employeeId, setEmployeeId] = useState("");
  const [day, setDay] = useState(DAYS[0]);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [refused, setRefused] = useState(null);

  const active = (employees || []).filter((e) => e.is_active !== false);
  const person = active.find((e) => e.employee_id === employeeId);
  const hours = shiftHours(start, end);

  const submit = async () => {
    if (!employeeId) { toast.error("Choose who is coming in"); return; }
    setSaving(true);
    setRefused(null);
    try {
      await api.post(`/rosters/${rosterId}/extra`, {
        employee_id: employeeId, day, start, end, reason,
      });
      toast.success(
        `${person?.name} added on ${DAY_LABELS[day]} — on top of the usual cover`,
      );
      onDone();
    } catch (err) {
      // A refusal carries structured reasons so they can be listed one per
      // line. Rendering the object straight into JSX would crash the page.
      const refusal = refusalReasons(err);
      if (refusal) {
        setRefused(refusal);
        return;
      }
      toast.error(errorMessage(err, "Could not add the extra shift"));
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-md w-full card elevated p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2"><X size={16} /></button>

        <div className="mb-6">
          <div className="font-medium flex items-center gap-2">
            <UserPlus size={15} style={{ color: "var(--primary)" }} /> Add extra staff
          </div>
          <div className="text-[13px] mt-1" style={{ color: "var(--ink-mute)" }}>
            On top of the normal cover, not instead of it. The usual shifts are
            still filled.
          </div>
        </div>

        <label className="block mb-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>Who</div>
          <select
            data-testid="extra-employee"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            className="w-full px-3 py-2"
          >
            <option value="">Choose someone…</option>
            {active.map((e) => (
              <option key={e.employee_id} value={e.employee_id}>
                {e.name} · {e.role}
              </option>
            ))}
          </select>
        </label>

        <label className="block mb-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>Day</div>
          <select
            data-testid="extra-day"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="w-full px-3 py-2"
          >
            {DAYS.map((d) => (
              <option key={d} value={d}>
                {DAY_LABELS[d]} · {fmtDayDate(dateForDay(week, d))}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>Start</div>
            <input data-testid="extra-start" type="time" value={start}
                   onChange={(e) => setStart(e.target.value)}
                   className="w-full px-3 py-2 font-mono" />
          </label>
          <label className="block">
            <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>End</div>
            <input data-testid="extra-end" type="time" value={end}
                   onChange={(e) => setEnd(e.target.value)}
                   className="w-full px-3 py-2 font-mono" />
          </label>
        </div>

        <label className="block mt-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            Why (optional)
          </div>
          <input
            data-testid="extra-reason"
            value={reason}
            maxLength={200}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Stock delivery, refit, expected rush…"
            className="w-full px-3 py-2 text-[13px]"
          />
          <div className="text-[11px] mt-1" style={{ color: "var(--ink-mute-2)" }}>
            Shown on the roster, so a week that cost more than usual says why.
          </div>
        </label>

        {refused && (
          <div className="status-danger mt-4 p-3 text-[13px]">
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle size={13} /> {refused.message}
            </div>
            <ul className="mt-2 space-y-1">
              {refused.reasons.map((r, i) => (
                <li key={i}>• {r}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="card-soft p-3 mt-4 text-[11px]" style={{ color: "var(--ink-mute)" }}>
          {hours > 0
            ? `${hours.toFixed(1)}h — counts towards their weekly hours, their contract and the five-day limit.`
            : "Finish must be after the start."}
          {" "}Kept when you rebalance.
        </div>

        <button
          data-testid="extra-save"
          onClick={submit}
          disabled={saving || !employeeId || hours <= 0}
          className="btn btn-primary w-full mt-4"
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <UserPlus size={14} />}
          Add as extra
        </button>
      </div>
    </div>
  );
}


/**
 * How many sheets of paper the rota may use.
 *
 * Asked rather than assumed, because it is a real trade-off and only the
 * person at the printer knows which way it goes. A shop with 25 staff does
 * not want ten sheets; a shop that pins the rota where people read it at a
 * glance does not want six-point type. Neither is the right default for the
 * other.
 *
 * It replaces a browser prompt() that took a number and then scaled by
 * 1/pages — which meant "1 page" applied no compression at all and printed
 * exactly as many sheets as it always had.
 */
function PrintDialog({ value, onChange, people, onClose }) {
  // Mirrors RosterPrintSheet's arithmetic so the warning is honest: rows are
  // people, plus a heading per role, plus the day header.
  const estimateRows = people + 4;
  const rowMm = Math.min(9, Math.max(3.2, (152 * value) / estimateRows));
  const tooTight = rowMm <= 3.3;

  const options = [
    { pages: 1, label: "One sheet", hint: "Everything on a single page" },
    { pages: 2, label: "Two sheets", hint: "Larger type, easier to read" },
    { pages: 3, label: "Three sheets", hint: "Largest — for a noticeboard" },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4 no-print"
         onClick={onClose}>
      <div className="max-w-sm w-full card elevated p-8 relative"
           onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>

        <div className="mb-1 font-medium flex items-center gap-2">
          <Printer size={15} /> Print the rota
        </div>
        <div className="text-[13px] mb-5" style={{ color: "var(--ink-mute)" }}>
          {people} {people === 1 ? "person" : "people"} on this week.
        </div>

        <div className="space-y-2">
          {options.map((option) => (
            <button
              key={option.pages}
              data-testid={`print-${option.pages}`}
              onClick={() => onChange(option.pages)}
              className="w-full text-left p-3 rounded-md"
              style={{
                border: `1px solid ${value === option.pages
                  ? "var(--ink)" : "var(--hairline)"}`,
                background: value === option.pages
                  ? "var(--canvas-soft)" : "transparent",
              }}
            >
              <div className="text-[13px]">{option.label}</div>
              <div className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
                {option.hint}
              </div>
            </button>
          ))}
        </div>

        {tooTight && (
          <div className="status-warn p-3 mt-4 text-[11px]">
            With {people} people this will be very small type. Two sheets will
            be easier to read.
          </div>
        )}

        <button
          data-testid="print-go"
          onClick={() => {
            // The sheet is already rendered at this row height; closing the
            // dialog first keeps it out of the printed page.
            onClose();
            setTimeout(() => window.print(), 80);
          }}
          className="btn btn-primary w-full mt-5"
        >
          <Printer size={14} /> Print
        </button>
      </div>
    </div>
  );
}


/**
 * Why this person's name is highlighted.
 *
 * Named numbers, not rule names. "Rostered 48h against a 44h limit — 4h over"
 * tells a manager what to change; "weekly_hours_exceeded" makes them go and
 * look it up. The sentences come from the server, which is the only place
 * that can see the whole week.
 */
function BreachModal({ person, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="max-w-md w-full card elevated p-8 relative"
           onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>

        <div className="font-medium mb-1">{person.name}</div>
        <div className="text-[13px] mb-5" style={{ color: "var(--ink-mute)" }}>
          {person.breaches.length}{" "}
          {person.breaches.length === 1 ? "rule is" : "rules are"} broken this week.
        </div>

        <div className="space-y-2">
          {person.breaches.map((breach, i) => (
            <div key={i} className="card-soft p-3 flex items-start gap-2">
              <AlertTriangle
                size={13}
                className="mt-0.5 shrink-0"
                style={{ color: breach.overridable ? "var(--warn)" : "var(--danger)" }}
              />
              <div className="min-w-0">
                <div className="text-[13px]">{breach.message}</div>
                {!breach.overridable && (
                  <div className="text-[11px] mt-1" style={{ color: "var(--danger)" }}>
                    This one cannot be approved, with or without a password.
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <p className="text-[11px] mt-5" style={{ color: "var(--ink-mute-2)" }}>
          You can leave these as they are — the roster saves either way.
          Approving the week is what needs them fixed, or deliberately
          overridden.
        </p>
      </div>
    </div>
  );
}

/**
 * Approving a week that breaks rules.
 *
 * The password is the account's own, re-entered. It is not security theatre
 * and it is not a second factor: it exists so the record names a PERSON
 * rather than a session somebody left open on the back-office machine. A
 * six-day week is a decision with a consequence, and whoever takes it should
 * be identifiable afterwards.
 *
 * The list of what is being overridden is shown in full, deliberately. An
 * override you can grant without reading is the same as no override at all.
 */
function ForceApproveModal({ audit, onClose, onConfirm }) {
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const breaches = (audit?.people || []).flatMap((p) => p.breaches);

  const submit = async () => {
    if (!password) { toast.error("Enter your password to authorise this"); return; }
    setBusy(true);
    try {
      await onConfirm(password, reason);
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="max-w-md w-full card elevated p-8 relative"
           onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2">
          <X size={16} />
        </button>

        <div className="font-medium flex items-center gap-2 mb-1">
          <AlertTriangle size={15} style={{ color: "var(--warn)" }} />
          Approve anyway
        </div>
        <div className="text-[13px] mb-4" style={{ color: "var(--ink-mute)" }}>
          This week breaks {breaches.length}{" "}
          {breaches.length === 1 ? "rule" : "rules"}. Approving it makes it the
          schedule your team is told to work.
        </div>

        <div className="card-soft p-3 mb-4 max-h-44 overflow-auto">
          {breaches.map((breach, i) => (
            <div key={i} className="text-[12px] py-1"
                 style={{ color: "var(--ink-secondary)" }}>
              • {breach.message}
            </div>
          ))}
        </div>

        <label className="block mb-3">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            Why (optional, kept on the record)
          </div>
          <input
            data-testid="force-reason"
            value={reason}
            maxLength={300}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Two people off sick, agreed with the team"
            className="w-full px-3 py-2 text-[13px]"
          />
        </label>

        <label className="block">
          <div className="text-[11px] mb-1" style={{ color: "var(--ink-mute)" }}>
            Your password
          </div>
          <input
            data-testid="force-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            autoFocus
            className="w-full px-3 py-2 text-[13px]"
          />
          <div className="text-[11px] mt-1" style={{ color: "var(--ink-mute-2)" }}>
            Recorded against this roster with your name and the list above.
          </div>
        </label>

        <div className="flex gap-2 mt-5">
          <button onClick={onClose} className="btn btn-secondary flex-1">
            Go back and fix it
          </button>
          <button
            data-testid="force-confirm"
            onClick={submit}
            disabled={busy || !password}
            className="btn btn-primary flex-1"
          >
            {busy ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
            Approve anyway
          </button>
        </div>
      </div>
    </div>
  );
}
