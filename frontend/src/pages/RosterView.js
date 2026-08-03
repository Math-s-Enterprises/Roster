import React, { useEffect, useMemo, useState } from "react";
import { api, DAY_LABELS, DAYS, mondayOf, fmtHours, roleClass } from "@/lib/api";
import { toast } from "sonner";
import confetti from "canvas-confetti";
import jsPDF from "jspdf";
import { Wand2, Send, Check, FileDown, Printer, AlertTriangle, RefreshCw, Mail, X, Sparkles } from "lucide-react";

export default function RosterView() {
  const [week, setWeek] = useState(mondayOf());
  const [roster, setRoster] = useState(null);
  const [emps, setEmps] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [rosters, setRosters] = useState([]);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState(null);
  const [editShift, setEditShift] = useState(null);

  const load = async () => {
    const [e, r] = await Promise.all([api.get("/employees"), api.get("/rosters")]);
    setEmps(e.data); setRosters(r.data);
    const found = r.data.find((x) => x.week_start === week);
    if (found) setRoster(found);
    else setRoster(null);
  };
  useEffect(() => { load(); }, [week]);

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await api.post("/roster/generate", { week_start: week });
      setRoster(r.data);
      toast.success(`Generated ${r.data.version} · compliance ${r.data.compliance_score}`);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Generation failed");
    } finally { setGenerating(false); }
  };

  const approve = async () => {
    await api.post(`/rosters/${roster.roster_id}/approve`);
    confetti({ particleCount: 140, spread: 80, origin: { y: 0.4 }, colors: ["#00E5FF", "#7C4DFF", "#ffffff"] });
    toast.success("Roster approved");
    load();
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

  const saveShift = async (payload) => {
    const shifts = (roster.shifts || []).filter((s) => s.shift_id !== editShift.shift_id);
    if (payload) shifts.push(payload);
    const clean = shifts.map(({ employee_id, day, start, end }) => ({ employee_id, day, start, end }));
    const r = await api.put(`/rosters/${roster.roster_id}`, { shifts: clean });
    setRoster(r.data);
    setEditShift(null);
    toast.success(payload ? "Shift saved" : "Shift removed");
  };

  const exportCSV = () => {
    const rows = [["Employee", "Role", "Day", "Start", "End", "Hours"]];
    (roster.shifts || []).forEach((s) => {
      const e = empMap[s.employee_id] || {};
      const hrs = (parseInt(s.end.split(":")[0]) * 60 + parseInt(s.end.split(":")[1]) - parseInt(s.start.split(":")[0]) * 60 - parseInt(s.start.split(":")[1])) / 60;
      rows.push([e.name, e.role, DAY_LABELS[s.day], s.start, s.end, hrs.toFixed(1)]);
    });
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `roster-${week}-${roster.version}.csv`;
    a.click();
  };

  const exportPDF = () => {
    const pdf = new jsPDF();
    pdf.setFontSize(16); pdf.text(`Roster ${roster.version} · week of ${week}`, 14, 20);
    pdf.setFontSize(10); let y = 32;
    (roster.shifts || []).forEach((s) => {
      const e = empMap[s.employee_id] || {};
      pdf.text(`${DAY_LABELS[s.day]}  ${s.start}–${s.end}  ·  ${e.name} (${e.role})`, 14, y);
      y += 6; if (y > 280) { pdf.addPage(); y = 20; }
    });
    pdf.save(`roster-${week}-${roster.version}.pdf`);
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
          <input data-testid="week-picker" type="date" value={week} onChange={(e) => setWeek(mondayOf(e.target.value))} className="px-3 py-2 rounded-lg font-mono text-sm" />
          <button data-testid="btn-generate" onClick={generate} disabled={generating} className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2">
            {generating ? <RefreshCw size={14} className="animate-spin" /> : <Wand2 size={14} />}
            {roster ? "Regenerate" : "Generate"}
          </button>
        </div>
      </div>

      {roster && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 no-print">
            <Metric label="Compliance" value={roster.compliance_score} suffix="/100" accent />
            <Metric label="Weekly hours" value={fmtHours(roster.total_hours)} />
            <Metric label="Labor cost" value={`$${roster.labor_cost.toFixed(0)}`} />
            <Metric label="Utilization" value={`${roster.utilization}%`} />
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
          <div className="glass rounded-3xl p-4 overflow-x-auto scroll-thin mb-6">
            <div className="min-w-[900px]">
              <div className="grid grid-cols-8 gap-2 mb-3 sticky top-0">
                <div className="text-xs text-white/40 uppercase tracking-wider py-2 pl-3">Employee</div>
                {DAYS.map((d) => (
                  <div key={d} className="text-xs text-white/40 uppercase tracking-wider text-center py-2">{DAY_LABELS[d]}</div>
                ))}
              </div>
              {emps.map((e) => (
                <div key={e.employee_id} className="grid grid-cols-8 gap-2 mb-2 items-stretch">
                  <div className="flex items-center gap-2 bg-[#0A0B10] rounded-lg px-3 py-2">
                    <img src={e.avatar} alt="" className="w-8 h-8 rounded-full object-cover border border-white/10" />
                    <div className="min-w-0">
                      <div className="text-sm truncate">{e.name}</div>
                      <div className={`text-[10px] px-1.5 py-0.5 rounded inline-block mt-0.5 ${roleClass(e.role)}`}>{e.role}</div>
                    </div>
                  </div>
                  {DAYS.map((d) => {
                    const s = shiftsByDay[d].find((x) => x.employee_id === e.employee_id);
                    return (
                      <button
                        key={d}
                        data-testid={`cell-${e.employee_id}-${d}`}
                        onClick={() => setEditShift(s || { shift_id: `new_${Date.now()}`, employee_id: e.employee_id, day: d, start: "09:00", end: "17:00" })}
                        className={`min-h-[52px] rounded-lg text-xs transition-colors ${
                          s ? `${roleClass(e.role)} hover:brightness-125` : "bg-white/[0.02] border border-dashed border-white/10 hover:border-white/30 text-white/30"
                        }`}
                      >
                        {s ? (
                          <div className="p-2 text-left">
                            <div className="font-mono">{s.start}</div>
                            <div className="font-mono text-[10px] opacity-80">→ {s.end}</div>
                            {s.fixed && <div className="text-[9px] mt-1 opacity-70">FIXED</div>}
                          </div>
                        ) : "+"}
                      </button>
                    );
                  })}
                </div>
              ))}
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
            <button onClick={() => window.print()} className="px-5 py-2.5 rounded-full glass-solid text-sm flex items-center gap-2"><Printer size={14} /> Print</button>
          </div>

          {/* Version history */}
          {rosters.filter((r) => r.week_start === week).length > 1 && (
            <div className="mt-8 glass rounded-2xl p-5 no-print">
              <div className="text-sm font-medium mb-3">Versions this week</div>
              <div className="flex flex-wrap gap-2">
                {rosters.filter((r) => r.week_start === week).map((r) => (
                  <button key={r.roster_id} onClick={() => setRoster(r)} className={`px-3 py-1.5 rounded-full text-xs font-mono ${r.roster_id === roster.roster_id ? "neon-btn" : "glass-solid text-white/60"}`}>
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
    <div className={`rounded-2xl p-5 ${accent ? "neon-border" : "glass"}`}>
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
              {sending ? "Sending…" : `Send ${emps.length} emails`}
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
