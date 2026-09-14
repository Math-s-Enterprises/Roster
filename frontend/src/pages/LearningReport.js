/**
 * What the scheduler has learned from being corrected.
 *
 * WHY THIS SCREEN EXISTS
 *
 * The falling edit count is the product proving its worth every week. A shop
 * whose rosters needed six edits and now need one can see that, and it is
 * specific to them — a competitor cannot copy it, because it is built out of
 * their own corrections.
 *
 * The suggestions are the other half. When the same edit has been made three
 * times, the scheduler offers to change a real setting — a fixed shift, a day
 * off, an availability window — rather than quietly weighting something in the
 * background. Learning you cannot inspect is learning you cannot trust, and if
 * it has concluded something wrong the manager must be able to find out from a
 * screen rather than from a bad roster. Which is why every suggestion can be
 * refused, and refusing is permanent.
 *
 * Layout is the handoff's, scoped to .wl-* in index.css: a three-stat band, a
 * two-column explanation split, one table of every logged change.
 *
 * DEVIATIONS
 *
 * 1. "Set up now" appears only once a pattern has reached the repeat
 *    threshold, not at ×2 as the handoff says. POST /reports/corrections/apply
 *    looks the signature up among the real suggestions and 404s otherwise, so
 *    an earlier button could only fail.
 *
 * 2. There is no "Undo refusal". Refusals are stored, and the API has dismiss
 *    but nothing to reverse it — matching the product decision that refusing
 *    is permanent. Refused rows say so rather than offering an action that
 *    does not exist.
 *
 * 3. Refused rows are derived, not flagged: the report returns a count of
 *    refusals but not which ones. A pattern at or past the threshold that is
 *    absent from the suggestion list has been refused, which is the only way
 *    it can be missing.
 *
 * 4. Rows are a CSS grid with table roles rather than a real <table> — the
 *    handoff asks for both a real table and minmax() tracks, and a table
 *    cannot express minmax. Same choice as the sibling pages.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage, DAY_LABELS, DAYS } from "@/lib/api";
import { toast } from "sonner";
import { Download } from "lucide-react";

const SORT_KEY = "roster_learning_sort";
const PAGE = 7;

const SORTS = [
  { key: "most-repeated", label: "Most repeated" },
  { key: "by-day", label: "By day" },
  { key: "newest", label: "Newest" },
];

/** What accepting a suggestion actually creates, and where it will live. */
const LANDS_IN = {
  fixed_shift: "This becomes a template on Fixed Shifts.",
  day_off: "This becomes a guaranteed day off on the employee's record.",
  earliest_start: "This changes the availability window on the employee's record.",
};

const fmtWeek = (weekStart) => {
  const d = new Date(`${weekStart}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? weekStart
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

/** Join week labels the way a person would say them. */
function listWeeks(weeks) {
  const names = weeks.map(fmtWeek);
  if (names.length === 0) return "";
  if (names.length === 1) return `the week of ${names[0]}`;
  return `weeks of ${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * One correction as a sentence, in the manager's own voice and past tense.
 * A screen full of `{kind: "removed", slot: "09:00-17:00"}` is data, not an
 * explanation, and the point of this page is that somebody can disagree
 * with what it says.
 */
function describe(p) {
  const who = p.employee_name || "Someone";
  if (p.kind === "swap") return `You used ${who} instead of ${p.replaced_employee_name} for ${p.slot}`;
  if (p.kind === "moved") return `You moved ${who} from ${p.from_slot} to ${p.to_slot}`;
  if (p.kind === "removed") return `You took ${who} off (${p.slot})`;
  return `You added ${who} · ${p.slot}`;
}

export default function LearningReport() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [sort, setSort] = useState(() => localStorage.getItem(SORT_KEY) || "most-repeated");
  const [visible, setVisible] = useState(PAGE);
  const [confirming, setConfirming] = useState(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const r = await api.get("/reports/corrections");
      setReport(r.data);
    } catch (err) {
      toast.error(errorMessage(err, "Could not load what has been learned"));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const chooseSort = (key) => { setSort(key); localStorage.setItem(SORT_KEY, key); };

  const minRepeats = report?.min_repeats ?? 3;
  const patterns = useMemo(() => report?.patterns || [], [report]);
  const suggestions = useMemo(() => report?.suggestions || [], [report]);

  /** Signatures the scheduler is currently willing to act on. */
  const offered = useMemo(
    () => new Set(suggestions.map((s) => s.signature)),
    [suggestions],
  );

  /** Only measured weeks count — a roster with no snapshot cannot be compared. */
  const measured = useMemo(
    () => (report?.trend || []).filter((t) => t.measurable),
    [report],
  );
  const lastThree = useMemo(() => measured.slice(-3), [measured]);

  const editsLast = measured.length ? measured[measured.length - 1].edit_count : 0;
  const editsPrev = measured.length > 1 ? measured[measured.length - 2].edit_count : null;
  const rose = editsPrev != null && editsLast > editsPrev;

  const rows = useMemo(() => {
    const list = patterns.map((p) => {
      const weeks = p.weeks || [];
      const ready = p.count >= minRepeats;
      const refused = ready && !offered.has(p.signature);
      return {
        ...p,
        lastWeek: weeks.length ? [...weeks].sort().at(-1) : "",
        ready,
        refused,
        remaining: Math.max(0, minRepeats - p.count),
      };
    });
    if (sort === "by-day") {
      return list.sort((a, b) =>
        (DAYS.indexOf(a.day) - DAYS.indexOf(b.day)) || (b.count - a.count));
    }
    if (sort === "newest") {
      return list.sort((a, b) =>
        String(b.lastWeek).localeCompare(String(a.lastWeek)) || (b.count - a.count));
    }
    return list.sort((a, b) =>
      (b.count - a.count) || String(b.lastWeek).localeCompare(String(a.lastWeek)));
  }, [patterns, sort, minRepeats, offered]);

  const shown = rows.slice(0, visible);

  const decide = async (signature, accept) => {
    setBusy(signature);
    try {
      const r = await api.post(
        `/reports/corrections/${accept ? "apply" : "dismiss"}`, { signature },
      );
      toast.success(accept ? `Set up — ${r.data.detail}` : "Won't be offered again");
      setConfirming(null);
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save that"));
    } finally { setBusy(""); }
  };

  const exportCsv = () => {
    if (rows.length === 0) {
      toast.error("No changes to export yet");
      return;
    }
    const escape = (v) => {
      const str = String(v ?? "");
      return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
    };
    const out = [
      ["Times", "Day", "What you changed", "State", "Weeks seen"],
      ...rows.map((p) => [
        p.count,
        DAY_LABELS[p.day] || p.day,
        describe(p),
        p.refused ? "Refused" : p.ready ? "Ready to set up" : `${p.remaining} more to offer`,
        (p.weeks || []).join(" / "),
      ]),
    ];
    const csv = out.map((r) => r.map(escape).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `changes-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${rows.length} ${rows.length === 1 ? "change" : "changes"}`);
  };

  if (loading) {
    return <div className="wl-page"><div className="wl-emptyrow" style={{ padding: 28 }}>Reading your corrections…</div></div>;
  }
  if (!report) return null;

  const suggestion = confirming
    ? suggestions.find((s) => s.signature === confirming)
    : null;

  return (
    <div className="wl-page">
      <header className="wl-head">
        <div>
          <div className="wl-eyebrow">LEARNING</div>
          <h1 className="wl-h1">What the scheduler has learned</h1>
          <p className="wl-sub">
            Every edit you make to a generated roster is the most useful thing this app sees — it is
            you saying what “right” looks like here.
          </p>
        </div>
        <button type="button" className="wl-btn" onClick={exportCsv} disabled={rows.length === 0}>
          <Download size={15} strokeWidth={1.6} /> Export changes
        </button>
      </header>

      <div className="wl-stats">
        <div className="wl-stat">
          <div className="wl-stat-label">Edits last week</div>
          <div className="wl-stat-value" data-tone={rose ? "warn" : "good"}>{editsLast}</div>
          <div className="wl-stat-cap">
            {editsPrev == null
              ? measured.length ? "first measured week" : "nothing measured yet"
              : `${rose ? "up" : "down"} from ${editsPrev}`}
          </div>
        </div>
        <div className="wl-stat">
          <div className="wl-stat-label">Weekly average</div>
          <div className="wl-stat-value">
            {measured.length >= 3 && report.average_per_week != null ? report.average_per_week : "—"}
          </div>
          <div className="wl-stat-cap">
            {measured.length >= 3
              ? `across ${measured.length} rosters`
              : `${measured.length} roster${measured.length === 1 ? "" : "s"} measured — too few to average`}
          </div>
        </div>
        <div className="wl-stat">
          <div className="wl-stat-label">Refused</div>
          <div className="wl-stat-value">{report.dismissed_count || 0}</div>
          <div className="wl-stat-cap">never offered again</div>
        </div>
      </div>

      <div className="wl-split">
        <div className="wl-left">
          <div className="wl-label">Things you keep changing by hand</div>
          {suggestions.length === 0 ? (
            <>
              <p className="wl-body">
                <strong>Nothing yet.</strong> Make the same change {minRepeats} weeks running — moving
                somebody off a day, adding a shift the generator missed, always lengthening the same
                shift — and it will offer to set that up permanently.
              </p>
              {report.dismissed_count > 0 && (
                <p className="wl-aside">
                  You have refused {report.dismissed_count} so far; those are not offered again.
                </p>
              )}
            </>
          ) : (
            <>
              <p className="wl-body">
                Each of these has come up at least {minRepeats} times. Setting one up changes a real
                setting you can see and undo — nothing is hidden.
              </p>
              <div className="wl-ready">
                {suggestions.map((s) => (
                  <div className="wl-ready-row" key={s.signature}>
                    <span className="wl-ready-text">
                      {s.employee_name} · {s.headline}
                      <span className="wl-ready-why">{s.because}</span>
                    </span>
                    <button
                      type="button"
                      data-testid={`apply-${s.signature}`}
                      className="wl-link"
                      onClick={() => setConfirming(s.signature)}
                      aria-label={`Set up ${s.employee_name}, ${s.headline}`}
                    >
                      Set up now
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="wl-right">
          <div className="wl-label">Edits needed per roster</div>
          {lastThree.length === 0 ? (
            <p className="wl-run-note">
              Nothing measured yet. Approve a roster you have edited and this starts filling in.
            </p>
          ) : (
            <>
              <div className="wl-run">
                {lastThree.map((t, i) => (
                  <React.Fragment key={t.week_start}>
                    {i > 0 && <span className="wl-run-sep" aria-hidden="true">·</span>}
                    {i === lastThree.length - 1
                      ? <em>{t.edit_count}</em>
                      : <span>{t.edit_count}</span>}
                  </React.Fragment>
                ))}
              </div>
              <p className="wl-run-note">
                {listWeeks(lastThree.map((t) => t.week_start))
                  .replace(/^w/, "W")
                  .replace(/^the w/, "The w")}.{" "}
                {measured.length >= 3 && report.average_per_week != null
                  ? `Averaging ${report.average_per_week} a week`
                  : "Too few weeks to average yet"}
                {editsLast === 0
                  ? " — last week needed none at all."
                  : editsPrev != null && editsLast < editsPrev
                    ? " — last week needed fewer."
                    : "."}
              </p>
            </>
          )}
        </div>
      </div>

      <div className="wl-section">
        <div>
          <h2 className="wl-h2">
            Every change you have made <span>({patterns.length})</span>
          </h2>
          <p className="wl-section-sub">
            Across your last {report.weeks_measured}{" "}
            approved {report.weeks_measured === 1 ? "roster" : "rosters"}. Shown whether or not it has
            been repeated often enough to act on.
          </p>
        </div>
        <div className="wl-sorts" role="group" aria-label="Sort changes">
          {SORTS.map((s) => (
            <button
              key={s.key}
              type="button"
              className="wl-sort"
              aria-pressed={sort === s.key}
              onClick={() => chooseSort(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="wl-table" role="table" aria-label="Every change you have made">
        <div className="wl-row wl-colhead" role="row">
          <span role="columnheader">Times</span>
          <span role="columnheader">Day</span>
          <span role="columnheader">What you changed</span>
          <span role="columnheader">State</span>
          <span role="columnheader" aria-label="Actions" />
        </div>

        {patterns.length === 0 ? (
          <div className="wl-emptyrow">
            No edits yet — generate and adjust a roster and your changes appear here.
          </div>
        ) : shown.map((p) => (
          <div className="wl-row wl-data" role="row" key={p.signature} data-refused={p.refused}>
            <span className="wl-times" role="cell">×{p.count}</span>
            <span className="wl-day" role="cell">{DAY_LABELS[p.day] || p.day}</span>
            <span className="wl-what" role="cell">{describe(p)}</span>
            <span className="wl-state" role="cell" data-refused={p.refused}>
              {p.refused
                ? "Refused — not offered again"
                : p.ready
                  ? "Ready to set up"
                  : `${p.remaining} more to offer`}
            </span>
            <span className="wl-acts" role="cell">
              {p.refused ? (
                <span className="wl-state">—</span>
              ) : p.ready ? (
                <button
                  type="button"
                  className="wl-link"
                  disabled={busy === p.signature}
                  onClick={() => setConfirming(p.signature)}
                  aria-label={`Set up ${describe(p)}`}
                >
                  Set up now
                </button>
              ) : (
                <button
                  type="button"
                  className="wl-link wl-link-mute"
                  onClick={() => navigate(`/roster?week=${p.lastWeek}`)}
                  aria-label={`Open the week of ${fmtWeek(p.lastWeek)}`}
                >
                  Open week
                </button>
              )}
            </span>
          </div>
        ))}

        {patterns.length > 0 && (
          <div className="wl-foot">
            <span>Showing {shown.length} of {rows.length} changes</span>
            {rows.length > shown.length && (
              <button type="button" className="wl-link" onClick={() => setVisible(rows.length)}>
                Show all {rows.length}
              </button>
            )}
          </div>
        )}
      </div>

      <p className="wl-note">
        A change has to repeat across <strong>{minRepeats} approved rosters</strong> before it is
        offered — <strong>one-offs are noise, repeats are policy</strong>. Drafts never count, so
        regenerating a week twice cannot fake a pattern. <strong>Set up now</strong> writes the real
        setting behind the change — a fixed shift, a day off, an availability window — where anyone
        can find and undo it in the ordinary screens; nothing is weighted invisibly.{" "}
        <strong>Refusing removes a pattern from consideration for good</strong>, so it will not be
        raised again.
      </p>

      {suggestion && (
        <div className="wl-scrim" onClick={() => !busy && setConfirming(null)}>
          <div
            className="wl-sheet"
            role="dialog"
            aria-modal="true"
            aria-label="Set this up permanently"
            onClick={(e) => e.stopPropagation()}
          >
            <h2>Set this up permanently?</h2>
            <p>
              <strong>{suggestion.employee_name} · {suggestion.headline}</strong>
            </p>
            <p>{suggestion.because}</p>
            <div className="wl-sheet-where">
              {LANDS_IN[suggestion.action] || "This writes a real setting you can see and change."}
              {suggestion.effect ? ` ${suggestion.effect}` : ""}
            </div>
            <div className="wl-sheet-acts">
              <button
                type="button"
                className="wl-btn wl-btn-1"
                disabled={busy === suggestion.signature}
                onClick={() => decide(suggestion.signature, true)}
              >
                {busy === suggestion.signature ? "Setting up…" : "Set it up"}
              </button>
              <button
                type="button"
                data-testid={`dismiss-${suggestion.signature}`}
                className="wl-link wl-link-mute"
                disabled={busy === suggestion.signature}
                onClick={() => decide(suggestion.signature, false)}
              >
                Not for me
              </button>
              <button
                type="button"
                className="wl-link wl-link-mute"
                disabled={busy === suggestion.signature}
                onClick={() => setConfirming(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
