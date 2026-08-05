import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { CalendarPlus, Trash2, Store, User } from "lucide-react";

export default function CalendarPage() {
  const [hols, setHols] = useState([]);
  const [emps, setEmps] = useState([]);
  const [date, setDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState("shop");
  const scopeOpts = [{k:"shop",l:"Shop"},{k:"employee",l:"Holiday"},{k:"sick",l:"Sick"}];
  const [empId, setEmpId] = useState("");

  const load = async () => {
    const [h, e] = await Promise.all([api.get("/holidays"), api.get("/employees")]);
    setHols(h.data.sort((a, b) => a.date.localeCompare(b.date)));
    setEmps(e.data);
  };
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    try {
      await api.post("/holidays", { date, end_date: endDate || null, label, scope, employee_id: scope === "employee" ? empId : null });
      setDate(""); setEndDate(""); setLabel(""); setEmpId("");
      toast.success("Holiday added"); load();
    } catch (err) { toast.error(err.response?.data?.detail || "Failed"); }
  };

  const del = async (id) => {
    await api.delete(`/holidays/${id}`); toast.success("Removed"); load();
  };

  const empName = (id) => emps.find((e) => e.employee_id === id)?.name || "—";

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Calendar</div>
        <h1 className="text-4xl font-light">Holidays & off-days</h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form onSubmit={add} className="glass rounded-2xl p-6 space-y-4">
          <h2 className="font-medium">Add holiday</h2>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-white/60">Start date</label>
              <input data-testid="hol-date" required type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
            </div>
            <div>
              <label className="text-xs text-white/60">End date (optional)</label>
              <input data-testid="hol-end" type="date" value={endDate} min={date} onChange={(e) => setEndDate(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
            </div>
          </div>
          <div>
            <label className="text-xs text-white/60">Label</label>
            <input data-testid="hol-label" required value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Public holiday, vacation…" className="mt-1 w-full px-3 py-2.5 rounded-lg" />
          </div>
          <div>
            <label className="text-xs text-white/60">Scope</label>
            <div className="flex gap-2 mt-1">
              {scopeOpts.map((o) => (
                <button type="button" key={o.k} onClick={() => setScope(o.k)} className={`flex-1 px-3 py-2 rounded-lg text-xs ${scope === o.k ? "neon-btn" : "glass-solid text-white/60"}`}>
                  {o.l}
                </button>
              ))}
            </div>
            {scope === "sick" && <div className="text-[10px] text-amber-400 mt-2">Sick leave is temporary and never used by AI learning.</div>}
          </div>
          {(scope === "employee" || scope === "sick") && (
            <div>
              <label className="text-xs text-white/60">Employee</label>
              <select required value={empId} onChange={(e) => setEmpId(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg">
                <option value="">Select…</option>
                {emps.map((e) => <option key={e.employee_id} value={e.employee_id}>{e.name}</option>)}
              </select>
            </div>
          )}
          <button data-testid="btn-add-holiday" className="neon-btn w-full py-2.5 rounded-full text-sm flex items-center justify-center gap-2"><CalendarPlus size={14} /> Add holiday</button>
        </form>

        <div className="lg:col-span-2 glass rounded-2xl p-6">
          <h2 className="font-medium mb-4">Upcoming ({hols.length})</h2>
          {hols.length === 0 ? (
            <div className="text-white/40 text-sm py-10 text-center">No holidays configured.</div>
          ) : (
            <ul className="space-y-2">
              {hols.map((h) => (
                <li key={h.holiday_id} className="glass-solid rounded-xl p-4 flex items-center justify-between">
                  <div>
                    <div className="font-mono text-sm">{h.date}{h.end_date && h.end_date !== h.date ? ` → ${h.end_date}` : ""}</div>
                    <div className="text-xs text-white/60 mt-0.5">{h.label} · {h.scope === "shop" ? "Shop" : `Employee: ${empName(h.employee_id)}`}</div>
                  </div>
                  <button onClick={() => del(h.holiday_id)} className="text-red-400 hover:bg-red-500/10 p-2 rounded-lg"><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
