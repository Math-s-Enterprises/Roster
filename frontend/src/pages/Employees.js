import React, { useEffect, useState } from "react";
import { api, roleClass, DAY_LABELS, DAYS } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, AlertTriangle, X } from "lucide-react";

const emptyForm = {
  name: "", email: "", role: "Cashier", age: 22, hourly_rate: 15, max_weekly_hours: 40, preferred_days_off: [],
};

export default function Employees() {
  const [emps, setEmps] = useState([]);
  const [shop, setShop] = useState(null);
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(emptyForm);

  const load = async () => {
    const [e, s] = await Promise.all([api.get("/employees"), api.get("/shop")]);
    setEmps(e.data); setShop(s.data);
  };
  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    try {
      if (modal === "edit") {
        await api.put(`/employees/€{form.employee_id}`, form);
        toast.success("Employee updated");
      } else {
        await api.post("/employees", form);
        toast.success("Employee added");
      }
      setModal(null); setForm(emptyForm); load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const del = async (id) => {
    if (!window.confirm("Remove this employee?")) return;
    await api.delete(`/employees/€{id}`); toast.success("Removed"); load();
  };

  return (
    <div className="max-w-7xl">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Team</div>
          <h1 className="text-4xl font-light">Employees</h1>
        </div>
        <button data-testid="btn-add-employee" onClick={() => { setForm(emptyForm); setModal("new"); }} className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2">
          <Plus size={14} /> Add employee
        </button>
      </div>

      {emps.length === 0 ? (
        <div className="glass rounded-3xl p-12 text-center text-white/50">
          No employees yet. Add your first team member to start scheduling.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {emps.map((e) => (
            <div key={e.employee_id} data-testid={`employee-card-€{e.employee_id}`} className="glass rounded-2xl p-6 relative">
              <div className="flex gap-4">
                <img src={e.avatar} alt={e.name} className="w-14 h-14 rounded-full object-cover border border-white/10" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{e.name}</div>
                  <div className="text-[11px] text-white/40 truncate">{e.email}</div>
                  <div className="mt-2 flex items-center gap-2 flex-wrap">
                    <span className={`text-[11px] px-2 py-0.5 rounded-md €{roleClass(e.role)}`}>{e.role}</span>
                    {e.age < 16 && (
                      <span className="text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center gap-1">
                        <AlertTriangle size={10} /> Under 16
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 mt-4 text-xs">
                <Stat label="Age" value={e.age} />
                <Stat label="Rate" value={`€€{e.hourly_rate}`} />
                <Stat label="Max" value={`€{e.max_weekly_hours}h`} />
              </div>
              {e.preferred_days_off?.length > 0 && (
                <div className="mt-4 text-[11px] text-white/50">
                  Off: <span className="text-white/70 font-mono">{e.preferred_days_off.map((d) => DAY_LABELS[d]).join(", ")}</span>
                </div>
              )}
              <div className="flex gap-2 mt-4">
                <button data-testid={`btn-edit-€{e.employee_id}`} onClick={() => { setForm(e); setModal("edit"); }} className="flex-1 px-3 py-2 rounded-lg glass-solid text-xs flex items-center justify-center gap-1"><Pencil size={12} /> Edit</button>
                <button onClick={() => del(e.employee_id)} className="px-3 py-2 rounded-lg text-red-400 hover:bg-red-500/10 text-xs"><Trash2 size={12} /></button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <Modal onClose={() => setModal(null)}>
          <form onSubmit={submit} className="space-y-4">
            <h2 className="text-2xl font-light mb-4">{modal === "edit" ? "Edit" : "New"} employee</h2>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name"><input data-testid="emp-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full px-3 py-2.5 rounded-lg" /></Field>
              <Field label="Email"><input data-testid="emp-email" required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="w-full px-3 py-2.5 rounded-lg" /></Field>
              <Field label="Role">
                <select data-testid="emp-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="w-full px-3 py-2.5 rounded-lg">
                  {shop?.roles?.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </Field>
              <Field label="Age"><input data-testid="emp-age" type="number" min={14} max={80} required value={form.age} onChange={(e) => setForm({ ...form, age: Number(e.target.value) })} className="w-full px-3 py-2.5 rounded-lg font-mono" /></Field>
              <Field label="Hourly rate ($)"><input data-testid="emp-rate" type="number" step="0.5" required value={form.hourly_rate} onChange={(e) => setForm({ ...form, hourly_rate: Number(e.target.value) })} className="w-full px-3 py-2.5 rounded-lg font-mono" /></Field>
              <Field label="Max weekly hours">
                <select data-testid="emp-max" value={form.max_weekly_hours} onChange={(e) => setForm({ ...form, max_weekly_hours: Number(e.target.value) })} className="w-full px-3 py-2.5 rounded-lg font-mono">
                  <option value={20}>20h (part-time)</option>
                  <option value={30}>30h</option>
                  <option value={40}>40h (full-time)</option>
                </select>
              </Field>
            </div>
            <Field label="Preferred days off">
              <div className="flex gap-2 flex-wrap">
                {DAYS.map((d) => {
                  const on = form.preferred_days_off.includes(d);
                  return (
                    <button type="button" key={d} onClick={() => setForm({ ...form, preferred_days_off: on ? form.preferred_days_off.filter((x) => x !== d) : [...form.preferred_days_off, d] })}
                      className={`px-3 py-1.5 rounded-full text-xs €{on ? "neon-btn" : "glass-solid text-white/70"}`}>
                      {DAY_LABELS[d]}
                    </button>
                  );
                })}
              </div>
            </Field>
            {form.age < 16 && (
              <div className="text-xs text-amber-400 flex items-center gap-2"><AlertTriangle size={12} /> Under-16 curfew rule will apply: no shifts before 08:00 or after 19:00.</div>
            )}
            <button data-testid="btn-save-employee" className="neon-btn w-full py-3 rounded-full text-sm">Save</button>
          </form>
        </Modal>
      )}
    </div>
  );
}

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

function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="max-w-lg w-full bg-[#0A0B10] border border-white/10 rounded-3xl p-8 relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute top-4 right-4 text-white/40 hover:text-white"><X size={16} /></button>
        {children}
      </div>
    </div>
  );
}
