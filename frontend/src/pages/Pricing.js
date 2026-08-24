import React, { useState } from "react";
import { api, errorMessage, CURRENCY } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Sparkles, Check, Zap, Crown } from "lucide-react";

const plans = [
  {
    key: "roster_pro_monthly",
    name: "Pro Monthly",
    price: `${CURRENCY}19`,
    per: "/month",
    tag: "Flexible",
    features: ["Unlimited rosters", "AI narrative summaries", "Priority email dispatch", "Version history & audit log", "Multi-store roadmap access"],
  },
  {
    key: "roster_pro_yearly",
    name: "Pro Yearly",
    price: `${CURRENCY}190`,
    per: "/year",
    tag: "Save 17%",
    highlighted: true,
    features: ["Everything in Monthly", "2 months free", "Early access to new features", "Custom onboarding call"],
  },
];

export default function Pricing() {
  const { user } = useAuth();
  const [busy, setBusy] = useState(null);

  const buy = async (lookup_key) => {
    setBusy(lookup_key);
    try {
      const r = await api.post("/payments/checkout", { lookup_key, quantity: 1, origin_url: window.location.origin });
      window.location.href = r.data.checkout_url;
    } catch (err) {
      toast.error(errorMessage(err, "Could not start checkout"));
      setBusy(null);
    }
  };

  return (
    <div className="max-w-5xl">
      <div className="mb-8">
        <div className="text-xs text-cyan-400 uppercase tracking-widest mb-2 flex items-center gap-2"><Crown size={12} /> Billing</div>
        <h1 className="text-4xl font-light">
          Unlock <span className="neon-text font-bold">Roster AI Pro</span>
        </h1>
        <p className="text-white/50 mt-2 max-w-lg text-sm">
          Faster generation, richer analytics, and priority AI. Cancel anytime.
        </p>
      </div>

      {user?.pro && (
        <div className="glass rounded-2xl p-5 mb-6 flex items-center gap-3 border border-emerald-500/30">
          <Check size={16} className="text-emerald-400" />
          <div className="text-sm">You're on <span className="neon-text font-medium">Pro</span> — thank you for supporting the app.</div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {plans.map((p) => (
          <div key={p.key} data-testid={`plan-${p.key}`} className={`rounded-3xl p-8 ${p.highlighted ? "neon-border" : "glass"}`}>
            <div className="flex items-center justify-between mb-4">
              <div className="text-sm text-white/60">{p.name}</div>
              <span className="text-[10px] px-2 py-1 rounded-full glass-solid text-cyan-400 uppercase tracking-wider">{p.tag}</span>
            </div>
            <div className="flex items-baseline gap-1 mb-6">
              <div className="text-5xl font-light font-mono">{p.price}</div>
              <div className="text-white/40 text-sm">{p.per}</div>
            </div>
            <ul className="space-y-3 mb-8">
              {p.features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-white/80">
                  <Check size={14} className="text-cyan-400 mt-0.5 shrink-0" /> {f}
                </li>
              ))}
            </ul>
            <button
              data-testid={`buy-${p.key}`}
              onClick={() => buy(p.key)}
              disabled={busy === p.key}
              className="neon-btn w-full py-3 rounded-full text-sm flex items-center justify-center gap-2"
            >
              {busy === p.key ? "Redirecting…" : <><Zap size={14} /> Subscribe</>}
            </button>
          </div>
        ))}
      </div>

      <div className="mt-8 glass rounded-2xl p-5 text-xs text-white/50 flex items-start gap-3">
        <Sparkles size={14} className="text-cyan-400 mt-0.5 shrink-0" />
        <div>
          Sandbox test card: <span className="font-mono text-white/80">4242 4242 4242 4242</span> · any future expiry · any CVC · any ZIP.
          Managed by Stripe. No account required for test.
        </div>
      </div>
    </div>
  );
}
