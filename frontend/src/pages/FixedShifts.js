import React, { useEffect, useState } from "react";
import { api, DAY_LABELS, DAYS } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Clock } from "lucide-react";

export default function FixedShifts() {
  const [items, setItems] = useState([]);
  const [emps, setEmps] = useState([]);
  const [empId, setEmpId] = useState("");
  const [days, setDays] = useState([]);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");

  const load = async () => {
    const [f, e] = await Promise.all([api.get("/fixed-shifts"), api.get("/employees")]);
    setItems(f.data); setEmps(e.data);
  };
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (days.length === 0) return toast.error("Pick at least one day");
    await api.post("/fixed-shifts", { employee_id: empId, days, start, end });
    setEmpId(""); setDays([]); toast.success("Fixed shift added"); load();
  };

  const del = async (id) => { await api.delete(`/fixed-shifts/${id}`); load(); };
  const empName = (id) => emps.find((e) => e.employee_id === id)?.name || "—";

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Templates</div>
        <h1 className="text-4xl font-light">Fixed & recurring shifts</h1>
        <p className="text-white/50 mt-2 text-sm max-w-lg">Pin an employee to specific days and times every week — the AI will honor these first.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form onSubmit={add} className="glass rounded-2xl p-6 space-y-4">
          <h2 className="font-medium">Add template</h2>
          <div>
            <label className="text-xs text-white/60">Employee</label>
            <select data-testid="fs-emp" required value={empId} onChange={(e) => setEmpId(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg">
              <option value="">Select…</option>
              {emps.map((e) => <option key={e.employee_id} value={e.employee_id}>{e.name} · {e.role}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-white/60">Days</label>
            <div className="flex gap-1.5 mt-1 flex-wrap">
              {DAYS.map((d) => {
                const on = days.includes(d);
                return (
                  <button type="button" key={d} onClick={() => setDays(on ? days.filter((x) => x !== d) : [...days, d])}
                    className={`px-3 py-1.5 rounded-full text-xs ${on ? "neon-btn" : "glass-solid text-white/60"}`}>{DAY_LABELS[d]}</button>
                );
              })}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-white/60">Start</label>
              <input required type="time" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
            </div>
            <div>
              <label className="text-xs text-white/60">End</label>
              <input required type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg font-mono" />
            </div>
          </div>
          <button data-testid="btn-add-fixed" className="neon-btn w-full py-2.5 rounded-full text-sm flex items-center justify-center gap-2"><Plus size={14} /> Save template</button>
        </form>

        <div className="lg:col-span-2 glass rounded-2xl p-6">
          <h2 className="font-medium mb-4">Templates ({items.length})</h2>
          {items.length === 0 ? (
            <div className="text-white/40 text-sm py-10 text-center">No templates yet.</div>
          ) : (
            <ul className="space-y-2">
              {items.map((it) => (
                <li key={it.fixed_id} className="glass-solid rounded-xl p-4 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Clock size={16} className="text-cyan-400" />
                    <div>
                      <div className="text-sm">{empName(it.employee_id)}</div>
                      <div className="text-xs text-white/50 font-mono mt-0.5">
                        {it.days.map((d) => DAY_LABELS[d]).join(", ")} · {it.start} – {it.end}
                      </div>
                    </div>
                  </div>
                  <button onClick={() => del(it.fixed_id)} className="text-red-400 hover:bg-red-500/10 p-2 rounded-lg"><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
