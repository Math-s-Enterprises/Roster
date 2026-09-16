import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AlertTriangle, Calendar, CheckCircle2, FileSpreadsheet, FileText,
  Image as ImageIcon, Loader2, Search, Trash2, Upload, X,
} from "lucide-react";

import { api, errorMessage } from "@/lib/api";

/**
 * Import past rosters (handoff: Import past rosters).
 *
 * Two jobs: get a file in, and show which weeks the scheduler is learning
 * from. The drop target is the hero across the left column, the learning
 * summary sits in the inset panel beside it, and imported weeks are a
 * hairline table grouped by month. Styling is scoped to .im-* in index.css.
 *
 * WHAT IS KEPT FROM THE EXISTING PAGE
 *
 * Uploading is not a single step here. The file is parsed into a preview,
 * the manager confirms which weeks to take and maps each name on the sheet
 * to a real employee — or marks them past staff — and only then is it
 * committed. The handoff describes upload as one action and says nothing
 * about that stage, so the Review screen is kept exactly as it was rather
 * than rebuilt from a spec that does not cover it. Without the name mapping
 * an import silently invents employees.
 *
 * The removed-weeks list is kept for the same reason: imported weeks are
 * stored as approved past weeks, which the app otherwise refuses to reopen,
 * and restoring one is the only way back from loading the wrong sheet.
 *
 * DEVIATIONS
 *
 * 1. SOURCE reads the file extension rather than a stored source type, and
 *    shows the sheet or file name instead of "added 23 Aug" — the history
 *    records what a week came from, not when it was imported.
 *
 * 2. "Looks short" is computed here, against the median shift count of the
 *    other imported weeks. The handoff wants it derived server-side; the
 *    history returns no such flag, and a heuristic that never fires would be
 *    worse than one the manager can sanity-check against the numbers beside
 *    it.
 *
 * 3. Rows are a CSS grid with table roles rather than a real <table>: the
 *    handoff asks for both a real table and minmax() tracks, and a table
 *    cannot express minmax. Same choice as the sibling pages.
 */

/** Which glyph the review stage shows for each parsed source kind. */
const KIND_ICON = {
  spreadsheet: FileSpreadsheet,
  csv: FileSpreadsheet,
  pdf: FileText,
  image: ImageIcon,
};

const PAST_STAFF = "__past_staff__";

const SHEET_TYPES = ".xlsx,.xlsm,.xltx,.csv,.tsv";
const PDF_TYPES = ".pdf";
const IMAGE_TYPES = ".png,.jpg,.jpeg,.webp,.gif,.bmp,.heic";

const PAGE = 7;

const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

const parseDay = (isoDate) => new Date(`${isoDate}T00:00:00`);

const fmtWeek = (isoDate) => {
  const d = parseDay(isoDate);
  return Number.isNaN(d.getTime())
    ? isoDate
    : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
};

const monthKeyOf = (isoDate) => {
  const d = parseDay(isoDate);
  return Number.isNaN(d.getTime())
    ? "unknown"
    : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

const monthLabel = (key) => {
  const [y, m] = key.split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`.toUpperCase();
};

/** What kind of file a week came from, read off its name. */
function sourceOf(week) {
  const name = String(week.filename || week.source_sheet || "").toLowerCase();
  if (/\.(csv|tsv)$/.test(name)) return "CSV";
  if (/\.(xlsx|xlsm|xltx|xls)$/.test(name)) return "Spreadsheet";
  if (/\.pdf$/.test(name)) return "PDF";
  if (/\.(png|jpe?g|webp|gif|bmp|heic)$/.test(name)) return "Photo";
  return week.source_sheet ? "Spreadsheet" : "Imported";
}

const median = (values) => {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

export default function ImportRosters() {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState(null);
  const [weekHint, setWeekHint] = useState("");
  const [reading, setReading] = useState("");

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
  const unavailable = [caps.pdf ? null : "PDF", caps.image ? null : "photo"].filter(Boolean);

  const [committed, setCommitted] = useState(0);
  const [weeks, setWeeks] = useState([]);
  const [mapping, setMapping] = useState({});
  const [employees, setEmployees] = useState([]);

  const [summary, setSummary] = useState(null);
  useEffect(() => {
    api.get("/imports/learning-summary")
      .then((r) => setSummary(r.data))
      .catch(() => setSummary(null));
  }, [committed]);

  const reset = () => {
    setPreview(null); setWeeks([]); setMapping({});
    if (fileRef.current) fileRef.current.value = "";
  };

  /**
   * Reject a format this server cannot read with the reason the server gave,
   * rather than a generic "unsupported file" the manager cannot act on.
   */
  const rejectReason = (file) => {
    const name = file.name.toLowerCase();
    if (/\.pdf$/.test(name) && !caps.pdf) {
      return caps.reasons?.pdf || "PDF reading is not set up on this server.";
    }
    if (/\.(png|jpe?g|webp|gif|bmp|heic)$/.test(name) && !caps.image) {
      return caps.reasons?.image || "Photo reading is not set up on this server.";
    }
    if (!/\.(xlsx|xlsm|xltx|xls|csv|tsv|pdf|png|jpe?g|webp|gif|bmp|heic)$/.test(name)) {
      return "That file type cannot be read — use a spreadsheet or CSV.";
    }
    if (caps.max_bytes && file.size > caps.max_bytes) {
      return `That file is larger than the ${Math.round(caps.max_bytes / 1024 / 1024)}MB limit.`;
    }
    return null;
  };

  const upload = async (file) => {
    if (!file) return;
    const refusal = rejectReason(file);
    if (refusal) { toast.error(refusal); return; }

    setBusy(true);
    setReading(file.name);
    try {
      const form = new FormData();
      form.append("file", file);
      // Multi-sheet workbooks name their own weeks; a CSV export or a photo
      // of the wall sheet usually carries no date at all, so this dates
      // anything the file leaves undated.
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
      setReading("");
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
        `Imported ${data.weeks_imported} week${data.weeks_imported === 1 ? "" : "s"}`
          + (data.employees_created ? `, created ${data.employees_created} employee(s)` : "")
          + (kept ? `, kept ${kept} past staff out of your list` : ""),
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

  // The review stage replaces the whole page: mapping names to people is a
  // decision, and leaving the drop target visible invites a second upload
  // on top of one already waiting to be confirmed.
  if (preview) {
    return (
      <div className="max-w-6xl">
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
      </div>
    );
  }

  const maxMb = caps.max_bytes ? Math.round(caps.max_bytes / 1024 / 1024) : null;

  return (
    <div className="im-page">
      <header className="im-head">
        <div>
          <div className="im-eyebrow">DATA</div>
          <h1 className="im-h1">Import past rosters</h1>
          <p className="im-sub">
            Upload the rosters you already have — a spreadsheet, a PDF, or a photo of the sheet on
            the wall. The solver learns the shifts you actually run from these, so the more history
            it has, the closer a generated week looks to yours.
          </p>
        </div>
      </header>

      <input
        ref={fileRef}
        type="file"
        accept={accept}
        data-testid="import-file"
        onChange={(e) => upload(e.target.files?.[0])}
        style={{ display: "none" }}
      />

      <div className="im-split">
        <div
          className="im-drop"
          data-dragging={dragging}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault(); setDragging(false);
            upload(e.dataTransfer.files?.[0]);
          }}
        >
          {busy ? (
            <>
              <Loader2 size={28} className="animate-spin" color="var(--t-accent)" aria-hidden="true" />
              <h2 className="im-drop-head">Reading {reading}…</h2>
              <p className="im-drop-sub">Photos and PDFs take longer — they are read page by page.</p>
            </>
          ) : (
            <>
              <Upload size={28} color="var(--t-accent)" strokeWidth={1.8} aria-hidden="true" />
              <h2 className="im-drop-head">Drop a roster file here</h2>
              <p className="im-drop-sub">
                Excel · CSV{caps.pdf ? " · PDF" : ""}{caps.image ? " · photo" : ""}
                {maxMb ? ` — up to ${maxMb}MB` : ""}
                {unavailable.length > 0 ? `. ${unavailable.join(" and ")} need server setup.` : ""}
              </p>

              <div className="im-drop-row">
                <button
                  type="button"
                  className="im-btn im-btn-1 im-btn-hero"
                  onClick={() => fileRef.current?.click()}
                >
                  <Upload size={16} strokeWidth={1.8} /> Choose a file
                </button>

                <label className="im-week">
                  <Calendar size={14} color="var(--t-faint)" strokeWidth={1.6} aria-hidden="true" />
                  <span className="im-week-label">
                    Week beginning <span>(optional)</span>
                  </span>
                  <input
                    type="date"
                    value={weekHint}
                    onChange={(e) => setWeekHint(e.target.value)}
                    onClick={(e) => { try { e.currentTarget.showPicker?.(); } catch { /* unsupported */ } }}
                    aria-label="Week beginning (optional)"
                  />
                </label>
              </div>

              <p className="im-drop-note">
                Set the week for a CSV or photo, which rarely say which week they cover. Excel files
                with dated sheet names work without it.
              </p>
            </>
          )}
        </div>

        <div className="im-summary">
          <div className="im-label">What the scheduler has learned</div>
          {summary ? (
            <>
              <div className="im-sum-row">
                <span className="im-sum-num">{summary.weeks_in_window}</span>
                <span className="im-sum-head">
                  weeks in use
                  <span className="im-sum-sub">
                    of the last {summary.lookback_weeks} · {summary.weeks_of_history} stored
                  </span>
                </span>
              </div>
              <p className="im-sum-say">
                {summary.learning_from_history
                  ? <>
                      {Number(summary.total_shifts_learned || 0).toLocaleString()} shifts learned across{" "}
                      {summary.employees_learned} {summary.employees_learned === 1 ? "person" : "people"}.
                      Rosters are built from the shifts you actually ran in the last{" "}
                      {summary.lookback_weeks} weeks.
                    </>
                  : <>
                      At least {summary.weeks_needed} weeks are needed before the roster follows your
                      own patterns. Until then it falls back to generic blocks.
                    </>}
              </p>
            </>
          ) : (
            <p className="im-sum-say" style={{ borderTop: 0, paddingTop: 0 }}>
              Nothing imported yet — the scheduler will guess until you add some history.
            </p>
          )}
        </div>
      </div>

      <div className="im-formats">
        {unavailable.length > 0 ? (
          <>
            <span className="im-tag">
              {unavailable.length} format{unavailable.length === 1 ? "" : "s"} unavailable
            </span>
            <span className="im-formats-text">
              {reasons.length > 0
                ? reasons.join(" · ")
                : `${unavailable.join(" and ")} need server setup.`}
              {" "}Spreadsheets and CSV work regardless — they need no AI.
            </span>
          </>
        ) : (
          <>
            <span className="im-tag" data-tone="ok">All formats ready</span>
            <span className="im-formats-text">
              Spreadsheet, CSV, PDF and photo can all be read.
            </span>
          </>
        )}
      </div>

      <ImportedWeeks
        refreshKey={committed}
        summary={summary}
        onChange={() => setCommitted((n) => n + 1)}
        onReplace={() => fileRef.current?.click()}
      />

      <p className="im-note">
        The scheduler learns from the last <strong>{summary?.lookback_weeks || 24} weeks</strong> only, so a
        week older than that reads <strong>Stored only</strong> — it is kept, and it is not being learned
        from. A week flagged <strong>Looks short</strong> has far fewer shifts than the weeks around it,
        which usually means the wrong sheet was read rather than a quiet week; replacing it is normally
        the fix. <strong>Removing a week stops the scheduler learning from it immediately</strong> and
        nothing else changes.
      </p>
    </div>
  );
}

/**
 * The weeks currently in the history, grouped by month, and the only way to
 * take one back out.
 *
 * Imported weeks are stored as approved past weeks, which the app otherwise
 * refuses to reopen — a week that has been worked is a record, not a plan.
 * An import is the exception: loading the wrong sheet is an ordinary mistake,
 * invisible afterwards except through the odd rosters it produces, and
 * without this it would be permanent.
 */
function ImportedWeeks({ refreshKey, summary, onChange, onReplace }) {
  const [weeks, setWeeks] = useState(null);
  const [removed, setRemoved] = useState([]);
  const [confirming, setConfirming] = useState(null);
  const [removing, setRemoving] = useState(false);
  const [restoring, setRestoring] = useState("");

  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("in-use");
  const [visible, setVisible] = useState(PAGE);

  const load = useCallback(() => {
    api.get("/imports/history")
      .then((r) => setWeeks(r.data))
      .catch(() => setWeeks([]));
    api.get("/imports/removed")
      .then((r) => setRemoved(r.data))
      .catch(() => setRemoved([]));
  }, []);
  useEffect(() => { load(); }, [load, refreshKey]);

  const remove = async () => {
    setRemoving(true);
    try {
      await api.delete(`/imports/history/${confirming.roster_id}`);
      toast.success(`Removed the week of ${fmtWeek(confirming.week_start)}`);
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
        `Restored ${fmtWeek(data.week_start)} — ${data.shifts_restored} shift${
          data.shifts_restored === 1 ? "" : "s"}`,
      );
      load();
      onChange?.();
    } catch (err) {
      toast.error(errorMessage(err, "Could not restore that week"));
    } finally { setRestoring(""); }
  };

  const lookback = summary?.lookback_weeks || 24;

  /**
   * A week is stored-only once it falls outside the learning window, and
   * "short" when its shift count sits well under the median of the others.
   * The history carries neither flag, so both are worked out here — the
   * numbers are on the same row, so the reader can check the claim.
   */
  const decorated = useMemo(() => {
    const list = weeks || [];
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - lookback * 7);
    const mid = median(list.map((w) => Number(w.shifts) || 0).filter(Boolean));
    return list.map((w) => {
      const storedOnly = parseDay(w.week_start) < cutoff;
      const shifts = Number(w.shifts) || 0;
      const short = !storedOnly && mid > 0 && shifts < mid * 0.6;
      return { ...w, storedOnly, short, sourceLabel: sourceOf(w) };
    });
  }, [weeks, lookback]);

  const inUseCount = decorated.filter((w) => !w.storedOnly).length;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return decorated.filter((w) => {
      if (scope === "in-use" && w.storedOnly) return false;
      if (!q) return true;
      const hay = [
        w.week_start,
        fmtWeek(w.week_start),
        monthLabel(monthKeyOf(w.week_start)),
        w.source_sheet || "",
        w.filename || "",
      ].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }, [decorated, scope, query]);

  const shown = filtered.slice(0, visible);

  /** Month groups, with each month's totals taken from what is shown. */
  const months = useMemo(() => {
    const map = new Map();
    shown.forEach((w) => {
      const key = monthKeyOf(w.week_start);
      if (!map.has(key)) map.set(key, { key, list: [], shifts: 0, hours: 0 });
      const g = map.get(key);
      g.list.push(w);
      g.shifts += Number(w.shifts) || 0;
      g.hours += Number(w.total_hours) || 0;
    });
    return [...map.values()].map((g) => ({
      ...g,
      allTooOld: g.list.every((w) => w.storedOnly),
    }));
  }, [shown]);

  if (weeks === null) {
    return <div className="im-section"><span className="im-section-sub">Loading imported weeks…</span></div>;
  }

  return (
    <>
      {removed.length > 0 && (
        <div className="im-removed">
          <div className="im-label">Recently removed</div>
          <p className="im-removed-note">
            Still readable from the file you uploaded, so you can put one back without finding the
            original again.
          </p>
          {removed.map((w) => (
            <div className="im-removed-row" key={`${w.import_id}-${w.week_start}`}>
              <span style={{ fontWeight: 700 }}>{fmtWeek(w.week_start)}</span>
              <span style={{ color: "var(--t-muted)" }}>
                {w.shifts} shift{w.shifts === 1 ? "" : "s"}
                {w.filename ? ` · from ${w.filename}` : ""}
              </span>
              <button
                type="button"
                data-testid={`btn-restore-week-${w.week_start}`}
                className="im-act im-act-1"
                disabled={restoring === w.week_start}
                onClick={() => restore(w)}
              >
                {restoring === w.week_start ? "Restoring…" : "Restore"}
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="im-section">
        <div>
          <h2 className="im-h2">
            Imported weeks <span>({decorated.length})</span>
          </h2>
          <p className="im-section-sub">
            Weeks loaded from your files. Remove one if it was the wrong sheet or read badly — the
            scheduler stops learning from it immediately.
          </p>
        </div>
        <div className="im-controls">
          <div className="im-search">
            <Search size={14} color="var(--t-faint)" strokeWidth={1.6} aria-hidden="true" />
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setVisible(PAGE); }}
              placeholder="Search by week"
              aria-label="Search imported weeks"
            />
          </div>
          <button
            type="button"
            className="im-pill"
            aria-pressed={scope === "in-use"}
            onClick={() => { setScope("in-use"); setVisible(PAGE); }}
          >
            In use ({inUseCount})
          </button>
          <button
            type="button"
            className="im-pill"
            aria-pressed={scope === "all"}
            onClick={() => { setScope("all"); setVisible(PAGE); }}
          >
            All ({decorated.length})
          </button>
        </div>
      </div>

      <div className="im-table" role="table" aria-label="Imported weeks">
        <div className="im-row im-colhead" role="row">
          <span role="columnheader">Week beginning</span>
          <span className="im-num" role="columnheader">Shifts</span>
          <span className="im-num" role="columnheader">Hours</span>
          <span role="columnheader">Source</span>
          <span role="columnheader">State</span>
          <span role="columnheader" aria-label="Actions" />
        </div>

        {decorated.length === 0 ? (
          <div className="im-emptyrow">
            No rosters imported yet — the scheduler will guess until you add some history.
          </div>
        ) : filtered.length === 0 ? (
          <div className="im-emptyrow">
            Nothing matches that{scope === "in-use" ? " within the learning window" : ""}.
          </div>
        ) : months.map((g, gi) => (
          <div key={g.key} role="rowgroup">
            <div className="im-monthhead" data-later={gi > 0}>
              <span className="im-monthname">{monthLabel(g.key)} ({g.list.length})</span>
              <span className="im-monthtot">
                {g.allTooOld
                  ? "too old to learn from"
                  : `${g.shifts.toLocaleString()} shifts · ${Math.round(g.hours).toLocaleString()}h`}
              </span>
            </div>

            {g.list.map((w) => (
              <div className="im-row im-data" role="row" key={w.roster_id} data-short={w.short}>
                <span className="im-week-start" role="cell" data-stored={w.storedOnly}>
                  {fmtWeek(w.week_start)}
                </span>
                <span className="im-num im-val" role="cell">{w.shifts}</span>
                <span className="im-num im-val" role="cell" data-short={w.short}>
                  {w.total_hours ? `${Math.round(w.total_hours)}h` : "—"}
                </span>
                <span className="im-source" role="cell" title={w.source_sheet || w.filename || ""}>
                  {w.sourceLabel}
                  {w.source_sheet ? ` · ${w.source_sheet}` : w.filename ? ` · ${w.filename}` : ""}
                </span>
                <span role="cell">
                  {w.storedOnly ? (
                    <span className="im-state-plain">Stored only</span>
                  ) : w.short ? (
                    <span className="im-state-tag" data-tone="short">Looks short</span>
                  ) : (
                    <span className="im-state-tag">In use</span>
                  )}
                </span>
                <span className="im-acts" role="cell">
                  {w.short && (
                    <button
                      type="button"
                      className="im-act im-act-1"
                      onClick={onReplace}
                      aria-label={`Replace the week of ${fmtWeek(w.week_start)}`}
                    >
                      Replace
                    </button>
                  )}
                  <button
                    type="button"
                    data-testid={`btn-remove-week-${w.week_start}`}
                    className="im-act im-act-2"
                    onClick={() => setConfirming(w)}
                    aria-label={`Remove the week of ${fmtWeek(w.week_start)}`}
                  >
                    Remove
                  </button>
                </span>
              </div>
            ))}
          </div>
        ))}

        {filtered.length > 0 && (
          <div className="im-foot">
            <span>
              Showing {shown.length} of {filtered.length} week{filtered.length === 1 ? "" : "s"} —
              grouped by month, newest first
            </span>
            {filtered.length > shown.length && (
              <button type="button" className="im-link" onClick={() => setVisible(filtered.length)}>
                Show all {filtered.length}
              </button>
            )}
          </div>
        )}
      </div>

      {confirming && (
        <ConfirmRemove
          week={confirming}
          busy={removing}
          onCancel={() => setConfirming(null)}
          onConfirm={remove}
        />
      )}
    </>
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
