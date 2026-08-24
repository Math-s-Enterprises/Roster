import React, { useEffect, useState } from "react";
import { api, errorMessage, DAY_LABELS, DAYS } from "@/lib/api";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { ChevronRight, ChevronLeft, Check, ArrowUp, ArrowDown, Loader2, X } from "lucide-react";

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [shop, setShop] = useState(null);
  const [name, setName] = useState("");
  const [hours, setHours] = useState([]);
  const [minShift, setMinShift] = useState(4);
  const [maxShift, setMaxShift] = useState(9);
  // The role list is ordered: position in it *is* the seniority ladder, which
  // decides who gets hours first and what order the roster grid is printed in.
  // Keeping one ordered list rather than a separate "roles" and "hierarchy"
  // means the two can never drift apart.
  const [roles, setRoles] = useState([]);
  const [newRole, setNewRole] = useState("");
  const [supervisory, setSupervisory] = useState([]);
  const [counts, setCounts] = useState({});
  const [strictDaysOff, setStrictDaysOff] = useState(true);
  const [breaksPaid, setBreaksPaid] = useState(false);
  const [open24h, setOpen24h] = useState(false);
  const [paidSickDays, setPaidSickDays] = useState(5);
  const [minRest, setMinRest] = useState(11);
  const [saving, setSaving] = useState(false);
  const nav = useNavigate();

  /**
   * A shop already through setup sees every section at once with one Save,
   * not a five-screen wizard it has to click through to change one time.
   * Same fields either way, so the two can never disagree.
   */
  const editing = !!shop?.onboarded;

  const copyMondayToAll = () => {
    const monday = hours.find((h) => h.day === "mon") || hours[0];
    if (!monday) return;
    setHours(hours.map((h) => ({
      ...h, open: monday.open, close: monday.close, closed: monday.closed,
    })));
    toast.success(`Every day set to ${monday.open}–${monday.close}`);
  };

  useEffect(() => {
    Promise.all([api.get("/shop"), api.get("/shop/hierarchy")]).then(([r, h]) => {
      setShop(r.data); setName(r.data.name);
      setHours(r.data.hours); setMinShift(r.data.min_shift_hours);
      setMaxShift(r.data.max_shift_hours);
      setStrictDaysOff(r.data.strict_days_off !== false);
      setBreaksPaid(!!r.data.breaks_are_paid);
      setOpen24h(!!r.data.open_24h);
      setPaidSickDays(r.data.paid_sick_days ?? 5);
      setMinRest(r.data.min_rest_hours ?? 11);
      // Seeded from the server so an unconfigured shop starts from the
      // sensible default ladder rather than whatever order roles were added.
      setRoles(h.data.hierarchy);
      setSupervisory(h.data.supervisory);
      setCounts(h.data.employee_counts || {});
    });
  }, []);

  const move = (index, delta) => {
    const next = [...roles];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setRoles(next);
  };

  const save = async (extra = {}) => {
    await api.put("/shop", {
      name, hours,
      min_shift_hours: minShift, max_shift_hours: maxShift,
      roles,
      role_hierarchy: roles,
      strict_days_off: strictDaysOff,
      breaks_are_paid: breaksPaid,
      // The backend fills in round-the-clock hours and night templates when
      // this turns on, so the shop is never flagged 24h while still holding
      // 09:00–21:00 times.
      open_24h: open24h,
      paid_sick_days: Number(paidSickDays) || 0,
      min_rest_hours: Number(minRest) || 0,
      ...extra,
    });
  };

  const finish = async () => {
    await save({ onboarded: true });
    toast.success("Setup complete — you're ready to roster.");
    nav("/");
  };

  const saveChanges = async () => {
    setSaving(true);
    try {
      await save();
      toast.success("Shop settings saved");
    } catch (err) {
      toast.error(errorMessage(err, "Could not save the settings"));
    } finally { setSaving(false); }
  };

  if (!shop) return <div className="text-white/60">Loading…</div>;

  const steps = [
    { title: "Shop identity", desc: "Give your shop a name your team will recognize." },
    { title: "Opening hours", desc: "Set weekly opening and closing times." },
    { title: "Shift limits", desc: "Minimum and maximum shift lengths." },
    { title: "Roles & seniority", desc: "The order here decides who gets hours first." },
    { title: "Scheduling rules", desc: "How firmly the roster holds to preferences." },
  ];

  // In settings mode every section is rendered, so the `step === n` guards
  // below become "is this section shown", not "is this the current screen".
  const shows = (n) => editing || step === n;

  return (
    <div className="max-w-3xl">
      {editing ? (
        <div className="mb-8">
          <div className="eyebrow mb-2">Setup</div>
          <h1 className="display">Shop settings</h1>
          <p className="mt-2 text-sm" style={{ color: "var(--ink-mute)" }}>
            Change anything you got wrong first time. Saving applies to the
            next roster you generate — weeks already approved are untouched.
          </p>
        </div>
      ) : (
        <>
          <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Onboarding · step {step + 1} of {steps.length}</div>
          <h1 className="text-4xl font-light mb-2">{steps[step].title}</h1>
          <p className="text-white/50 mb-8">{steps[step].desc}</p>
        </>
      )}

      <div className={editing ? "space-y-6" : "glass rounded-3xl p-8"}>
        {shows(0) && (
          <Section show={editing} title="Shop identity">
          <div className="space-y-4">
            <label className="text-xs text-white/60">Shop name</label>
            <input data-testid="input-shop-name" value={name} onChange={(e) => setName(e.target.value)} className="w-full px-4 py-3 rounded-xl" />
          </div>
          </Section>
        )}

        {shows(1) && (
          <Section show={editing} title="Opening hours">
          <div className="space-y-4">
            {/* Seven rows of near-identical times is the most tedious part of
                setup, and the commonest shapes are "same every day" and
                "always open". Both are one click. */}
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox" data-testid="input-open-24h"
                  checked={open24h}
                  onChange={(e) => setOpen24h(e.target.checked)}
                  className="w-4 h-4 accent-cyan-400"
                />
                Open 24 hours
              </label>

              {!open24h && (
                <button
                  type="button"
                  data-testid="btn-copy-monday"
                  onClick={copyMondayToAll}
                  className="px-3 py-1.5 rounded-lg glass-solid text-xs ml-auto"
                >
                  Use Monday's times every day
                </button>
              )}
            </div>

            {open24h ? (
              <p className="text-xs text-white/50">
                The shop is treated as open every hour of every day, and at
                least one person is rostered at all times — including
                overnight. Individual day times are not used.
              </p>
            ) : (
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
          </div>
          </Section>
        )}

        {shows(2) && (
          <Section show={editing} title="Shift limits">
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
          </Section>
        )}

        {shows(3) && (
          <Section show={editing} title="Roles & seniority">
          <div className="space-y-4">
            <p className="text-xs text-white/50">
              Most senior at the top. Hours are allocated down this list, and
              the roster grid, print view and exports all follow the same
              order.
            </p>
            <ul className="space-y-2">
              {roles.map((r, i) => (
                <li key={r} data-testid={`role-row-${i}`} className="glass-solid rounded-xl px-3 py-2 flex items-center gap-3">
                  <span className="font-mono text-[11px] text-white/30 w-5 text-right">{i + 1}</span>
                  <span className="flex-1 text-sm truncate">{r}</span>
                  {counts[r] > 0 && (
                    <span className="text-[10px] text-white/40 font-mono shrink-0">
                      {counts[r]} staff
                    </span>
                  )}
                  {supervisory.includes(r) && (
                    <span className="text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 shrink-0">
                      Supervisory
                    </span>
                  )}
                  <button type="button" title="Move up" disabled={i === 0}
                    onClick={() => move(i, -1)}
                    className="p-1 rounded text-white/40 hover:text-white disabled:opacity-20">
                    <ArrowUp size={13} />
                  </button>
                  <button type="button" title="Move down" disabled={i === roles.length - 1}
                    onClick={() => move(i, 1)}
                    className="p-1 rounded text-white/40 hover:text-white disabled:opacity-20">
                    <ArrowDown size={13} />
                  </button>
                  <button type="button" title="Remove"
                    onClick={() => setRoles(roles.filter((x) => x !== r))}
                    className="p-1 rounded text-white/30 hover:text-red-400">
                    <X size={13} />
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input data-testid="input-new-role" value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                placeholder="Add a role" className="flex-1 px-4 py-2.5 rounded-xl" />
              <button type="button"
                onClick={() => {
                  const title = newRole.trim();
                  if (title && !roles.includes(title)) setRoles([...roles, title]);
                  setNewRole("");
                }}
                className="px-4 py-2.5 rounded-xl glass-solid text-sm">Add</button>
            </div>
            <p className="text-[11px] text-white/40">
              Roles in the top third count as supervisory cover. Removing a
              role here does not remove it from anyone — staff with an
              unlisted title simply rank last.
            </p>
          </div>
          </Section>
        )}

        {shows(4) && (
          <Section show={editing} title="Scheduling rules">
          <div className="space-y-5">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox" data-testid="input-strict-days-off"
                checked={strictDaysOff}
                onChange={(e) => setStrictDaysOff(e.target.checked)}
                className="mt-1 w-4 h-4 shrink-0 accent-cyan-400"
              />
              <span>
                <span className="text-sm block">Preferred days off are never overridden</span>
                <span className="text-xs text-white/50 block mt-1">
                  On: a requested day off is honoured even when that leaves an
                  hour uncovered — the gap is reported instead of quietly
                  filled. Off: preferences yield to keeping the shop attended.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox" data-testid="input-breaks-paid"
                checked={breaksPaid}
                onChange={(e) => setBreaksPaid(e.target.checked)}
                className="mt-1 w-4 h-4 shrink-0 accent-cyan-400"
              />
              <span>
                <span className="text-sm block">Breaks are paid</span>
                <span className="text-xs text-white/50 block mt-1">
                  On: a shift pays for its full length. Off: the break comes
                  out, so an 8-hour shift pays 7.5. This changes every wage
                  figure in the app. It does not change a full-time contract,
                  which is written in hours on the floor either way.
                </span>
              </span>
            </label>

            <div>
              <label className="text-xs text-white/60">Minimum rest between shifts (hours)</label>
              <input
                data-testid="input-min-rest-hours"
                type="number" min={0} max={24} step={0.5}
                value={minRest}
                onChange={(e) => setMinRest(e.target.value)}
                className="mt-1 w-32 px-4 py-2.5 rounded-xl font-mono"
              />
              <p className="text-xs text-white/50 mt-2 max-w-lg">
                Nobody starts again until this long after finishing. Eleven is
                the daily rest entitlement in the Organisation of Working Time
                Act. Counted in real time, so a night shift ending 07:00 on
                Tuesday blocks a Tuesday afternoon start.
              </p>
            </div>

            <div>
              <label className="text-xs text-white/60">Paid sick days per year</label>
              <input
                data-testid="input-paid-sick-days"
                type="number" min={0} max={365} step={0.5}
                value={paidSickDays}
                onChange={(e) => setPaidSickDays(e.target.value)}
                className="mt-1 w-32 px-4 py-2.5 rounded-xl font-mono"
              />
              <p className="text-xs text-white/50 mt-2 max-w-lg">
                Ireland's statutory minimum is 5. Set in days because that is
                how the law is written, but spent in hours: each person's day
                is worked out from the shifts they actually do, so somebody on
                four-hour Saturdays is not charged the same as somebody on
                ten-hour Mondays. Illness beyond the allowance is still
                recorded — it is simply unpaid.
              </p>
            </div>

            <div className="glass-solid rounded-xl p-4">
              <div className="text-xs text-white/60 mb-2">Rules that cannot be turned off</div>
              <ul className="text-xs text-white/50 space-y-1.5">
                <li>• Someone is on the floor from open to close, every day.</li>
                <li>• Hours are allocated down the seniority list above.</li>
                <li>• Nobody exceeds their contracted hours or the maximum shift length.</li>
                <li>• Under-16s are never rostered before 08:00 or after 19:00.</li>
              </ul>
            </div>
          </div>
          </Section>
        )}
      </div>

      {editing ? (
        <div className="flex items-center gap-3 mt-8">
          <button
            data-testid="btn-save-settings"
            onClick={saveChanges}
            disabled={saving}
            className="btn btn-primary"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Save changes
          </button>
          <span className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
            Regenerate a week afterwards to see the effect.
          </span>
        </div>
      ) : (
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
      )}
    </div>
  );
}

/**
 * One section of setup.
 *
 * A heading and a card only in settings mode: in the wizard the page title
 * already says which step you are on, and repeating it inside the card would
 * read as a stutter.
 */
function Section({ show, title, children }) {
  if (!show) return children;
  return (
    <div className="card p-6">
      <h2 className="text-sm font-medium mb-4">{title}</h2>
      {children}
    </div>
  );
}
