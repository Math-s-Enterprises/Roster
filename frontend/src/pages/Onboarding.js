import React, { useEffect, useState } from "react";
import { api, DAY_LABELS, DAYS } from "@/lib/api";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { ChevronRight, ChevronLeft, Check } from "lucide-react";

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [shop, setShop] = useState(null);
  const [name, setName] = useState("");
  const [hours, setHours] = useState([]);
  const [minShift, setMinShift] = useState(4);
  const [maxShift, setMaxShift] = useState(9);
  const [roles, setRoles] = useState([]);
  const [newRole, setNewRole] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    api.get("/shop").then((r) => {
      setShop(r.data); setName(r.data.name);
      setHours(r.data.hours); setMinShift(r.data.min_shift_hours);
      setMaxShift(r.data.max_shift_hours); setRoles(r.data.roles);
    });
  }, []);

  const save = async (extra = {}) => {
    await api.put("/shop", { name, hours, min_shift_hours: minShift, max_shift_hours: maxShift, roles, ...extra });
  };

  const finish = async () => {
    await save({ onboarded: true });
    toast.success("Setup complete — you're ready to roster.");
    nav("/");
  };

  if (!shop) return <div className="text-white/60">Loading…</div>;

  const steps = [
    { title: "Shop identity", desc: "Give your shop a name your team will recognize." },
    { title: "Opening hours", desc: "Set weekly opening and closing times." },
    { title: "Shift limits", desc: "Minimum and maximum shift lengths." },
    { title: "Roles", desc: "Define the roles you schedule against." },
  ];

  return (
    <div className="max-w-3xl">
      <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Onboarding · step {step + 1} of {steps.length}</div>
      <h1 className="text-4xl font-light mb-2">{steps[step].title}</h1>
      <p className="text-white/50 mb-8">{steps[step].desc}</p>

      <div className="glass rounded-3xl p-8">
        {step === 0 && (
          <div className="space-y-4">
            <label className="text-xs text-white/60">Shop name</label>
            <input data-testid="input-shop-name" value={name} onChange={(e) => setName(e.target.value)} className="w-full px-4 py-3 rounded-xl" />
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            {hours.map((h, i) => (
              <div key={h.day} className="flex items-center gap-3">
                <div className="w-14 text-sm">{DAY_LABELS[h.day]}</div>
                <label className="flex items-center gap-2 text-xs text-white/60">
                  <input
                    type="checkbox"
                    checked={!h.closed}
                    onChange={(e) => {
                      const n = [...hours]; n[i] = { ...h, closed: !e.target.checked }; setHours(n);
                    }}
                  /> Open
                </label>
                <input type="time" value={h.open} disabled={h.closed}
                  onChange={(e) => { const n = [...hours]; n[i] = { ...h, open: e.target.value }; setHours(n); }}
                  className="px-3 py-2 rounded-lg font-mono" />
                <span className="text-white/40 text-sm">to</span>
                <input type="time" value={h.close} disabled={h.closed}
                  onChange={(e) => { const n = [...hours]; n[i] = { ...h, close: e.target.value }; setHours(n); }}
                  className="px-3 py-2 rounded-lg font-mono" />
              </div>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-white/60">Min shift hours</label>
              <input data-testid="input-min-shift" type="number" min={1} max={8} value={minShift} onChange={(e) => setMinShift(Number(e.target.value))} className="mt-1 w-full px-4 py-3 rounded-xl font-mono" />
            </div>
            <div>
              <label className="text-xs text-white/60">Max shift hours</label>
              <input data-testid="input-max-shift" type="number" min={4} max={12} value={maxShift} onChange={(e) => setMaxShift(Number(e.target.value))} className="mt-1 w-full px-4 py-3 rounded-xl font-mono" />
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {roles.map((r) => (
                <div key={r} className="px-3 py-1.5 rounded-full glass-solid text-sm flex items-center gap-2">
                  {r}
                  <button className="text-white/40 hover:text-red-400" onClick={() => setRoles(roles.filter((x) => x !== r))}>×</button>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input data-testid="input-new-role" value={newRole} onChange={(e) => setNewRole(e.target.value)} placeholder="Add a role" className="flex-1 px-4 py-2.5 rounded-xl" />
              <button onClick={() => { if (newRole) { setRoles([...roles, newRole]); setNewRole(""); } }} className="px-4 py-2.5 rounded-xl glass-solid text-sm">Add</button>
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-between mt-8">
        <button disabled={step === 0} onClick={() => setStep(step - 1)} className="px-5 py-2.5 rounded-full glass text-sm flex items-center gap-2 disabled:opacity-40">
          <ChevronLeft size={14} /> Back
        </button>
        {step < steps.length - 1 ? (
          <button data-testid="btn-next" onClick={async () => { await save(); setStep(step + 1); }} className="neon-btn px-6 py-2.5 rounded-full text-sm flex items-center gap-2">
            Continue <ChevronRight size={14} />
          </button>
        ) : (
          <button data-testid="btn-finish" onClick={finish} className="neon-btn px-6 py-2.5 rounded-full text-sm flex items-center gap-2">
            Finish <Check size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
