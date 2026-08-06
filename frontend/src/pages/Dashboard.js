import React, { useEffect, useState } from "react";
import { api, fmtHours } from "@/lib/api";
import { useNavigate } from "react-router-dom";
import { Users, ShieldCheck, DollarSign, Activity, Sparkles, ArrowRight, Wand2 } from "lucide-react";
import { toast } from "sonner";

export default function Dashboard() {
  const [shop, setShop] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [rosters, setRosters] = useState([]);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const [s, e, r, a] = await Promise.all([
        api.get("/shop"), api.get("/employees"), api.get("/rosters"), api.get("/activity"),
      ]);
      setShop(s.data); setEmployees(e.data); setRosters(r.data); setActivity(a.data);
    } catch (err) {
      toast.error("Failed to load dashboard");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const latest = rosters[0];
  const seedDemo = async () => {
    await api.post("/seed-demo");
    toast.success("Demo team loaded");
    load();
  };

  if (loading) return <div className="text-white/60">Loading…</div>;

  return (
    <div className="max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Shop</div>
          <h1 className="text-4xl lg:text-5xl font-light">
            <span className="neon-text font-bold">{shop?.name}</span>
          </h1>
          <p className="text-white/50 mt-2 max-w-lg text-sm">
            {shop?.onboarded ? "Everything is set up. Generate this week's roster in one click." : "Complete onboarding to unlock 1-click roster generation."}
          </p>
        </div>
        <div className="flex gap-3 flex-wrap">
          {!shop?.onboarded && (
            <button data-testid="btn-onboarding" onClick={() => navigate("/onboarding")} className="px-5 py-2.5 rounded-full glass text-sm flex items-center gap-2">
              Complete setup <ArrowRight size={14} />
            </button>
          )}
          {employees.length === 0 && (
            <button data-testid="btn-seed" onClick={seedDemo} className="px-5 py-2.5 rounded-full glass-solid text-sm flex items-center gap-2">
              <Sparkles size={14} className="text-cyan-400" /> Load demo team
            </button>
          )}
          <button data-testid="btn-reset" onClick={async () => { if (window.confirm("Wipe ALL employees, rosters, rules and start fresh?")) { await api.post("/dev/reset"); toast.success("Data reset — shop is empty"); load(); } }} className="px-5 py-2.5 rounded-full text-xs text-red-400 border border-red-500/30 hover:bg-red-500/10">Reset all data</button>
          <button data-testid="btn-generate-roster" onClick={() => navigate("/roster")} className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2">
            <Wand2 size={14} /> Generate roster
          </button>
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        <KpiCard icon={<Users size={16} />} label="Team" value={employees.length} unit="people" testId="kpi-team" />
        <KpiCard icon={<ShieldCheck size={16} />} label="Compliance" value={latest?.compliance_score ?? "—"} unit={latest ? "score" : ""} accent testId="kpi-compliance" />
        <KpiCard icon={<DollarSign size={16} />} label="Weekly cost" value={latest ? `€${latest.labor_cost.toFixed(0)}` : "—"} unit={latest ? "EUR" : ""} testId="kpi-cost" />
        <KpiCard icon={<Activity size={16} />} label="Utilization" value={latest ? `${latest.utilization}%` : "—"} unit={latest ? "of capacity" : ""} testId="kpi-utilization" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 glass rounded-3xl p-8">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-medium">Recent rosters</h2>
            <button onClick={() => navigate("/roster")} className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
              Open roster <ArrowRight size={12} />
            </button>
          </div>
          {rosters.length === 0 ? (
            <div className="text-white/40 text-sm py-12 text-center">
              No rosters yet. Complete setup then click <span className="neon-text font-medium">Generate roster</span>.
            </div>
          ) : (
            <ul className="space-y-3">
              {rosters.slice(0, 5).map((r) => (
                <li key={r.roster_id} className="flex items-center justify-between glass-solid rounded-xl p-4">
                  <div>
                    <div className="text-sm font-medium">Week of {r.week_start} · <span className="neon-text">{r.version}</span></div>
                    <div className="text-xs text-white/40 font-mono mt-1">{fmtHours(r.total_hours)} · ${r.labor_cost.toFixed(0)} · score {r.compliance_score}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {r.issues?.length > 0 && <span className="conflict-dot" />}
                    {r.approved && <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">Approved</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="glass rounded-3xl p-8">
          <h2 className="text-xl font-medium mb-6">Activity</h2>
          {activity.length === 0 ? (
            <div className="text-white/40 text-sm py-6">No activity yet.</div>
          ) : (
            <ul className="space-y-4">
              {activity.slice(0, 8).map((a) => (
                <li key={a.log_id} className="text-sm">
                  <div className="text-white/80">{a.detail}</div>
                  <div className="text-[11px] text-white/40 font-mono mt-1">{new Date(a.created_at).toLocaleString()}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function KpiCard({ icon, label, value, unit, accent, testId }) {
  return (
    <div data-testid={testId} className={`rounded-2xl p-6 ${accent ? "neon-border" : "glass"}`}>
      <div className="flex items-center gap-2 text-xs text-white/50 uppercase tracking-wider">
        <span className="text-cyan-400">{icon}</span> {label}
      </div>
      <div className="mt-4 flex items-baseline gap-2">
        <div className="text-4xl font-light font-mono">{value}</div>
        {unit && <div className="text-xs text-white/40">{unit}</div>}
      </div>
    </div>
  );
}
