import React, { useEffect, useState } from "react";
import { api, fmtHours, fmtMoney } from "@/lib/api";
import { useNavigate } from "react-router-dom";
import { Users, ShieldCheck, Euro, Activity, Sparkles, ArrowRight, Wand2, CheckCircle2, HelpCircle } from "lucide-react";
import { toast } from "sonner";

export default function Dashboard() {
  const [shop, setShop] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [rosters, setRosters] = useState([]);
  const [activity, setActivity] = useState([]);
  const [setup, setSetup] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const [s, e, r, a, st] = await Promise.all([
        api.get("/shop"), api.get("/employees"), api.get("/rosters"), api.get("/activity"),
        api.get("/setup-status"),
      ]);
      setShop(s.data); setEmployees(e.data); setRosters(r.data); setActivity(a.data);
      setSetup(st.data);
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
          {/* Reads from the checklist, not from `onboarded`. That flag only
              means the shop wizard was finished, and the page used to
              announce "Everything is set up" at the exact moment a new shop
              had no staff, no history and no fixed shifts. */}
          <p className="text-white/50 mt-2 max-w-lg text-sm">
            {setup?.complete
              ? "Everything is set up. Generate this week's roster in one click."
              : setup
                ? `${setup.done} of ${setup.total} setup steps done — see below.`
                : ""}
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

      {setup && <GettingStarted setup={setup} />}

      {/* KPI grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        <KpiCard icon={<Users size={16} />} label="Team" value={employees.length} unit="people" testId="kpi-team" />
        <KpiCard icon={<ShieldCheck size={16} />} label="Compliance" value={latest?.compliance_score ?? "—"} unit={latest ? "score" : ""} accent testId="kpi-compliance" />
        <KpiCard icon={<Euro size={16} />} label="Weekly cost" value={latest ? fmtMoney(latest.labor_cost) : "—"} unit={latest ? "EUR" : ""} testId="kpi-cost" />
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
                    <div className="text-xs text-white/40 font-mono mt-1">{fmtHours(r.total_hours)} · {fmtMoney(r.labor_cost)} · score {r.compliance_score}</div>
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

/**
 * What to do next, and why it matters.
 *
 * Ordered so each step makes the next one worth doing: import before adding
 * staff by hand, because the import creates everyone named on the sheet;
 * employment types before generating, because they decide contracted hours
 * and a roster built on the wrong contract has to be thrown away rather than
 * corrected.
 *
 * Every step's state comes from the server, which derives it from the data
 * rather than from a stored "step 3 done" flag. A flag would keep claiming
 * success after the data behind it was deleted — precisely when a new user
 * most needs to be told the truth.
 *
 * Collapses to one line once finished instead of disappearing, so the
 * walkthrough stays reachable.
 */
function GettingStarted({ setup }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(!setup.complete);
  const [explain, setExplain] = useState(false);

  const pct = Math.round((setup.done / Math.max(1, setup.total)) * 100);

  if (setup.complete && !open) {
    return (
      <div className="card p-4 mb-8 flex items-center gap-3 text-[13px]">
        <CheckCircle2 size={16} style={{ color: "var(--primary)" }} />
        <span>Setup complete.</span>
        <button onClick={() => setOpen(true)} className="btn btn-ghost ml-auto text-[12px]">
          Review steps
        </button>
      </div>
    );
  }

  return (
    <div className="card p-6 mb-8">
      <div className="flex items-start justify-between gap-4 mb-1">
        <div>
          <div className="eyebrow mb-1">Getting started</div>
          <h2 className="text-lg">
            {setup.complete ? "You're set up" : "Next steps for your shop"}
          </h2>
        </div>
        <div className="text-right shrink-0">
          <div className="font-mono text-lg">{setup.done}/{setup.total}</div>
          <div className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>done</div>
        </div>
      </div>

      <div className="h-1 rounded-full overflow-hidden mb-5" style={{ background: "var(--canvas-raised)" }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--primary)" }} />
      </div>

      <ol className="space-y-1">
        {setup.steps.map((step, i) => {
          const isNext = step.id === setup.next_step_id;
          return (
            <li
              key={step.id}
              data-testid={`setup-step-${step.id}`}
              className="flex gap-3 p-3 rounded-lg"
              style={{
                background: isNext ? "var(--canvas-soft)" : "transparent",
                border: isNext ? "1px solid var(--hairline-strong)" : "1px solid transparent",
              }}
            >
              <div className="shrink-0 mt-0.5">
                {step.done ? (
                  <CheckCircle2 size={17} style={{ color: "var(--primary)" }} />
                ) : (
                  <div
                    className="w-[17px] h-[17px] rounded-full flex items-center justify-center text-[10px] font-mono"
                    style={{
                      border: "1px solid var(--hairline-strong)",
                      color: "var(--ink-mute-2)",
                    }}
                  >
                    {i + 1}
                  </div>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="text-sm"
                    style={{ color: step.done ? "var(--ink-mute)" : "var(--ink)" }}
                  >
                    {step.title}
                  </span>
                  {step.optional && <span className="pill">Optional</span>}
                  {isNext && <span className="pill">Start here</span>}
                </div>

                {/* Shown until the step is done. A manager who does not know
                    why importing matters will skip it, then blame the roster. */}
                {!step.done && (
                  <p className="text-[12px] mt-1 leading-relaxed" style={{ color: "var(--ink-mute)" }}>
                    {step.why}
                  </p>
                )}

                <div className="text-[11px] mt-1 font-mono" style={{ color: "var(--ink-mute-2)" }}>
                  {step.detail}
                </div>
              </div>

              {!step.done && (
                <button
                  data-testid={`setup-go-${step.id}`}
                  onClick={() => navigate(step.action.path)}
                  className={isNext ? "btn btn-primary shrink-0" : "btn btn-secondary shrink-0"}
                >
                  {step.action.label} <ArrowRight size={13} />
                </button>
              )}
            </li>
          );
        })}
      </ol>

      <button
        onClick={() => setExplain(!explain)}
        className="btn btn-ghost mt-4 text-[12px]"
        data-testid="btn-how-it-works"
      >
        <HelpCircle size={14} /> {explain ? "Hide" : "How the roster is built"}
      </button>

      {explain && <HowItWorks />}

      {setup.complete && (
        <button onClick={() => setOpen(false)} className="btn btn-ghost mt-2 text-[12px]">
          Hide this
        </button>
      )}
    </div>
  );
}

/**
 * The walkthrough.
 *
 * Written as what the scheduler does and what it will refuse to do, because
 * the questions managers actually ask are "why is this hour empty" and "why
 * did it not give her that shift" — and the answer to both is a rule.
 */
function HowItWorks() {
  return (
    <div className="mt-4 pt-4 space-y-5" style={{ borderTop: "1px solid var(--hairline)" }}>
      <Explain title="Four rules that are never broken">
        Somebody is on from opening to closing. A 24-hour shop always has
        someone in. Hours go to the most senior role first. Nobody works more
        than 12 hours or more than 5 days in a week. If keeping these means
        leaving an hour empty, the roster leaves it empty and tells you —
        rather than quietly rostering somebody who cannot legally be there.
      </Explain>

      <Explain title="It copies your own rosters">
        From the weeks you import, it learns which shifts your shop actually
        runs, how many people are on each day, and who normally works what.
        A generated week reuses those shapes. If somebody has never worked a
        06:00 start, it will not give them one.
      </Explain>

      <Explain title="Contracts are honoured before preferences">
        Full-time contract means 42.5 hours on the floor, breaks included,
        every week. The scheduler builds their shifts to reach it, choosing
        the lengths that fit rather than a fixed block. Students and hourly
        staff flex around them.
      </Explain>

      <Explain title="Edit, then rebalance">
        Change any shift and it becomes pinned. Press Rebalance and everyone
        else is re-solved around your pinned shifts, so a small correction
        does not cost you the rest of the week. A change that would break one
        of the four rules is refused, with the reason.
      </Explain>

      <Explain title="Approving makes it real">
        An approved week is the schedule people work, and it joins what the
        scheduler learns from. It is locked at that point — to change it, use
        Unapprove, which also takes it back out of the learning. A week that
        has already been worked cannot be reopened.
      </Explain>
    </div>
  );
}

function Explain({ title, children }) {
  return (
    <div>
      <div className="text-[13px] font-medium mb-1">{title}</div>
      <p className="text-[12px] leading-relaxed" style={{ color: "var(--ink-mute)" }}>
        {children}
      </p>
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
