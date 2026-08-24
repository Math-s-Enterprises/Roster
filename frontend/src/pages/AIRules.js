import React, { useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Shield, AlertCircle, Sparkles, Lock } from "lucide-react";

const catIcon = { legal: Shield, safety: AlertCircle, custom: Sparkles };
const catClass = { legal: "text-cyan-400", safety: "text-amber-400", custom: "text-violet-400" };

export default function AIRules() {
  const [rules, setRules] = useState([]);
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [compiling, setCompiling] = useState(null);

  const load = async () => setRules((await api.get("/ai-rules")).data);
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    await api.post("/ai-rules", { title, description: desc, category: "custom", enabled: true });
    setTitle(""); setDesc(""); toast.success("Rule added"); load();
  };

  const toggle = async (r) => {
    if (r.locked) { toast.error("This is a system rule and cannot be changed."); return; }
    await api.put(`/ai-rules/${r.rule_id}`, { title: r.title, description: r.description, category: r.category, enabled: !r.enabled });
    load();
  };
  const del = async (r) => {
    if (r.locked) { toast.error("This is a system rule and cannot be removed."); return; }
    await api.delete(`/ai-rules/${r.rule_id}`);
    load();
  };

  const compile = async (r) => {
    setCompiling(r.rule_id);
    try {
      const resp = await api.post(`/ai-rules/${r.rule_id}/compile`);
      toast.success("Rule compiled — review then approve");
      // Refresh to get the compiled JSON
      load();
      return resp.data.compiled;
    } catch (err) {
      toast.error(errorMessage(err, "Could not compile the rule"));
    } finally { setCompiling(null); }
  };
  const approve = async (r) => {
    await api.post(`/ai-rules/${r.rule_id}/approve-compiled`);
    toast.success("Constraint approved — solver will enforce it");
    load();
  };

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="text-xs text-white/40 uppercase tracking-widest mb-2">Policy</div>
        <h1 className="text-4xl font-light">AI rules engine</h1>
        <p className="text-white/50 mt-2 text-sm max-w-lg">Legal, safety and custom rules the AI must respect when generating a roster.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form onSubmit={add} className="glass rounded-2xl p-6 space-y-4">
          <h2 className="font-medium">New custom rule</h2>
          <div>
            <label className="text-xs text-white/60">Title</label>
            <input data-testid="rule-title" required value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 w-full px-3 py-2.5 rounded-lg" placeholder="e.g. No lone opening" />
          </div>
          <div>
            <label className="text-xs text-white/60">Description</label>
            <textarea data-testid="rule-desc" required value={desc} onChange={(e) => setDesc(e.target.value)} rows={4} className="mt-1 w-full px-3 py-2.5 rounded-lg resize-none" placeholder="Describe the constraint in plain English." />
          </div>
          <button data-testid="btn-add-rule" className="neon-btn w-full py-2.5 rounded-full text-sm flex items-center justify-center gap-2"><Plus size={14} /> Add rule</button>
        </form>

        <div className="lg:col-span-2 space-y-3">
          {rules.map((r) => {
            const Icon = catIcon[r.category] || Sparkles;
            return (
              <div key={r.rule_id} className="glass rounded-2xl p-5">
                <div className="flex items-start gap-4">
                  <Icon size={18} className={catClass[r.category] || "text-white/60"} />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="font-medium text-sm">{r.title}</div>
                      <span className="text-[10px] px-2 py-0.5 rounded-full glass-solid text-white/50 uppercase tracking-wider">{r.category}</span>
                      {r.locked && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 border border-white/15 text-white/50 flex items-center gap-1">
                          <Lock size={9} /> System rule
                        </span>
                      )}
                      {r.compiled && !r.approved && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400">Needs approval</span>}
                      {r.approved && <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">Enforced</span>}
                    </div>
                    <div className="text-xs text-white/60 mt-1">{r.description}</div>
                    {r.compiled && (
                      <pre className="mt-3 text-[10px] font-mono bg-black/40 p-3 rounded-lg text-cyan-300 overflow-x-auto scroll-thin">{JSON.stringify(r.compiled, null, 2)}</pre>
                    )}
                    <div className="flex gap-2 mt-3 flex-wrap">
                      <button data-testid={`btn-compile-${r.rule_id}`} onClick={() => compile(r)} disabled={compiling === r.rule_id} className="text-[11px] px-3 py-1.5 rounded-full glass-solid hover:border-white/20 flex items-center gap-1">
                        <Sparkles size={10} /> {compiling === r.rule_id ? "Compiling…" : (r.compiled ? "Re-compile" : "Compile")}
                      </button>
                      {r.compiled && !r.approved && (
                        <button data-testid={`btn-approve-${r.rule_id}`} onClick={() => approve(r)} className="neon-btn text-[11px] px-3 py-1.5 rounded-full">Approve for solver</button>
                      )}
                    </div>
                  </div>
                  <label className={`flex items-center gap-2 ${r.locked ? "cursor-not-allowed opacity-40" : "cursor-pointer"}`} title={r.locked ? "System rule — always on" : ""}>
                    <input type="checkbox" checked={r.enabled} disabled={r.locked} onChange={() => toggle(r)} className="w-4 h-4" />
                  </label>
                  {!r.locked && (
                    <button onClick={() => del(r)} className="text-red-400 hover:bg-red-500/10 p-2 rounded-lg"><Trash2 size={14} /></button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
