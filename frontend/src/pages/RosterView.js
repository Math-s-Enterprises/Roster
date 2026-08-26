import React, { useEffect, useMemo, useState } from "react";
import { api, errorMessage, refusalReasons, DAY_LABELS, DAY_SHORT, DAYS, mondayOf, fmtHours, fmtMoney, roleClass, roleAccent, shiftHours, shiftPaidHours, dateForDay, fmtDayDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Link } from "react-router-dom";
import { Crown } from "lucide-react";
import { toast } from "sonner";
import confetti from "canvas-confetti";
import jsPDF from "jspdf";
import { Wand2, Send, Check, FileDown, Printer, AlertTriangle, RefreshCw, Mail, X, Sparkles, HelpCircle, UserX, UserPlus, ChevronUp, ChevronDown, Pin, Unlock } from "lucide-react";

export default function RosterView() {
  const { user } = useAuth();
  const [week, setWeek] = useState(mondayOf());
  const [roster, setRoster] = useState(null);
  const [emps, setEmps] = useState([]);
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
  const [confirmUnapprove, setConfirmUnapprove] = useState(false);
  const [sickShift, setSickShift] = useState(null);
  const [extraOpen, setExtraOpen] = useState(false);
  // How many drafts this week has been through. Counted from the
  // stored version rather than a local tally, so it survives a
  // reload and is honest about what actually happened.
  const attempts = Number(String(roster?.version || "v1.0")
    .replace(/^v\d+\./, "")) + 1 || 1;
  const [undoSick, setUndoSick] = useState(null);

  const load = async () => {
    const [e, r, s] = await Promise.all([api.get("/employees"), api.get("/rosters"), api.get("/shop")]);
    setEmps(e.data); setRosters(r.data); setShop(s.data);
    const found = r.data.find((x) => x.week_start === week && (x.department || null) === (department || null));
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
  const approve = async (acknowledgeGaps = false) => {
    try {
      const url = `/rosters/${roster.roster_id}/approve`
        + (acknowledgeGaps ? "?acknowledge_gaps=true" : "");
      const r = await api.post(url);
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

  const saveShift = async (payload) => {
    if (payload && shiftHours(payload.start, payload.end) > 11) {
      toast.error("Shift exceeds 11h limit"); return;
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

  const moveShift = async (shift, toEmpId, toDay) => {
    if (shift.employee_id === toEmpId && shift.day === toDay) return;
    const shifts = (roster.shifts || []).map((s) =>
      s.shift_id === shift.shift_id ? { ...s, employee_id: toEmpId, day: toDay } : s
    );
    const dup = shifts.filter((s) => s.shift_id !== shift.shift_id).find((s) => s.employee_id === toEmpId && s.day === toDay);
    if (dup) { toast.error("That slot already has a shift"); return; }
    const clean = shifts.map(({ employee_id, day, start, end, paid_holiday, unpaid_holiday, sick }) => ({ employee_id, day, start, end, paid_holiday: !!paid_holiday, unpaid_holiday: !!unpaid_holiday, sick: !!sick }));
    try {
      const r = await api.put(`/rosters/${roster.roster_id}`, { shifts: clean });
      setRoster(r.data);
      toast.success("Shift moved");
      (r.data.edit_warnings || []).slice(0, 3).forEach((w) => toast.warning(w));
    } catch (err) {
      const refusal = refusalReasons(err);
      if (refusal) setRefused(refusal);
      else toast.error(errorMessage(err, "Could not move the shift"));
    }
  };

  const exportCSV = () => {
    const rows = [["Employee", "Role", "Department", "Day", "Date", "Start", "End", "Hours"]];
    (roster.shifts || []).forEach((s) => {
      const e = empMap[s.employee_id] || {};
      const d = dateForDay(roster.week_start, s.day);
      const label = s.paid_holiday ? "Holiday" : s.unpaid_holiday ? "Unpaid" : s.sick ? "Sick" : "";
      rows.push([
        e.name, e.role, (e.departments || []).join("/"), DAY_LABELS[s.day],
        d.toISOString().slice(0, 10),
        s.start || label, s.end || label,
        shiftPaidHours(s).toFixed(1),
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
      const label = s.paid_holiday ? "Holiday" : s.unpaid_holiday ? "Unpaid leave" : s.sick ? "Sick" : "";
      pdf.text(String(e.name || "").slice(0, 24), colX[0], y);
      pdf.text(String(e.role || ""), colX[1], y);
      pdf.text(DAY_LABELS[s.day], colX[2], y);
      pdf.text(fmtDayDate(d), colX[3], y);
      pdf.text(s.start && s.end ? `${s.start} – ${s.end}` : label, colX[4], y);
      pdf.text(`${shiftPaidHours(s).toFixed(1)}h`, colX[5], y);
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

  return (
    <div className="max-w-full">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8 no-print">
        <div>
          <div className="eyebrow mb-2">Weekly roster</div>
          <h1 className="display">
            Week of <span className="font-mono">{week}</span>
          </h1>
          {roster && (
            <div className="mt-2 flex items-center gap-2 text-[13px]" style={{ color: "var(--ink-mute)" }}>
              <span className="font-mono">{roster.version}</span>
              {roster.approved && (
                <span className="pill"><Check size={11} /> Approved</span>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          {shop?.multi_department && user?.pro && (
            <select
              data-testid="dept-switch"
              value={department || ""}
              onChange={(e) => setDepartment(e.target.value || null)}
              className="px-3 py-2 text-sm"
            >
              <option value="">All departments</option>
              {(shop.departments || []).map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          <input
            data-testid="week-picker"
            type="date"
            value={week}
            onChange={(e) => setWeek(mondayOf(e.target.value))}
            className="px-3 py-2 font-mono text-sm"
          />
          {/* An approved week is closed. Rebalance and Regenerate both build a
              a new draft, and approving that draft would leave two approved
              rosters on one week — which the scheduler reads as two weeks that
              were both worked. Reopening is the way back in, and it is offered
              here rather than hiding the buttons with no explanation. */}
          {roster?.approved ? (
            <button
              data-testid="btn-unapprove"
              onClick={() => setConfirmUnapprove(true)}
              disabled={weekHasEnded}
              className="btn btn-secondary"
              title={
                weekHasEnded
                  ? "This week has been worked and can no longer be reopened"
                  : "Reopen this roster for editing"
              }
            >
              <Unlock size={14} /> Unapprove to edit
            </button>
          ) : (
            <>
              {/* Rebalance is the primary action once anything is pinned.
                  Editing the tenth of a roster that is wrong keeps the other
                  nine tenths AND tells the scheduler something; regenerating
                  throws away both the attempt and the reason it was wrong.
                  The cheap action should be the one that improves the
                  product, so it gets the filled button. */}
              {pinnedCount > 0 && (
                <button
                  data-testid="btn-rebalance"
                  onClick={() => generate(true)}
                  disabled={generating || overLimit}
                  className="btn btn-primary"
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
                  className="btn btn-secondary"
                  title="Roster somebody on top of the normal cover — a delivery, a renovation, an unusually busy day"
                >
                  <UserPlus size={14} /> Add extra
                </button>
              )}
              <button
                data-testid="btn-generate"
                onClick={() => generate(false)}
                disabled={generating || overLimit}
                className={pinnedCount > 0 ? "btn btn-secondary" : "btn btn-primary"}
                title={pinnedCount > 0 ? "Start over, discarding your pinned shifts" : undefined}
              >
                {generating ? <RefreshCw size={14} className="animate-spin" /> : <Wand2 size={14} />}
                {roster ? "Regenerate" : "Generate"}
              </button>
            </>
          )}
        </div>
      </div>

      {overLimit && (
        <div className="card p-5 mb-6 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Crown size={18} style={{ color: "var(--ink-mute)" }} />
            <div>
              <div className="text-sm font-medium">Free plan limit reached ({freeLimit} rosters)</div>
              <div className="text-[13px]" style={{ color: "var(--ink-mute)" }}>
                Upgrade to Pro for unlimited generations, AI learning and multi-department.
              </div>
            </div>
          </div>
          <Link to="/pricing" className="btn btn-secondary">Upgrade</Link>
        </div>
      )}

      {/* Said once, at the third draft of one week, and only while nothing is
          pinned — with pins there is already a Rebalance button doing the
          right thing and this would be nagging.

          Deliberately not "regenerating is pointless". It is not: it offers a
          different arrangement of the shifts nobody has a settled claim on.
          But it starts from the same inputs, so it cannot fix a roster that
          is wrong for a reason the scheduler does not know yet — and editing
          is what tells it. */}
      {roster && !roster.approved && attempts >= 3 && pinnedCount === 0 && (
        <div className="card p-4 mb-6 no-print flex items-start gap-3">
          <Sparkles size={15} className="mt-0.5 shrink-0" style={{ color: "var(--accent)" }} />
          <div className="text-[13px]" style={{ color: "var(--ink-secondary)" }}>
            <span style={{ color: "var(--ink)" }}>
              This is draft {attempts} of the same week.
            </span>{" "}
            If a shift keeps coming out wrong, change that shift and press
            Rebalance — the rest of the week is kept, and the scheduler learns
            what you changed. Regenerating gives you a different arrangement,
            but it starts from the same information.
          </div>
        </div>
      )}

      {roster && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-px mb-6 no-print card overflow-hidden"
               style={{ background: "var(--hairline)" }}>
            <Metric label="Coverage" value={roster.compliance_score} suffix="/100"
                    tone={roster.compliance_score >= 90 ? "good"
                          : roster.compliance_score >= 70 ? "warn" : "bad"} />
            <Metric label="Weekly hours" value={fmtHours(roster.total_hours)} />
            <Metric label="Labour cost" value={fmtMoney(roster.labor_cost)} />
            <Metric label="Utilisation" value={`${roster.utilization}%`} />
          </div>

          {roster.ai_summary && (
            <div className="card-soft p-4 mb-6 flex items-start gap-2.5 no-print">
              <Sparkles size={15} className="mt-0.5 shrink-0" style={{ color: "var(--ink-mute-2)" }} />
              <div className="text-[13px]" style={{ color: "var(--ink-secondary)" }}>
                {roster.ai_summary}
              </div>
            </div>
          )}

          {/* Critical issues mean the shop would be left unattended — a broken
              guarantee, not a planning nicety. Kept visually distinct from and
              above the advisory list so it cannot be skimmed past, and shown in
              print output too, since that is what gets pinned to the wall. */}
          {roster.critical_issues?.length > 0 && (
            <div className="status-danger p-5 mb-6">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={16} />
                <span className="text-sm font-medium">
                  Uncovered shifts ({roster.critical_issues.length})
                </span>
              </div>
              <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
                No employee can legally cover the times below. Nobody would be in the
                shop. Add staff, extend someone's weekly hours, or adjust leave.
              </p>
              <ul className="space-y-1.5 text-[13px]">
                {roster.critical_issues.map((issue, idx) => (
                  <li key={idx} className="flex gap-2">
                    <span aria-hidden>•</span>
                    <span>{issue.replace(/^CRITICAL:\s*/, "")}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Shifts that are legal but unlike anything the person has worked
              before. Separate from advisories because each one is a decision
              the manager has to actually make, not background information. */}
          {roster.confirmations?.length > 0 && (
            <div className="status-warn p-5 mb-6 no-print">
              <div className="flex items-center gap-2 mb-2">
                <HelpCircle size={16} />
                <span className="text-sm font-medium">
                  Please confirm ({roster.confirmations.length})
                </span>
              </div>
              <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
                These assignments are allowed, but are unlike anything the
                person has worked before. Check they are happy with them.
              </p>
              <ul className="space-y-1.5 text-[13px]">
                {roster.confirmations.map((c, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="font-mono shrink-0 w-9">{DAY_SHORT[c.day]}</span>
                    <span style={{ color: "var(--ink-secondary)" }}>
                      <span className="font-mono">{c.start}–{c.end}</span>
                      {" — "}{c.message}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Consequences of hand edits. Kept on the roster rather than
              only in a toast, so they survive a reload. */}
          {roster.edit_warnings?.length > 0 && (
            <div className="status-warn p-5 mb-6 no-print">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={16} />
                <span className="text-sm font-medium">
                  From your edits ({roster.edit_warnings.length})
                </span>
              </div>
              <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
                These were allowed because they are your call, but they are
                not what the generator would have produced.
              </p>
              <ul className="space-y-1.5 text-[13px]">
                {roster.edit_warnings.map((w, idx) => (
                  <li key={idx} className="flex gap-2">
                    <span aria-hidden>•</span><span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Contracted hours are owed, not merely permitted. */}
          {roster.under_contract?.length > 0 && (
            <div className="status-warn p-5 mb-6 no-print">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={16} />
                <span className="text-sm font-medium">
                  Below contracted hours ({roster.under_contract.length})
                </span>
              </div>
              <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
                These people are owed more hours than the week gives them. Either
                the shop doesn't need the cover, or their availability blocked it.
              </p>
              <ul className="space-y-1.5 text-[13px]">
                {roster.under_contract.map((u) => (
                  <li key={u.employee_id} className="flex items-center gap-2 flex-wrap">
                    <span style={{ color: "var(--ink)" }}>{u.name}</span>
                    <span className="font-mono">
                      {u.rostered_hours}h of {u.contracted_hours}h
                    </span>
                    <span className="pill pill-warn">{u.short_hours}h short</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Nobody is silently left off a roster — anyone who got no shifts
              is listed here with the reason they were passed over. */}
          {roster.unrostered?.length > 0 && (
            <div className="card p-5 mb-6 no-print">
              <div className="flex items-center gap-2 mb-3">
                <UserX size={16} style={{ color: "var(--ink-mute)" }} />
                <span className="text-sm font-medium">
                  Not rostered this week ({roster.unrostered.length})
                </span>
              </div>
              <ul className="space-y-2">
                {roster.unrostered.map((u) => (
                  <li key={u.employee_id} className="flex items-center gap-2 text-[13px] flex-wrap">
                    <span className="shrink-0">{u.name}</span>
                    {u.role && (
                      <span className={`text-[11px] px-1.5 py-0.5 rounded shrink-0 ${roleClass(u.role)}`}>
                        {u.role}
                      </span>
                    )}
                    <span style={{ color: "var(--ink-mute)" }}>{u.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Advisories stay monochrome — three severity tiers only work if
              the lowest one does not compete with the two above it. */}
          {roster.issues?.length > 0 && (
            <div className="card p-5 mb-6 no-print">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle size={16} style={{ color: "var(--ink-mute)" }} />
                <span className="text-sm font-medium">
                  Advisories ({roster.issues.length})
                </span>
              </div>
              <ul className="space-y-1 text-[13px]" style={{ color: "var(--ink-mute)" }}>
                {roster.issues.map((issue, idx) => (
                  <li key={idx} className="flex gap-2">
                    <span aria-hidden>•</span><span>{issue}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Weekly grid */}
          {/* Sits on the page colour so the filled cells inside lift off it.
              On a dark canvas, elevation is a lighter surface — a drop shadow
              against near-black is invisible. */}
          <div className="p-4 overflow-x-auto scroll-thin mb-6 rounded-xl" id="roster-print"
               style={{ background: "var(--canvas)", border: "1px solid var(--hairline)" }}>
            <div className="print-header hidden print:block mb-4">
              <h2 className="text-2xl font-medium">{shop?.name} — Weekly Roster {roster.version}</h2>
              <p className="text-sm" style={{ color: "var(--ink-mute)" }}>
                Week of {roster.week_start}{roster.department ? ` · ${roster.department}` : ""}
              </p>
            </div>
            <div className="min-w-[1000px]">
              <div className="grid grid-cols-8 gap-2 mb-2 pb-2 border-b"
                   style={{ borderColor: "var(--hairline)" }}>
                <div className="flex items-baseline gap-2 py-2 pl-2">
                  <span className="eyebrow">Employee</span>
                  {customOrder && (
                    <button
                      type="button"
                      onClick={resetOrder}
                      data-testid="btn-reset-order"
                      title="Back to seniority order"
                      className="text-[11px] no-print hover:underline"
                      style={{ color: "var(--ink-mute-2)" }}
                    >
                      reset
                    </button>
                  )}
                </div>
                {DAYS.map((d) => {
                  const dt = dateForDay(week, d);
                  const dayGaps = gapsByDay[d] || [];
                  return (
                    <div
                      key={d}
                      className="text-center py-1.5 rounded-md"
                      style={dayGaps.length ? {
                        background: "var(--danger-soft)",
                        border: "1px solid var(--danger-hairline)",
                      } : undefined}
                    >
                      <div className="text-[13px] font-medium">{DAY_SHORT[d]}</div>
                      <div className="text-[11px] font-mono mt-0.5" style={{ color: "var(--ink-mute-2)" }}>
                        {fmtDayDate(dt)}
                      </div>
                      {dayGaps.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setSuggesting({ day: d, gaps: dayGaps })}
                          data-testid={`gap-${d}`}
                          className="mt-1 text-[10px] no-print hover:underline"
                          style={{ color: "var(--danger)" }}
                        >
                          {dayGaps.length}h unfilled
                        </button>
                      )}
                      {/* Re-solve just this day. Lives on the day header
                          because the day is already the subject there — and
                          it is hidden on an approved week, where nothing may
                          change without unapproving first. */}
                      {roster && !roster.approved && (
                        <button
                          type="button"
                          data-testid={`rebalance-${d}`}
                          disabled={generating}
                          onClick={() => generate(true, d)}
                          className="mt-1 text-[10px] no-print hover:underline block mx-auto disabled:opacity-40"
                          style={{ color: "var(--ink-mute-2)" }}
                          title={`Re-solve ${DAY_LABELS[d]} only — every other day stays exactly as it is`}
                        >
                          rebalance day
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
              {gridEmployees.map((e, rowIndex) => {
                // Paid hours, so a week of booked holiday reads as the hours
                // they are paid rather than as zero.
                const empHours = (roster.shifts || [])
                  .filter((s) => s.employee_id === e.employee_id)
                  .reduce((a, s) => a + shiftPaidHours(s), 0);
                return (
                  <div key={e.employee_id} className="grid grid-cols-8 gap-2 mb-1.5 items-stretch group">
                    <div className="flex items-center gap-1 px-2.5 py-2 rounded-md"
                         style={{ background: "var(--canvas-soft)" }}>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] truncate leading-tight">{e.name}</div>
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${roleClass(e.role)}`}>
                            {e.role}
                          </span>
                          <span className="text-[11px] font-mono" style={{ color: "var(--ink-mute)" }}>
                            {empHours.toFixed(1)}h
                          </span>
                        </div>
                      </div>
                      {/* Arrows rather than row dragging: the grid already
                          uses drag to move shifts between cells, and two
                          drag gestures on one surface is a coin toss. */}
                      <div className="flex flex-col shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity no-print">
                        <button
                          type="button"
                          data-testid={`move-up-${e.employee_id}`}
                          aria-label={`Move ${e.name} up`}
                          title="Move up"
                          disabled={rowIndex === 0}
                          onClick={() => moveEmployee(e.employee_id, -1)}
                          className="p-0.5 rounded disabled:opacity-20"
                          style={{ color: "var(--ink-mute)" }}
                        >
                          <ChevronUp size={13} />
                        </button>
                        <button
                          type="button"
                          data-testid={`move-down-${e.employee_id}`}
                          aria-label={`Move ${e.name} down`}
                          title="Move down"
                          disabled={rowIndex === gridEmployees.length - 1}
                          onClick={() => moveEmployee(e.employee_id, 1)}
                          className="p-0.5 rounded disabled:opacity-20"
                          style={{ color: "var(--ink-mute)" }}
                        >
                          <ChevronDown size={13} />
                        </button>
                      </div>
                    </div>
                    {DAYS.map((d) => {
                      const s = shiftsByDay[d].find((x) => x.employee_id === e.employee_id);
                      const dur = s ? shiftHours(s.start, s.end) : 0;
                      const confirm = s && needsConfirming.has(`${e.employee_id}|${d}`);
                      // Booked leave is not draggable. Moving it would shift
                      // the roster cell without moving the holiday record it
                      // came from, leaving the two disagreeing about which
                      // day the person is actually off.
                      const isLeave = !!s && (s.paid_holiday || s.unpaid_holiday || s.sick);
                      return (
                        <button
                          key={d}
                          data-testid={`cell-${e.employee_id}-${d}`}
                          draggable={!!s && !isLeave}
                          onDragStart={() => s && !isLeave && setDragging(s)}
                          onDragOver={(ev) => { if (dragging && !isLeave) ev.preventDefault(); }}
                          onDrop={(ev) => { ev.preventDefault(); if (dragging && !isLeave) moveShift(dragging, e.employee_id, d); setDragging(null); }}
                          onDragEnd={() => setDragging(null)}
                          onClick={() => {
                            // The edit dialog would open and then the save
                            // would fail with a 409. Saying so up front, and
                            // offering the way through, beats letting them
                            // retype a shift for nothing.
                            if (roster.approved) {
                              if (weekHasEnded) {
                                toast.error("This week has been worked and can no longer be changed");
                              } else if (s?.sick) {
                                setUndoSick({ ...s, employee_name: e.name });
                              } else if (s && !isLeave && s.start) {
                                // Somebody calling in is the one change an
                                // approved week has to accept: reopening the
                                // whole week to record one absence would
                                // take it out of learning and let it be
                                // regenerated underneath the manager.
                                setSickShift({ ...s, employee_name: e.name });
                              } else {
                                setConfirmUnapprove(true);
                              }
                              return;
                            }
                            setEditShift(s || { shift_id: `new_${Date.now()}`, employee_id: e.employee_id, day: d, start: "09:00", end: "17:00" });
                          }}
                          title={
                            roster.approved ? (s?.sick
                              ? "Marked sick — click to undo"
                              : s && !isLeave && s.start
                                ? "Approved — click to report sick and arrange cover"
                                : "Approved — unapprove the week to edit it")
                              : isLeave ? "Booked leave — change it on the Holidays page"
                                : s?.pinned ? "Pinned — kept when you rebalance"
                                  : confirm ? "Unfamiliar shift — please confirm" : undefined
                          }
                          className="min-h-[56px] rounded-md text-xs text-left"
                          style={{
                            // Flat, hairline-bordered cells. A filled colour
                            // block per cell would put ~200 saturated
                            // rectangles on screen and make the times harder
                            // to read, so the role lives in a 3px accent bar
                            // and the cell stays white.
                            background: s ? "var(--canvas-soft)" : "transparent",
                            border: s
                              ? `1px solid ${confirm ? "var(--warn-hairline)" : "var(--hairline)"}`
                              : "1px dashed var(--hairline)",
                            borderLeft: s
                              ? `3px solid ${isLeave ? "var(--hairline-strong)" : roleAccent(e.role)}`
                              : undefined,
                            boxShadow: confirm ? "inset 0 0 0 1px var(--warn-hairline)" : undefined,
                            cursor: !s ? "pointer" : isLeave ? "default" : "grab",
                            color: "var(--ink)",
                          }}
                        >
                          {s ? (
                            <div className="px-2 py-1.5">
                              <div className="flex items-start justify-between gap-1">
                                {s.paid_holiday ? (
                                  <span className="pill">Holiday</span>
                                ) : s.unpaid_holiday ? (
                                  <span className="pill">Unpaid</span>
                                ) : s.sick ? (
                                  <span className="pill pill-warn">Sick</span>
                                ) : (
                                  <span className="font-mono text-[12px] leading-tight">
                                    {s.start}–{s.end}
                                  </span>
                                )}
                                {/* Extra outranks the pin as a label: every
                                    extra shift is pinned too, and "pinned" is
                                    the less interesting of the two facts. */}
                                {s.extra ? (
                                  <UserPlus size={10} className="shrink-0 mt-0.5"
                                            style={{ color: "var(--accent)" }} />
                                ) : s.pinned ? (
                                  <Pin size={10} className="shrink-0 mt-0.5"
                                       style={{ color: "var(--ink-mute)" }} />
                                ) : null}
                                {confirm && (
                                  <HelpCircle size={11} className="shrink-0 mt-0.5"
                                              style={{ color: "var(--warn)" }} />
                                )}
                              </div>
                              {!s.paid_holiday && !s.unpaid_holiday && !s.sick && (
                                <div className="font-mono text-[11px] mt-0.5"
                                     style={{ color: "var(--ink-mute)" }}>
                                  {dur.toFixed(1)}h
                                </div>
                              )}
                              {s.extra && (
                                <div className="text-[10px] mt-1 truncate"
                                     style={{ color: "var(--accent)" }}
                                     title={s.extra_reason || "Extra cover"}>
                                  Extra{s.extra_reason ? ` · ${s.extra_reason}` : ""}
                                </div>
                              )}
                              {s.fixed && (
                                <div className="text-[10px] mt-1" style={{ color: "var(--ink-mute-2)" }}>
                                  Fixed
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="h-full flex items-center justify-center"
                                 style={{ color: "var(--ink-faint)" }}>+</div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Approve is the primary action once a roster exists, so it takes
              the emerald and Generate above it is the only other candidate —
              they are never both un-run at the same time. */}
          <div className="flex flex-wrap gap-2 no-print">
            {!roster.approved ? (
              <button data-testid="btn-approve" onClick={() => approve(false)} className="btn btn-primary">
                <Check size={14} /> Approve
              </button>
            ) : (
              <div className="btn btn-secondary" style={{ cursor: "default" }}>
                <Check size={14} /> Approved
              </div>
            )}
            {/* Repeated next to Approve as well as in the header, because this
                is where a manager looks when they want to change something and
                find the grid will not let them. */}
            {roster.approved && !weekHasEnded && (
              <button
                data-testid="btn-unapprove-inline"
                onClick={() => setConfirmUnapprove(true)}
                className="btn btn-ghost"
              >
                <Unlock size={14} /> Unapprove to edit
              </button>
            )}
            <button data-testid="btn-dispatch" onClick={() => setDispatchOpen(true)} className="btn btn-secondary">
              <Mail size={14} /> Email team
            </button>
            <button onClick={exportPDF} className="btn btn-secondary"><FileDown size={14} /> PDF</button>
            <button onClick={exportCSV} className="btn btn-secondary"><FileDown size={14} /> CSV</button>
            <button
              onClick={() => {
                const pages = parseInt(prompt("How many pages? (1-4)", "1") || "1", 10);
                document.documentElement.style.setProperty(
                  "--print-scale", String(1 / Math.max(1, Math.min(4, pages))),
                );
                setTimeout(() => window.print(), 50);
              }}
              className="btn btn-secondary"
            >
              <Printer size={14} /> Print
            </button>
          </div>

          {/* Version history */}
          {rosters.filter((r) => r.week_start === week).length > 1 && (
            <div className="mt-8 card p-5 no-print">
              <div className="text-sm font-medium mb-3">Versions this week</div>
              <div className="flex flex-wrap gap-2">
                {rosters.filter((r) => r.week_start === week).map((r) => {
                  const active = r.roster_id === roster.roster_id;
                  return (
                    <button
                      key={r.roster_id}
                      onClick={() => setRoster(r)}
                      className="px-2.5 py-1 rounded-md text-xs font-mono"
                      style={{
                        background: active ? "var(--ink)" : "var(--canvas)",
                        color: active ? "var(--canvas)" : "var(--ink-mute)",
                        border: `1px solid ${active ? "var(--ink)" : "var(--hairline)"}`,
                      }}
                    >
                      {r.version}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
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

const METRIC_TONES = {
  good: "var(--ink)",
  warn: "var(--warn)",
  bad: "var(--danger)",
};

function Metric({ label, value, suffix, tone }) {
  return (
    <div className="p-4" style={{ background: "var(--canvas-soft)" }}>
      <div className="eyebrow">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-1">
        <div
          className="text-[28px] font-mono leading-none"
          style={{ color: METRIC_TONES[tone] || "var(--ink)" }}
        >
          {value}
        </div>
        {suffix && (
          <div className="text-xs" style={{ color: "var(--ink-mute-2)" }}>{suffix}</div>
        )}
      </div>
    </div>
  );
}

const LEAVE_LABELS = {
  paid_holiday: "Paid holiday",
  unpaid_holiday: "Unpaid leave",
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

function DispatchModal({ roster, emps, onClose, onSend, sending, result }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-2xl w-full card elevated p-8 relative max-h-[85vh] overflow-y-auto scroll-thin" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="btn btn-ghost absolute top-3 right-3 p-2"><X size={16} /></button>
        <h2 className="mb-1">Dispatch <span className="font-mono">{roster.version}</span></h2>
        <p className="text-[13px] mb-6" style={{ color: "var(--ink-mute)" }}>
          Sending personal schedule cards to every employee by email.
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
            <button data-testid="btn-send-emails" onClick={onSend} disabled={sending} className="btn btn-primary w-full py-3">
              {sending ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
              {sending ? "Sending…" : `Send ${emps.length} emails`}
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
            <UserPlus size={15} style={{ color: "var(--accent)" }} /> Add extra staff
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
