import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Sparkles, Upload, Brain, Check, Loader2, FileText, X } from "lucide-react";

const SAMPLE_URLS = [
  { label: "Week 5 July", url: "https://customer-assets-jai6qajn.emergentagent.net/job_roster-engine-6/artifacts/z90x16xv_we_5th_july.webp" },
  { label: "Week 12 July", url: "https://customer-assets-jai6qajn.emergentagent.net/job_roster-engine-6/artifacts/87y02jop_we_12th_july.webp" },
  { label: "Week 19 July", url: "https://customer-assets-jai6qajn.emergentagent.net/job_roster-engine-6/artifacts/0d43ufo9_we_19th_july.webp" },
  { label: "Week 26 July", url: "https://customer-assets-jai6qajn.emergentagent.net/job_roster-engine-6/artifacts/58d4valb_we_26th_july.webp" },
  { label: "Week 2 August", url: "https://customer-assets-jai6qajn.emergentagent.net/job_roster-engine-6/artifacts/2vepob8t_we_2nd_august.webp" },
];

export default function AITraining() {
  const [stats, setStats] = useState(null);
  const [ocring, setOcring] = useState(null);
  const [preview, setPreview] = useState(null);
  const [importing, setImporting] = useState(false);
  const [imageUrl, setImageUrl] = useState("");

  const load = async () => {
    try { setStats((await api.get("/ai/training-stats")).data); } catch {}
  };
  useEffect(() => { load(); }, []);

  const runOCR = async (url) => {
    setOcring(url);
    try {
      const r = await api.post("/rosters/ocr", { image_url: url });
      setPreview({ ...r.data, source_url: url });
      toast.success(`Extracted ${r.data.shifts?.length || 0} shifts (from ${r.data.raw_shifts?.length || 0} rows)`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "OCR failed");
    } finally { setOcring(null); }
  };

  const importPreview = async () => {
    if (!preview) return;
    setImporting(true);
    try {
      const r = await api.post("/rosters/upload-historical", { week_start: preview.week_start, shifts: preview.shifts });
      toast.success(`AI trained on ${r.data.total_shifts} shifts · ${r.data.employees_learned} employees`);
      setPreview(null);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Import failed");
    } finally { setImporting(false); }
  };

  return (
    <div className="max-w-5xl">
      <div className="mb-8">
        <div className="text-xs text-cyan-400 uppercase tracking-widest mb-2 flex items-center gap-2"><Brain size={12} /> AI Training</div>
        <h1 className="text-4xl font-light">Teach Roster AI from your <span className="neon-text font-bold">real history</span></h1>
        <p className="text-white/50 mt-2 max-w-lg text-sm">Upload past rosters — photos, PDFs, or CSVs — and the AI will absorb the patterns of your store.</p>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard label="Approved rosters" value={stats.approved_rosters} />
          <StatCard label="Historical rosters" value={stats.historical_rosters} />
          <StatCard label="Shifts learned" value={stats.total_shifts_learned} accent />
          <StatCard label="Employees learned" value={stats.employees_learned} />
        </div>
      )}

      <div className="glass rounded-3xl p-8 mb-6">
        <h2 className="text-xl font-medium mb-4 flex items-center gap-2"><Upload size={16} /> Import from your photos</h2>
        <p className="text-xs text-white/50 mb-4">Click a roster below to run Claude vision OCR, review the extracted shifts, then import.</p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {SAMPLE_URLS.map((s) => (
            <button
              data-testid={`ocr-${s.label.replace(/\s+/g, "-")}`}
              key={s.url}
              onClick={() => runOCR(s.url)}
              disabled={ocring === s.url}
              className="glass-solid rounded-xl p-3 hover:border-white/20 transition-colors text-left"
            >
              <div className="aspect-video rounded-lg mb-2 bg-white/5 border border-white/10 overflow-hidden">
                <img src={s.url} alt={s.label} className="w-full h-full object-cover" />
              </div>
              <div className="text-xs font-medium">{s.label}</div>
              <div className="text-[10px] text-white/40 mt-0.5 flex items-center gap-1">
                {ocring === s.url ? <><Loader2 size={10} className="animate-spin" /> Analyzing…</> : <><Sparkles size={10} /> Extract</>}
              </div>
            </button>
          ))}
        </div>
        <div className="mt-4 flex gap-2">
          <input data-testid="ocr-url" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="Or paste an image URL…" className="flex-1 px-4 py-2.5 rounded-xl text-sm" />
          <button data-testid="btn-ocr-url" disabled={!imageUrl || ocring === imageUrl} onClick={() => runOCR(imageUrl)} className="neon-btn px-5 py-2.5 rounded-full text-sm">Extract</button>
        </div>
      </div>

      {preview && (
        <div className="glass rounded-3xl p-8 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-medium flex items-center gap-2"><FileText size={16} /> Review extracted data</h2>
            <button onClick={() => setPreview(null)} className="text-white/40 hover:text-white"><X size={16} /></button>
          </div>
          <div className="grid grid-cols-3 gap-3 mb-4 text-xs">
            <Stat label="Week start" value={preview.week_start || "—"} />
            <Stat label="Matched shifts" value={preview.shifts?.length || 0} />
            <Stat label="Rows detected" value={preview.raw_shifts?.length || 0} />
          </div>
          <div className="max-h-80 overflow-y-auto scroll-thin glass-solid rounded-xl p-4">
            <table className="w-full text-xs">
              <thead className="text-white/40 uppercase tracking-wider">
                <tr><th className="text-left pb-2">Employee</th><th>Day</th><th>Start</th><th>End</th><th>Role</th></tr>
              </thead>
              <tbody className="font-mono">
                {(preview.raw_shifts || []).slice(0, 100).map((s, i) => (
                  <tr key={i} className="border-t border-white/5">
                    <td className="py-1.5">{s.employee_name}</td>
                    <td className="text-center">{s.day}</td>
                    <td className="text-center">{s.start}</td>
                    <td className="text-center">{s.end}</td>
                    <td className="text-white/60">{s.role || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.shifts?.length === 0 && (
            <div className="mt-4 text-xs text-amber-400">
              None of the extracted names match existing employees. Add these employees first, then re-run OCR to import shifts.
            </div>
          )}
          <div className="flex gap-2 mt-6">
            <button data-testid="btn-import" onClick={importPreview} disabled={importing || !preview.shifts?.length} className="neon-btn px-5 py-2.5 rounded-full text-sm flex items-center gap-2">
              {importing ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Import & train AI
            </button>
            <button onClick={() => setPreview(null)} className="px-5 py-2.5 rounded-full glass-solid text-sm">Discard</button>
          </div>
        </div>
      )}

      <div className="glass rounded-3xl p-6 text-xs text-white/50 flex items-start gap-3">
        <Sparkles size={14} className="text-cyan-400 mt-0.5 shrink-0" />
        <div>
          <div className="text-white/80 mb-1">Learning quarantine</div>
          Only approved rosters and imported historical rosters train the AI. Draft rosters, sick leave records, and temporary overrides are excluded.
        </div>
      </div>
    </div>
  );
}

const StatCard = ({ label, value, accent }) => (
  <div className={`rounded-2xl p-5 ${accent ? "neon-border" : "glass"}`}>
    <div className="text-[11px] text-white/50 uppercase tracking-wider">{label}</div>
    <div className="text-3xl font-light font-mono mt-2">{value}</div>
  </div>
);

const Stat = ({ label, value }) => (
  <div className="glass-solid rounded-lg px-3 py-2">
    <div className="text-[10px] text-white/40 uppercase tracking-wider">{label}</div>
    <div className="font-mono text-white text-sm">{value}</div>
  </div>
);
