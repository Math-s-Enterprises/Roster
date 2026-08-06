import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ThermometerSnowflake, Activity } from "lucide-react";

export default function SickReport() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/reports/sick-leave").then((r) => setData(r.data)); }, []);

  return (
    <div className="max-w-5xl">
      <div className="mb-8">
        <div className="text-xs text-cyan-400 uppercase tracking-widest mb-2 flex items-center gap-2"><ThermometerSnowflake size={12} /> HR Report</div>
        <h1 className="text-4xl font-light">Sick leave</h1>
        <p className="text-white/50 mt-2 text-sm max-w-lg">Never used by AI scheduling. Purely for HR visibility.</p>
      </div>
      {!data ? <div className="text-white/50">Loading…</div> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8">
            <Card label="Total incidents" value={data.total_incidents} />
            <Card label="Total days" value={data.total_days} />
            <Card label="Employees affected" value={data.by_employee.length} accent />
          </div>
          {data.by_employee.length === 0 ? (
            <div className="glass rounded-3xl p-12 text-center text-white/50">No sick leave recorded.</div>
          ) : (
            <div className="space-y-3">
              {data.by_employee.map((e) => (
                <div key={e.employee_id} className="glass rounded-2xl p-5">
                  <div className="flex items-center gap-3 mb-3">
                    {e.avatar && <img src={e.avatar} alt="" className="w-10 h-10 rounded-full object-cover" />}
                    <div className="flex-1">
                      <div className="font-medium text-sm">{e.name}</div>
                      <div className="text-[11px] text-white/50">{e.role}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-lg">{e.days}d</div>
                      <div className="text-[10px] text-white/40">{e.occurrences.length} incident{e.occurrences.length !== 1 ? "s" : ""}</div>
                    </div>
                  </div>
                  <ul className="space-y-1.5 pl-13">
                    {e.occurrences.map((o, i) => (
                      <li key={i} className="text-xs text-white/60 font-mono flex items-center gap-2">
                        <Activity size={10} className="text-amber-400" />
                        {o.start}{o.end !== o.start ? ` → ${o.end}` : ""} · {o.days}d · {o.label}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const Card = ({ label, value, accent }) => (
  <div className={`rounded-2xl p-5 ${accent ? "neon-border" : "glass"}`}>
    <div className="text-[11px] text-white/50 uppercase tracking-wider">{label}</div>
    <div className="text-3xl font-light font-mono mt-2">{value}</div>
  </div>
);
