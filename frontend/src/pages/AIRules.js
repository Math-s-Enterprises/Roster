import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Shield, AlertCircle, Sparkles } from "lucide-react";

const catIcon = { legal: Shield, safety: AlertCircle, custom: Sparkles };
const catClass = { legal: "text-cyan-400", safety: "text-amber-400", custom: "text-violet-400" };

export default function AIRules() {
  const [rules, setRules] = useState([]);
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");

  const load = async () => setRules((await api.get("/ai-rules")).data);
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    await api.post("/ai-rules", { title, description: desc, category: "custom", enabled: true });
    setTitle(""); setDesc(""); toast.success("Rule added"); load();
  };

  const toggle = async (r) => {
    await api.put(`/ai-rules/${r.rule_id}`, { title: r.title, description: r.description, category: r.category, enabled: !r.enabled });
    load();
  };
  const del = async (id) => { await api.delete(`/ai-rules/${id}`); load(); };

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
              <div key={r.rule_id} className="glass rounded-2xl p-5 flex items-start gap-4">
                <Icon size={18} className={catClass[r.category] || "text-white/60"} />
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium text-sm">{r.title}</div>
                    <span className="text-[10px] px-2 py-0.5 rounded-full glass-solid text-white/50 uppercase tracking-wider">{r.category}</span>
                  </div>
                  <div className="text-xs text-white/60 mt-1">{r.description}</div>
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={r.enabled} onChange={() => toggle(r)} className="w-4 h-4" />
                </label>
                {r.category === "custom" && (
                  <button onClick={() => del(r.rule_id)} className="text-red-400 hover:bg-red-500/10 p-2 rounded-lg"><Trash2 size={14} /></button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
