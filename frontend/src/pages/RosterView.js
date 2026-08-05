import React, { useEffect, useMemo, useState } from "react";
import { api, DAY_LABELS, DAY_SHORT, DAYS, mondayOf, fmtHours, roleClass, shiftHours, dateForDay, fmtDayDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Link } from "react-router-dom";
import { Crown } from "lucide-react";
import { toast } from "sonner";
import confetti from "canvas-confetti";
import jsPDF from "jspdf";
import { Wand2, Send, Check, FileDown, Printer, AlertTriangle, RefreshCw, Mail, X, Sparkles } from "lucide-react";

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

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await api.post("/roster/generate", { week_start: week, department });
      setRoster(r.data);
      toast.success(`Generated €{r.data.version} · compliance €{r.data.compliance_score}`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Generation failed");
    } finally { setGenerating(false); }
  };

  const approve = async () => {
    await api.post(`/rosters/€{roster.roster_id}/approve`);
    confetti({ particleCount: 140, spread: 80, origin: { y: 0.4 }, colors: ["#00E5FF", "#7C4DFF", "#ffffff"] });
    toast.success("Roster approved");
    load();
  };

  const dispatch = async () => {
    setDispatching(true);
    try {
      const r = await api.post(`/roster/€{roster.roster_id}/dispatch`);
      setDispatchResult(r.data);
      toast.success(`Sent €{r.data.sent.length} of €{r.data.total} emails`);
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

  const saveShift = async (payload) => {
    if (payload && shiftHours(payload.start, payload.end) > 11) {
      toast.error("Shift exceeds 11h limit"); return;
    }
    const shifts = (roster.shifts || []).filter((s) => s.shift_id !== editShift.shift_id);
    if (payload) {
      // Prevent duplicate emp+day
      const dup = shifts.find((s) => s.employee_id === payload.employee_id && s.day === payload.day);
      if (dup) { toast.error("Employee already has a shift that day"); return; }
      shifts.push(payload);
    }
    const clean = shifts.map(({ employee_id, day, start, end }) => ({ employee_id, day, start, end }));
    try {
      const r = await api.put(`/rosters/€{roster.roster_id}`, { shifts: clean });
      setRoster(r.data);
      setEditShift(null);
      toast.success(payload ? "Shift saved" : "Shift removed");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to save");
    }
  };

  const moveShift = async (shift, toEmpId, toDay) => {
    if (shift.employee_id === toEmpId && shift.day === toDay) return;
    const shifts = (roster.shifts || []).map((s) =>
      s.shift_id === shift.shift_id ? { ...s, employee_id: toEmpId, day: toDay } : s
    );
    const dup = shifts.filter((s) => s.shift_id !== shift.shift_id).find((s) => s.employee_id === toEmpId && s.day === toDay);
    if (dup) { toast.error("That slot already has a shift"); return; }
    const clean = shifts.map(({ employee_id, day, start, end }) => ({ employee_id, day, start, end }));
    try {
      const r = await api.put(`/rosters/€{roster.roster_id}`, { shifts: clean });
      setRoster(r.data);
      toast.success("Shift moved");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Move failed");
    }
  };

  const exportCSV = () => {
    const rows = [["Employee", "Role", "Department", "Day", "Date", "Start", "End", "Hours"]];
    (roster.shifts || []).forEach((s) => {
      const e = empMap[s.employee_id] || {};
      const hrs = shiftHours(s.start, s.end);
      const d = dateForDay(roster.week_start, s.day);
      rows.push([e.name, e.role, (e.departments || []).join("/"), DAY_LABELS[s.day], d.toISOString().slice(0,10), s.start, s.end, hrs.toFixed(1)]);
    });
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `roster-€{week}-€{roster.version}.csv`;
    a.click();
  };

  const exportPDF = () => {
    const pdf = new jsPDF({ orientation: "landscape" });
    // Header
    pdf.setFillColor(15, 15, 20); pdf.rect(0, 0, 297, 22, "F");
    pdf.setTextColor(255, 255, 255); pdf.setFontSize(18);
    pdf.text(shop?.name || "Roster", 14, 13);
    pdf.setFontSize(10); pdf.setTextColor(180);
    pdf.text(`Week of €{roster.week_start} · €{roster.version}€{roster.department ? " · " + roster.department : ""}`, 14, 19);
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
      const hrs = shiftHours(s.start, s.end);
      pdf.text(String(e.name || "").slice(0, 24), colX[0], y);
      pdf.text(String(e.role || ""), colX[1], y);
      pdf.text(DAY_LABELS[s.day], colX[2], y);
      pdf.text(fmtDayDate(d), colX[3], y);
      pdf.text(`€{s.start} – €{s.end}`, colX[4], y);
      pdf.text(`€{hrs.toFixed(1)}h`, colX[5], y);
      y += 6; if (y > 195) { pdf.addPage(); y = 20; }
    });
    // Footer
    pdf.setFontSize(8); pdf.setTextColor(120);
    pdf.text(`Compliance €{roster.compliance_score}/100 · Labor $€{roster.labor_cost.toFixed(0)} · €{roster.total_hours}h total`, 14, 205);
    pdf.save(`roster-€{week}-€{roster.version}.pdf`);
  };

  if (emps.length === 0) {
    return (
      <div className="max-w-2xl glass rounded-3xl p-12 text-center">
        <Wand2 size={40} className="mx-auto text-cyan-400 mb-4" />
        <h2 className="text-2xl font-light mb-2">No employees yet</h2>
        <p className="text-white/50 text-sm">Add employees or load the demo team first.</p>
      </div>
    );
  }

  return (
    <div className="max-w-full">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6 no-print">
        <div>
          <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Weekly Roster</div>
          <h1 className="text-4xl font-light">
            Week of <span className="font-mono neon-text">{week}</span>
            {roster && <span className="ml-3 text-sm text-white/50 font-mono">{roster.version}</span>}
          </h1>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          {shop?.multi_department && user?.pro && (
            <select data-testid="dept-switch" value={department || ""} onChange={(e) => setDepartment(e.target.value || null)} className="px-3 py-2 rounded-lg text-sm">
              <option value="">All departments</option>
              {(shop.departments || []).map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          <input data-testid="week-picker" type="date" value={week} onChange={(e) => setWeek(mondayOf(e.target.value))} className="px-3 py-2 rounded-lg font-mono text-sm" />
          <button data-testid="btn-generate" onClick={generate} disabled={generating || overLimit} className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2">
            {generating ? <RefreshCw size={14} className="animate-spin" /> : <Wand2 size={14} />}
            {roster ? "Regenerate" : "Generate"}
          </button>
        </div>
      </div>
      {overLimit && (
        <div className="glass rounded-2xl p-5 mb-6 flex items-center justify-between gap-4 flex-wrap border border-amber-500/30">
          <div className="flex items-center gap-3">
            <Crown size={18} className="text-cyan-400" />
            <div>
              <div className="text-sm font-medium">Free plan limit reached ({freeLimit} rosters)</div>
              <div className="text-xs text-white/50">Upgrade to Pro for unlimited generations, AI learning and multi-department.</div>
            </div>
          </div>
          <Link to="/pricing" className="neon-btn px-5 py-2 rounded-full text-sm">Upgrade</Link>
        </div>
      )}

      {roster && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 no-print">
            <Metric label="Compliance" value={roster.compliance_score} suffix="/100" accent />
            <Metric label="Weekly hours" value={fmtHours(roster.total_hours)} />
            <Metric label="Labor cost" value={`€€{roster.labor_cost.toFixed(0)}`} />
            <Metric label="Utilization" value={`€{roster.utilization}%`} />
          </div>

          {roster.ai_summary && (
            <div className="glass rounded-2xl p-5 mb-6 flex items-start gap-3 no-print">
              <Sparkles size={16} className="text-cyan-400 mt-0.5 shrink-0" />
              <div className="text-sm text-white/80">{roster.ai_summary}</div>
            </div>
          )}

          {roster.issues?.length > 0 && (
            <div className="glass rounded-2xl p-5 mb-6 no-print">
              <div className="flex items-center gap-2 text-red-400 mb-3">
                <AlertTriangle size={16} /><span className="text-sm font-medium">Conflicts ({roster.issues.length})</span>
              </div>
              <ul className="space-y-1 text-xs text-white/70">
                {roster.issues.map((i, idx) => <li key={idx}>• {i}</li>)}
              </ul>
            </div>
          )}

          {/* Weekly grid */}
          <div className="glass rounded-3xl p-4 overflow-x-auto scroll-thin mb-6" id="roster-print">
            <div className="print-header hidden print:block mb-4">
              <h2 className="text-2xl font-bold text-black">{shop?.name} — Weekly Roster {roster.version}</h2>
              <p className="text-sm text-gray-700">Week of {roster.week_start}{roster.department ? ` · €{roster.department}` : ""}</p>
            </div>
            <div className="min-w-[1000px]">
              <div className="grid grid-cols-8 gap-2 mb-3">
                <div className="text-xs text-white/40 uppercase tracking-wider py-2 pl-3">Employee</div>
                {DAYS.map((d) => {
                  const dt = dateForDay(week, d);
                  return (
                    <div key={d} className="text-center py-2">
                      <div className="text-sm text-white/80 font-medium">{DAY_SHORT[d]}</div>
                      <div className="text-[10px] font-mono text-cyan-400 mt-0.5">{fmtDayDate(dt)}</div>
                    </div>
                  );
                })}
              </div>
              {emps.map((e) => {
                const empHours = (roster.shifts || []).filter((s) => s.employee_id === e.employee_id).reduce((a, s) => a + shiftHours(s.start, s.end), 0);
                return (
                  <div key={e.employee_id} className="grid grid-cols-8 gap-2 mb-2 items-stretch">
                    <div className="flex items-center gap-2 bg-[#0A0B10] rounded-lg px-3 py-2">
                      <img src={e.avatar} alt="" className="w-8 h-8 rounded-full object-cover border border-white/10" />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm truncate">{e.name}</div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded €{roleClass(e.role)}`}>{e.role}</span>
                          <span className="text-[10px] font-mono text-white/50">{empHours.toFixed(1)}h</span>
                        </div>
                      </div>
                    </div>
                    {DAYS.map((d) => {
                      const s = shiftsByDay[d].find((x) => x.employee_id === e.employee_id);
                      const dur = s ? shiftHours(s.start, s.end) : 0;
                      return (
                        <button
                          key={d}
                          data-testid={`cell-€{e.employee_id}-€{d}`}
                          draggable={!!s}
                          onDragStart={() => s && setDragging(s)}
                          onDragOver={(ev) => { if (dragging) ev.preventDefault(); }}
                          onDrop={(ev) => { ev.preventDefault(); if (dragging) moveShift(dragging, e.employee_id, d); setDragging(null); }}
                          onDragEnd={() => setDragging(null)}
                          onClick={() => setEditShift(s || { shift_id: `new_€{Date.now()}`, employee_id: e.employee_id, day: d, start: "09:00", end: "17:00" })}
                          className={`min-h-[64px] rounded-lg text-xs transition-colors ${
                            s ? `€{roleClass(e.role)} hover:brightness-125 cursor-grab active:cursor-grabbing` : "bg-white/[0.02] border border-dashed border-white/10 hover:border-white/30 text-white/30"
                          }`}
                        >
                          {s ? (
                            <div className="p-2 text-left">
                              <div className="font-mono text-xs">{s.start}–{s.end}</div>
                              <div className="font-mono text-[10px] opacity-80 mt-0.5">{dur.toFixed(1)}h</div>
                              {s.fixed && <div className="text-[9px] mt-1 opacity-70">FIXED</div>}
                            </div>
                          ) : "+"}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex flex-wrap gap-2 no-print">
            {!roster.approved ? (
              <button data-testid="btn-approve" onClick={approve} className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2"><Check size={14} /> Approve</button>
            ) : (
              <div className="px-5 py-2.5 rounded-full glass-solid text-sm text-emerald-400 flex items-center gap-2 border border-emerald-500/30"><Check size={14} /> Approved</div>
            )}
            <button data-testid="btn-dispatch" onClick={() => setDispatchOpen(true)} className="px-5 py-2.5 rounded-full glass-solid text-sm flex items-center gap-2"><Mail size={14} /> Email team</button>
            <button onClick={exportPDF} className="px-5 py-2.5 rounded-full glass-solid text-sm flex items-center gap-2"><FileDown size={14} /> PDF</button>
            <button onClick={exportCSV} className="px-5 py-2.5 rounded-full glass-solid text-sm flex items-center gap-2"><FileDown size={14} /> CSV</button>
            <button onClick={() => { const pages = parseInt(prompt("How many pages? (1-4)", "1") || "1"); document.documentElement.style.setProperty('--print-scale', String(1 / Math.max(1, Math.min(4, pages)))); setTimeout(() => window.print(), 50); }} className="px-5 py-2.5 rounded-full glass-solid text-sm flex items-center gap-2"><Printer size={14} /> Print</button>
          </div>

          {/* Version history */}
          {rosters.filter((r) => r.week_start === week).length > 1 && (
            <div className="mt-8 glass rounded-2xl p-5 no-print">
              <div className="text-sm font-medium mb-3">Versions this week</div>
              <div className="flex flex-wrap gap-2">
                {rosters.filter((r) => r.week_start === week).map((r) => (
                  <button key={r.roster_id} onClick={() => setRoster(r)} className={`px-3 py-1.5 rounded-full text-xs font-mono €{r.roster_id === roster.roster_id ? "neon-btn" : "glass-solid text-white/60"}`}>
                    {r.version}
                  </button>
                ))}
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
          isNew={editShift.shift_id?.startsWith("new_")}
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

function Metric({ label, value, suffix, accent }) {
  return (
    <div className={`rounded-2xl p-5 €{accent ? "neon-border" : "glass"}`}>
      <div className="text-[11px] text-white/50 uppercase tracking-wider">{label}</div>
      <div className="mt-2 flex items-baseline gap-1">
        <div className="text-3xl font-light font-mono">{value}</div>
        {suffix && <div className="text-xs text-white/40">{suffix}</div>}
      </div>
    </div>
  );
}

function ShiftModal({ shift, employee, onClose, onSave, onDelete, isNew }) {
  const [start, setStart] = useState(shift.start);
  const [end, setEnd] = useState(shift.end);
  const under16 = employee?.age < 16;
  const conflict = under16 && (start < "08:00" || end > "19:00");

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-md w-full bg-[#0A0B10] border border-white/10 rounded-3xl p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute top-4 right-4 text-white/40 hover:text-white"><X size={16} /></button>
        <div className="flex items-center gap-3 mb-6">
          <img src={employee?.avatar} alt="" className="w-10 h-10 rounded-full object-cover" />
          <div>
            <div className="font-medium">{employee?.name}</div>
            <div className="text-xs text-white/50">{DAY_LABELS[shift.day]} · {isNew ? "New shift" : "Edit shift"}</div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-white/60">Start</label>
            <input data-testid="edit-start" type="time" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
          </div>
          <div>
            <label className="text-xs text-white/60">End</label>
            <input data-testid="edit-end" type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
          </div>
        </div>
        {conflict && (
          <div className="mt-4 text-xs text-red-400 flex items-center gap-2"><AlertTriangle size={12} /> Under-16 curfew: shift must be within 08:00–19:00.</div>
        )}
        <div className="flex gap-2 mt-6">
          <button onClick={() => onSave({ shift_id: shift.shift_id, employee_id: shift.employee_id, day: shift.day, start, end, fixed: false })} className="neon-btn flex-1 py-2.5 rounded-full text-sm">Save</button>
          {!isNew && <button onClick={onDelete} className="px-4 py-2.5 rounded-full text-red-400 border border-red-500/30 hover:bg-red-500/10 text-sm">Remove</button>}
        </div>
      </div>
    </div>
  );
}

function DispatchModal({ roster, emps, onClose, onSend, sending, result }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-2xl w-full bg-[#0A0B10] border border-white/10 rounded-3xl p-8 relative max-h-[85vh] overflow-y-auto scroll-thin" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute top-4 right-4 text-white/40 hover:text-white"><X size={16} /></button>
        <h2 className="text-2xl font-light mb-2">Dispatch <span className="neon-text font-medium">{roster.version}</span></h2>
        <p className="text-sm text-white/50 mb-6">Sending personal schedule cards to every employee via email.</p>

        {!result ? (
          <>
            <div className="grid grid-cols-2 gap-3 mb-6">
              {emps.map((e) => {
                const count = roster.shifts.filter((s) => s.employee_id === e.employee_id).length;
                return (
                  <div key={e.employee_id} className="glass-solid rounded-xl p-3 flex items-center gap-3">
                    <img src={e.avatar} alt="" className="w-9 h-9 rounded-full object-cover" />
                    <div className="min-w-0">
                      <div className="text-sm truncate">{e.name}</div>
                      <div className="text-[11px] text-white/40 truncate">{e.email}</div>
                      <div className="text-[10px] text-cyan-400 font-mono mt-0.5">{count} shift{count !== 1 ? "s" : ""}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            <button data-testid="btn-send-emails" onClick={onSend} disabled={sending} className="neon-btn w-full py-3 rounded-full text-sm flex items-center justify-center gap-2">
              {sending ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
              {sending ? "Sending…" : `Send €{emps.length} emails`}
            </button>
          </>
        ) : (
          <div>
            <div className="glass-solid rounded-xl p-4 mb-4">
              <div className="text-sm">
                <span className="text-emerald-400 font-mono">{result.sent.length}</span> sent · <span className="text-red-400 font-mono">{result.failed.length}</span> failed
              </div>
            </div>
            <ul className="space-y-2 max-h-80 overflow-y-auto scroll-thin">
              {result.sent.map((s) => (
                <li key={s.employee_id} className="text-xs text-white/70 flex items-center gap-2"><Check size={12} className="text-emerald-400" /> {s.name} · {s.email}</li>
              ))}
              {result.failed.map((s) => (
                <li key={s.employee_id} className="text-xs text-red-400 flex items-start gap-2"><X size={12} className="mt-0.5" /> <div><div>{s.name} · {s.email}</div><div className="text-white/40">{s.error}</div></div></li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
