import React, { useEffect, useState } from "react";
import { api, fmtHours, DAY_LABELS } from "@/lib/api";
import { Archive, FileDown, Printer } from "lucide-react";
import { Link } from "react-router-dom";

export default function PastRosters() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");

  useEffect(() => { api.get("/rosters/past").then((r) => setItems(r.data)); }, []);

  const filtered = items.filter((r) => !q || r.week_start.includes(q) || (r.version || "").includes(q));

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="text-xs text-white/40 uppercase tracking-widest mb-2 flex items-center gap-2"><Archive size={12} /> Archive</div>
        <h1 className="text-4xl font-light">Past rosters</h1>
        <p className="text-white/50 mt-2 text-sm">Rosters whose week has already ended. Still searchable, printable and exportable.</p>
      </div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by date or version…" className="w-full max-w-sm mb-6 px-4 py-2.5 rounded-xl" />
      {filtered.length === 0 ? (
        <div className="glass rounded-3xl p-12 text-center text-white/50">No past rosters yet.</div>
      ) : (
        <ul className="space-y-3">
          {filtered.map((r) => (
            <li key={r.roster_id} className="glass rounded-2xl p-5 flex items-center justify-between flex-wrap gap-3">
              <div>
                <div className="text-sm font-medium">Week of <span className="font-mono">{r.week_start}</span> · <span className="neon-text">{r.version}</span></div>
                <div className="text-xs text-white/50 mt-1 font-mono">{fmtHours(r.total_hours)} · €{r.labor_cost?.toFixed?.(0) || 0} · score {r.compliance_score}{r.approved ? " · approved" : ""}</div>
              </div>
              <Link to={`/roster?week=${r.week_start}`} className="text-xs px-4 py-2 rounded-full glass-solid hover:border-white/20">Open</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
