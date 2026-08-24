import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AlertTriangle, Brain, CheckCircle2, FileSpreadsheet, FileText,
  Image as ImageIcon, Loader2, Trash2, Undo2, Upload, X,
} from "lucide-react";

import { api, errorMessage } from "@/lib/api";

const KIND_ICON = {
  spreadsheet: FileSpreadsheet,
  csv: FileSpreadsheet,
  pdf: FileText,
  image: ImageIcon,
};

/**
 * Sentinel for "this person has left".
 *
 * Chosen to be impossible as a real employee_id (those are `emp_…`), so it
 * can share the one dropdown with the match-to-existing options instead of
 * needing a second control per row.
 */
const PAST_STAFF = "__past_staff__";

const SHEET_TYPES = ".xlsx,.xlsm,.xltx,.csv,.tsv";
const PDF_TYPES = ".pdf";
const IMAGE_TYPES = ".png,.jpg,.jpeg,.webp,.gif,.bmp,.heic";

export default function ImportRosters() {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState(null);
  const [weekHint, setWeekHint] = useState("");

  // What this deployment can actually read. Checked up front so an
  // unavailable format is never offered — a 503 after a slow upload is a
  // much worse way to learn that PDFs are not configured.
  const [caps, setCaps] = useState({ spreadsheet: true, csv: true, pdf: true, image: true, reasons: {} });
  useEffect(() => {
    api.get("/imports/capabilities").then((r) => setCaps(r.data)).catch(() => {});
  }, []);

  const accept = [
    SHEET_TYPES,
    caps.pdf ? PDF_TYPES : "",
    caps.image ? IMAGE_TYPES : "",
  ].filter(Boolean).join(",");

  const reasons = Object.values(caps.reasons || {});

  // Review selections, only meaningful once a preview exists.
  // Bumped after a successful import so the learning summary re-reads and
  // answers the obvious question: did that actually give the solver more?
  const [committed, setCommitted] = useState(0);
  const [weeks, setWeeks] = useState([]);          // week_starts to import
  const [mapping, setMapping] = useState({});      // sheet name -> employee_id | ""
  const [employees, setEmployees] = useState([]);

  const reset = () => {
    setPreview(null); setWeeks([]); setMapping({});
    if (fileRef.current) fileRef.current.value = "";
  };

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      // Multi-sheet workbooks name their own weeks; CSV exports and photos
      // usually don't, so this dates anything the file leaves undated.
      if (weekHint) form.append("week_start", weekHint);
      const [{ data }, staff] = await Promise.all([
        api.post("/imports", form, { headers: { "Content-Type": "multipart/form-data" } }),
        api.get("/employees"),
      ]);

      setPreview(data);
      setEmployees(staff.data);
      // Weeks already in the history are unticked by default — re-importing
      // one would duplicate it rather than update it.
      setWeeks(data.weeks.filter((w) => !w.already_imported).map((w) => w.week_start));
      setMapping(
        Object.fromEntries(
          data.people.map((p) => [p.name, p.matched_employee_id || ""]),
        ),
      );
    } catch (err) {
      toast.error(errorMessage(err, "Could not read that file"));
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    setBusy(true);
    try {
      // The sentinel travels in its own field. Leaving it in employee_map
      // would have the backend look up an employee called "__past_staff__"
      // and silently drop every shift belonging to that person.
      const pastStaff = Object.entries(mapping)
        .filter(([, id]) => id === PAST_STAFF)
        .map(([name]) => name);
      const employeeMap = Object.fromEntries(
        Object.entries(mapping).filter(([, id]) => id !== PAST_STAFF),
      );

      const { data } = await api.post(`/imports/${preview.import_id}/commit`, {
        week_starts: weeks,
        employee_map: employeeMap,
        past_staff: pastStaff,
      });
      const kept = data.past_staff_kept?.length || 0;
      toast.success(
        `Imported ${data.weeks_imported} week${data.weeks_imported === 1 ? "" : "s"}` +
          (data.employees_created ? `, created ${data.employees_created} employee(s)` : "") +
          (kept ? `, kept ${kept} past staff out of your list` : ""),
      );
      setCommitted((n) => n + 1);
      reset();
    } catch (err) {
      toast.error(errorMessage(err, "Could not import that roster"));
    } finally {
      setBusy(false);
    }
  };

  // Leavers are created too, but as history only — counting them as new
  // employees would overstate what the import adds to the staff list.
  const newPeople = useMemo(
    () => Object.entries(mapping).filter(([, id]) => !id).length,
    [mapping],
  );

  const pastPeople = useMemo(
    () => Object.entries(mapping).filter(([, id]) => id === PAST_STAFF).map(([n]) => n),
    [mapping],
  );

  const selectedShifts = useMemo(() => {
    if (!preview) return 0;
    return preview.weeks
      .filter((w) => weeks.includes(w.week_start))
      .reduce((sum, w) => sum + w.shifts, 0);
  }, [preview, weeks]);

  return (
    <div className="max-w-6xl">
      <div className="mb-8">
        <div className="eyebrow mb-2">Data</div>
        <h1 className="display">Import past rosters</h1>
        <p className="mt-2 text-sm max-w-2xl" style={{ color: "var(--ink-mute)" }}>
          Upload the rosters you already have — a spreadsheet, a PDF, or a photo of the
          sheet on the wall. The solver learns the shifts you actually run from these,
          so the more history it has, the closer a generated week looks to yours.
        </p>
      </div>

      <LearningSummary refreshKey={committed} />

      {!preview ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault(); setDragging(false);
            upload(e.dataTransfer.files?.[0]);
          }}
          className={`glass rounded-3xl p-12 text-center border-2 border-dashed transition-colors ${
            dragging ? "border-cyan-400/60 bg-cyan-400/5" : "border-white/10"
          }`}
        >
          <input
            ref={fileRef}
            type="file"
            accept={accept}
            data-testid="import-file"
            onChange={(e) => upload(e.target.files?.[0])}
            className="hidden"
          />

          {busy ? (
            <div className="flex flex-col items-center gap-3 text-white/70">
              <Loader2 size={32} className="animate-spin text-cyan-400" />
              <div className="text-sm">Reading the file…</div>
              <div className="text-xs text-white/40">
                Photos and PDFs take longer — they're read page by page.
              </div>
            </div>
          ) : (
            <>
              <Upload size={32} className="mx-auto text-cyan-400 mb-4" />
              <div className="text-lg font-light mb-1">Drop a roster file here</div>
              <div className="text-xs text-white/40 mb-6">
                Excel · CSV
                {caps.pdf && " · PDF"}
                {caps.image && " · photo"}
                {caps.max_bytes ? ` — up to ${Math.round(caps.max_bytes / 1024 / 1024)}MB` : ""}
              </div>
              <button
                onClick={() => fileRef.current?.click()}
                className="neon-btn px-6 py-2.5 rounded-full text-sm"
              >
                Choose a file
              </button>

              {/* Only needed when the file cannot say which week it is — a
                  CSV export or a photo. Workbooks name their own sheets. */}
              <div className="mt-6 max-w-xs mx-auto text-left">
                <label className="text-[11px] text-white/50">
                  Week beginning <span className="text-white/30">(optional)</span>
                </label>
                <input
                  type="date"
                  value={weekHint}
                  onChange={(e) => setWeekHint(e.target.value)}
                  className="mt-1 w-full px-3 py-2 rounded-lg font-mono text-xs"
                />
                <p className="text-[10px] text-white/35 mt-1 leading-relaxed">
                  Set this for a CSV or photo, which rarely say which week they
                  cover. Excel files with dated sheet names work without it.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-10 text-left">
                <Hint icon={FileSpreadsheet} title="Spreadsheet" available>
                  Read exactly, no guessing. One sheet per week works best.
                </Hint>
                <Hint icon={FileText} title="PDF" available={caps.pdf}>
                  {caps.pdf
                    ? `Each page is read as an image. Up to ${caps.max_pdf_pages || 30} pages.`
                    : "Not set up on this server."}
                </Hint>
                <Hint icon={ImageIcon} title="Photo" available={caps.image}>
                  {caps.image
                    ? "A clear, straight-on photo of the printed roster."
                    : "Not set up on this server."}
                </Hint>
              </div>

              {reasons.length > 0 && (
                <div className="mt-4 text-left rounded-xl p-4 bg-amber-500/[0.07] border border-amber-500/25">
                  <div className="text-[11px] text-amber-400 mb-1">
                    Some formats are unavailable
                  </div>
                  {reasons.map((r, i) => (
                    <div key={i} className="text-[11px] text-white/60 leading-relaxed">
                      • {r}
                    </div>
                  ))}
                  <div className="text-[10px] text-white/40 mt-2">
                    Spreadsheets and CSV work regardless — they need no AI.
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <Review
          preview={preview}
          weeks={weeks}
          setWeeks={setWeeks}
          mapping={mapping}
          setMapping={setMapping}
          employees={employees}
          newPeople={newPeople}
          pastCount={pastPeople.length}
          pastShifts={
            preview.people
              .filter((p) => pastPeople.includes(p.name))
              .reduce((sum, p) => sum + p.shifts, 0)
          }
          selectedShifts={selectedShifts}
          busy={busy}
          onCancel={reset}
          onCommit={commit}
        />
      )}

      {!preview && (
        <ImportedWeeks refreshKey={committed} onChange={() => setCommitted((n) => n + 1)} />
      )}
    </div>
  );
}

/**
 * The weeks currently in the history, and the only way to take one back out.
 *
 * Imported weeks are stored as approved past weeks, which the app otherwise
 * refuses to reopen — a week that has been worked is a record, not a plan.
 * An import is the exception: loading the wrong sheet is an ordinary mistake,
 * invisible afterwards except through the odd rosters it produces, and
 * without this it would be permanent.
 */
function ImportedWeeks({ refreshKey, onChange }) {
  const [weeks, setWeeks] = useState(null);
  const [removed, setRemoved] = useState([]);
  const [confirming, setConfirming] = useState(null);
  const [removing, setRemoving] = useState(false);
  const [restoring, setRestoring] = useState("");

  const load = () => {
    api.get("/imports/history")
      .then((r) => setWeeks(r.data))
      .catch(() => setWeeks([]));
    api.get("/imports/removed")
      .then((r) => setRemoved(r.data))
      .catch(() => setRemoved([]));
  };
  useEffect(load, [refreshKey]);

  const remove = async () => {
    setRemoving(true);
    try {
      await api.delete(`/imports/history/${confirming.roster_id}`);
      toast.success(`Removed the week of ${confirming.week_start}`);
      setConfirming(null);
      load();
      onChange?.();
    } catch (err) {
      toast.error(errorMessage(err, "Could not remove that week"));
    } finally { setRemoving(false); }
  };

  const restore = async (entry) => {
    setRestoring(entry.week_start);
    try {
      const { data } = await api.post("/imports/removed/restore", {
        import_id: entry.import_id, week_start: entry.week_start,
      });
      toast.success(
        `Restored ${data.week_start} — ${data.shifts_restored} shift${
          data.shifts_restored === 1 ? "" : "s"}`,
      );
      load();
      onChange?.();
    } catch (err) {
      toast.error(errorMessage(err, "Could not restore that week"));
    } finally { setRestoring(""); }
  };

  if (!weeks) return null;
  if (weeks.length === 0 && removed.length === 0) return null;

  return (
    <div className="card p-5 mt-6">
      {removed.length > 0 && (
        <div className="mb-6">
          <div className="text-sm font-medium mb-1">Removed weeks</div>
          <p className="text-[11px] mb-3" style={{ color: "var(--ink-mute-2)" }}>
            Still readable from the file you uploaded, so you can put one back
            without finding the original again.
          </p>
          <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--hairline)" }}>
            {removed.map((w, i) => (
              <div
                key={`${w.import_id}-${w.week_start}`}
                className="flex items-center gap-3 px-3 py-2.5 text-[13px]"
                style={{
                  background: "var(--canvas-soft)",
                  borderTop: i === 0 ? "none" : "1px solid var(--hairline)",
                }}
              >
                <span className="font-mono">{w.week_start}</span>
                <span style={{ color: "var(--ink-mute-2)" }}>
                  {w.shifts} shift{w.shifts === 1 ? "" : "s"}
                </span>
                {w.filename && (
                  <span className="truncate text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
                    from {w.filename}
                  </span>
                )}
                <button
                  data-testid={`btn-restore-week-${w.week_start}`}
                  onClick={() => restore(w)}
                  disabled={restoring === w.week_start}
                  className="btn btn-ghost ml-auto text-[12px]"
                >
                  {restoring === w.week_start
                    ? <Loader2 size={13} className="animate-spin" />
                    : <Undo2 size={13} />}
                  Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {weeks.length > 0 && (
        <>
      <div className="text-sm font-medium mb-1">Imported weeks</div>
      <p className="text-[11px] mb-4" style={{ color: "var(--ink-mute-2)" }}>
        {weeks.length} week{weeks.length === 1 ? "" : "s"} loaded from your files.
        Remove one if it was the wrong sheet or read badly — the scheduler stops
        learning from it immediately.
      </p>

      <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--hairline)" }}>
        {weeks.map((w, i) => (
          <div
            key={w.roster_id}
            className="flex items-center gap-3 px-3 py-2.5 text-[13px]"
            style={{
              background: "var(--canvas-soft)",
              borderTop: i === 0 ? "none" : "1px solid var(--hairline)",
            }}
          >
            <span className="font-mono">{w.week_start}</span>
            <span style={{ color: "var(--ink-mute-2)" }}>
              {w.shifts} shift{w.shifts === 1 ? "" : "s"}
              {w.total_hours ? ` · ${w.total_hours}h` : ""}
            </span>
            {w.source_sheet && (
              <span className="truncate text-[11px]" style={{ color: "var(--ink-mute-2)" }}>
                {w.source_sheet}
              </span>
            )}
            <button
              data-testid={`btn-remove-week-${w.week_start}`}
              onClick={() => setConfirming(w)}
              className="btn btn-ghost ml-auto text-[12px]"
              title="Remove this week from the roster history"
            >
              <Trash2 size={13} /> Remove
            </button>
          </div>
        ))}
      </div>
        </>
      )}

      {confirming && (
        <ConfirmRemove
          week={confirming}
          busy={removing}
          onCancel={() => setConfirming(null)}
          onConfirm={remove}
        />
      )}
    </div>
  );
}

function ConfirmRemove({ week, busy, onCancel, onConfirm }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,.6)" }}
      onClick={onCancel}
    >
      <div
        className="card p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={18} style={{ color: "var(--warn)" }} />
          <h2 className="text-base">Remove the week of {week.week_start}?</h2>
        </div>
        <p className="text-[13px] mb-3" style={{ color: "var(--ink-secondary)" }}>
          {week.shifts} shift{week.shifts === 1 ? "" : "s"} will be deleted from
          the roster history, and the scheduler will stop learning from them.
        </p>
        <p className="text-[12px] mb-5" style={{ color: "var(--ink-mute-2)" }}>
          You can put it back afterwards — it stays readable from the file you
          uploaded, and appears under “Removed weeks”.
        </p>
        <div className="flex gap-2">
          <button onClick={onCancel} className="btn btn-secondary flex-1">Keep it</button>
          <button
            data-testid="btn-remove-week-confirm"
            onClick={onConfirm}
            disabled={busy}
            className="btn btn-danger flex-1"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Remove week
          </button>
        </div>
      </div>
    </div>
  );
}

const Hint = ({ icon: Icon, title, children, available = true }) => (
  <div className={`glass-solid rounded-xl p-4 ${available ? "" : "opacity-40"}`}>
    <Icon size={16} className="text-white/50 mb-2" />
    <div className="text-xs font-medium mb-1 flex items-center gap-1.5">
      {title}
      {!available && (
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-white/40 border border-white/10">
          unavailable
        </span>
      )}
    </div>
    <div className="text-[11px] text-white/45 leading-relaxed">{children}</div>
  </div>
);

function Review({
  preview, weeks, setWeeks, mapping, setMapping, employees,
  newPeople, pastCount, pastShifts, selectedShifts, busy, onCancel, onCommit,
}) {
  const Icon = KIND_ICON[preview.kind] || FileSpreadsheet;
  const s = preview.summary;

  const toggleWeek = (w) =>
    setWeeks((prev) => (prev.includes(w) ? prev.filter((x) => x !== w) : [...prev, w]));

  return (
    <div className="space-y-6">
      <div className="glass rounded-2xl p-6 flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <Icon size={22} className="text-cyan-400 mt-1" />
          <div>
            <div className="font-medium">{preview.filename}</div>
            <div className="text-xs text-white/50 mt-1">
              {s.weeks} week{s.weeks === 1 ? "" : "s"} · {s.shifts} shifts ·{" "}
              {s.employees} people · {s.date_range[0]} → {s.date_range[1]}
              {preview.pages ? ` · ${preview.pages} page(s)` : ""}
            </div>
          </div>
        </div>
        <button onClick={onCancel} className="text-white/40 hover:text-white p-1">
          <X size={18} />
        </button>
      </div>

      {/* A model's reading of a picture is a guess; a parsed spreadsheet is
          not. The distinction decides how hard the user should look. */}
      {preview.needs_review && (
        <div className="rounded-2xl p-5 bg-amber-500/10 border border-amber-500/40">
          <div className="flex items-center gap-2 text-amber-400 mb-2">
            <AlertTriangle size={16} />
            <span className="text-sm font-medium">Read from a {preview.kind} — check it</span>
          </div>
          <p className="text-xs text-white/70 leading-relaxed">
            Times and names were read from an image, so mistakes are possible. Check the
            preview below before importing — this becomes the history the AI learns from.
          </p>
        </div>
      )}

      {preview.notes?.length > 0 && (
        <div className="glass rounded-2xl p-5">
          <div className="text-xs text-white/60 mb-2">Notes</div>
          <ul className="text-xs text-white/70 space-y-1">
            {preview.notes.map((n, i) => <li key={i}>• {n}</li>)}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="glass rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-medium text-sm">Weeks to import</h2>
            <button
              onClick={() =>
                setWeeks(
                  weeks.length === preview.weeks.length
                    ? []
                    : preview.weeks.map((w) => w.week_start),
                )
              }
              className="text-[10px] px-2 py-1 rounded-full glass-solid text-white/60"
            >
              {weeks.length === preview.weeks.length ? "None" : "All"}
            </button>
          </div>

          <div className="space-y-1.5 max-h-96 overflow-y-auto scroll-thin">
            {preview.weeks.map((w) => {
              const on = weeks.includes(w.week_start);
              return (
                <label
                  key={w.week_start}
                  className={`flex items-start gap-3 p-2.5 rounded-lg cursor-pointer ${
                    on ? "bg-white/[0.06]" : "hover:bg-white/[0.03]"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggleWeek(w.week_start)}
                    className="mt-0.5"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs">{w.week_start}</span>
                      <span className="text-[10px] text-white/40">{w.shifts} shifts</span>
                      {w.already_imported && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-white/45 border border-white/10">
                          already imported
                        </span>
                      )}
                      {w.warnings?.length > 0 && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/25">
                          {w.warnings.length} warning{w.warnings.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    {w.sheet_name && (
                      <div className="text-[10px] text-white/30 truncate">{w.sheet_name}</div>
                    )}
                    {w.warnings?.slice(0, 2).map((warning, i) => (
                      <div key={i} className="text-[10px] text-amber-400/80 mt-0.5">{warning}</div>
                    ))}
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        <div className="glass rounded-2xl p-6">
          <h2 className="font-medium text-sm mb-1">People found</h2>
          <p className="text-[11px] text-white/45 mb-4">
            Match each name to someone you already have, or leave as “Create new”.
            For anyone who has left, choose <em>No longer works here</em> — their
            shifts stay in the history so the staffing levels stay right, but they
            are never rostered and never appear in your staff list.
          </p>

          <div className="space-y-2 max-h-96 overflow-y-auto scroll-thin">
            {preview.people.map((p) => {
              const choice = mapping[p.name] ?? "";
              return (
                <div key={p.name} className="flex items-center gap-2">
                  <div className="w-32 shrink-0">
                    <div className="text-xs truncate">{p.name}</div>
                    <div className="text-[10px] text-white/35 truncate">
                      {p.role} · {p.shifts} shifts
                    </div>
                    {/* Only when the sheet and your role list disagree. The
                        title is kept as written and sorts last until you
                        position it in Settings — worth seeing now. */}
                    {p.role_in_file && p.role_in_file !== p.role && (
                      <div className="text-[10px] truncate" style={{ color: "var(--warn)" }}>
                        sheet says “{p.role_in_file}”
                      </div>
                    )}
                  </div>
                  <select
                    data-testid={`map-${p.name}`}
                    value={choice}
                    onChange={(e) =>
                      setMapping((prev) => ({ ...prev, [p.name]: e.target.value }))
                    }
                    className="flex-1 px-2 py-1.5 rounded-lg text-xs"
                    style={choice === PAST_STAFF ? { color: "var(--ink-mute)" } : undefined}
                  >
                    <option value="">➕ Create new employee</option>
                    <option value={PAST_STAFF}>🚫 No longer works here</option>
                    {employees.map((e) => (
                      <option key={e.employee_id} value={e.employee_id}>
                        {e.name}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>

          {pastCount > 0 && (
            <p className="text-[11px] mt-3" style={{ color: "var(--ink-mute-2)" }}>
              {pastCount} {pastCount === 1 ? "person" : "people"} marked as left —
              keeping {pastShifts} shift{pastShifts === 1 ? "" : "s"} of history
              without adding them to your staff.
            </p>
          )}
        </div>
      </div>

      {s.unreadable_cells > 0 && (
        <div className="glass rounded-2xl p-5 text-xs text-white/60">
          {s.unreadable_cells} cell{s.unreadable_cells === 1 ? "" : "s"} could not be read
          and will be skipped — usually hours written without start and end times.
        </div>
      )}

      <div className="glass rounded-2xl p-6 flex items-center justify-between gap-4">
        <div className="text-xs text-white/60">
          Importing <span className="text-cyan-400">{weeks.length}</span> week
          {weeks.length === 1 ? "" : "s"} · {selectedShifts} shifts
          {newPeople > 0 && <> · creating <span style={{ color: "var(--primary)" }}>{newPeople}</span> new employee{newPeople === 1 ? "" : "s"}</>}
          {pastCount > 0 && <> · <span style={{ color: "var(--ink-mute)" }}>{pastCount}</span> kept as past staff</>}
        </div>
        <div className="flex gap-2">
          <button onClick={onCancel} className="btn btn-secondary">
            Cancel
          </button>
          <button
            data-testid="btn-commit-import"
            onClick={onCommit}
            disabled={busy || weeks.length === 0}
            className="btn btn-primary"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            Import
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * What the solver currently has to learn from.
 *
 * `weeks_in_window` is the number that actually decides roster quality: the
 * demand profile learns from a trailing window and needs a minimum before it
 * will use a learned shape at all. Counting rosters alone hid that — fifty
 * rosters spread over three years still leaves the solver falling back to
 * generic block coverage.
 */
function LearningSummary({ refreshKey }) {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/imports/learning-summary")
      .then((r) => setStats(r.data))
      .catch(() => setStats(null));
  }, [refreshKey]);

  if (!stats) return null;

  const ready = stats.learning_from_history;
  return (
    <div className="card p-5 mb-6">
      <div className="flex items-center gap-2 mb-3">
        <Brain size={15} style={{ color: "var(--ink-mute)" }} />
        <span className="text-sm font-medium">What the roster has learned</span>
        <span className={`pill ${ready ? "" : "pill-warn"}`}>
          {ready ? "Learning from your history" : "Not enough history yet"}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-px rounded-lg overflow-hidden"
           style={{ background: "var(--hairline)" }}>
        <Metric label="Weeks in use"
                value={`${stats.weeks_in_window}`}
                note={`of the last ${stats.lookback_weeks}`} />
        <Metric label="Weeks stored" value={`${stats.weeks_of_history}`} />
        <Metric label="Shifts learned" value={stats.total_shifts_learned.toLocaleString()} />
        <Metric label="People seen" value={`${stats.employees_learned}`} />
      </div>

      <p className="text-[11px] mt-3" style={{ color: "var(--ink-mute-2)" }}>
        {ready
          ? `Rosters are built from the shifts you actually ran in the last ${stats.lookback_weeks} weeks.`
          : `At least ${stats.weeks_needed} weeks are needed before the roster follows your own patterns. Until then it falls back to generic blocks.`}
      </p>
    </div>
  );
}

function Metric({ label, value, note }) {
  return (
    <div className="p-3" style={{ background: "var(--canvas-soft)" }}>
      <div className="eyebrow">{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-[22px] font-mono leading-none">{value}</span>
        {note && <span className="text-[11px]" style={{ color: "var(--ink-mute-2)" }}>{note}</span>}
      </div>
    </div>
  );
}
