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
 * background. That matters: learning you cannot inspect is learning you cannot
 * trust, and if it has concluded something wrong the manager must be able to
 * find out from a screen rather than from a bad roster.
 *
 * Which is why every suggestion can be refused, and refusing is permanent.
 */
import React, { useEffect, useState } from "react";
import { api, errorMessage, DAY_LABELS } from "@/lib/api";
import { toast } from "sonner";
import { Check, X, TrendingDown, Sparkles, RefreshCw } from "lucide-react";

const ACTION_LABEL = {
  fixed_shift: "Fixed shift",
  day_off: "Day off",
  earliest_start: "Availability",
};

export default function LearningReport() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/reports/corrections");
      setReport(r.data);
    } catch (err) {
      toast.error(errorMessage(err, "Could not load what has been learned"));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const decide = async (signature, accept) => {
    setBusy(signature);
    try {
      const r = await api.post(
        `/reports/corrections/${accept ? "apply" : "dismiss"}`, { signature },
      );
      toast.success(accept ? `Learned — ${r.data.detail}` : "Won't suggest that again");
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save that"));
    } finally { setBusy(""); }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center gap-2 text-[13px]"
           style={{ color: "var(--ink-mute)" }}>
        <RefreshCw size={14} className="animate-spin" /> Reading your corrections…
      </div>
    );
  }
  if (!report) return null;

  const measured = report.trend.filter((t) => t.measurable);
  const counts = measured.map((t) => t.edit_count);
  const peak = Math.max(1, ...counts);

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-2xl font-medium">What the scheduler has learned</h1>
      <p className="text-[13px] mt-1 mb-8" style={{ color: "var(--ink-mute)" }}>
        Every edit you make to a generated roster is the most useful thing this
        app sees — it is you saying what "right" looks like here.
      </p>

      {/* ---- the number that matters ---- */}
      <div className="card p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <TrendingDown size={15} style={{ color: "var(--accent)" }} />
          <h2 className="text-sm font-medium">Edits needed per roster</h2>
        </div>

        {measured.length === 0 ? (
          <p className="text-[13px]" style={{ color: "var(--ink-mute)" }}>
            Nothing to show yet. Approve a roster you have edited and this
            starts filling in.
          </p>
        ) : (
          <>
            <div className="flex items-end gap-4 h-28">
              {measured.map((week) => (
                <div key={week.week_start} className="flex-1 flex flex-col items-center gap-1">
                  <div className="text-[13px] font-mono">{week.edit_count}</div>
                  <div
                    className="w-full rounded-t"
                    style={{
                      // A clean week is the goal, so it still gets a visible
                      // sliver rather than nothing at all.
                      height: `${Math.max(4, (week.edit_count / peak) * 80)}px`,
                      background: week.edit_count === 0
                        ? "var(--good)" : "var(--accent)",
                      opacity: week.edit_count === 0 ? 1 : 0.75,
                    }}
                  />
                  <div className="text-[10px] font-mono" style={{ color: "var(--ink-mute-2)" }}>
                    {week.week_start?.slice(5)}
                  </div>
                </div>
              ))}
            </div>
            <div className="text-[13px] mt-4" style={{ color: "var(--ink-secondary)" }}>
              {report.clean_weeks > 0 && (
                <>
                  <span style={{ color: "var(--ink)" }}>
                    {report.clean_weeks} of the last {report.weeks_measured}
                  </span>{" "}
                  needed no changes at all.{" "}
                </>
              )}
              {report.average_per_week !== null && (
                <>Averaging {report.average_per_week} edits a week.</>
              )}
            </div>
          </>
        )}
      </div>

      {/* ---- suggestions ---- */}
      {report.suggestions.length > 0 && (
        <div className="card p-6 mb-6">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={15} style={{ color: "var(--accent)" }} />
            <h2 className="text-sm font-medium">
              Things you keep changing by hand
            </h2>
          </div>
          <p className="text-[13px] mb-5" style={{ color: "var(--ink-mute)" }}>
            Each of these has come up at least {report.min_repeats} times.
            Accepting one changes a real setting you can see and undo — nothing
            is hidden.
          </p>

          <div className="space-y-3">
            {report.suggestions.map((s) => (
              <div key={s.signature} className="card-soft p-4">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="pill">{ACTION_LABEL[s.action] || s.action}</span>
                      <span className="text-[13px]" style={{ color: "var(--ink)" }}>
                        {s.employee_name} · {s.headline}
                      </span>
                    </div>
                    <div className="text-[13px] mt-2" style={{ color: "var(--ink-secondary)" }}>
                      {s.because}
                    </div>
                    <div className="text-[11px] mt-1" style={{ color: "var(--ink-mute-2)" }}>
                      {s.effect}
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      data-testid={`dismiss-${s.signature}`}
                      onClick={() => decide(s.signature, false)}
                      disabled={busy === s.signature}
                      className="btn btn-ghost"
                      title="Never suggest this again"
                    >
                      <X size={13} /> No
                    </button>
                    <button
                      data-testid={`apply-${s.signature}`}
                      onClick={() => decide(s.signature, true)}
                      disabled={busy === s.signature}
                      className="btn btn-primary"
                    >
                      <Check size={13} /> Do it
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---- the evidence, unfiltered ---- */}
      <div className="card p-6">
        <h2 className="text-sm font-medium mb-1">Every change you have made</h2>
        <p className="text-[13px] mb-4" style={{ color: "var(--ink-mute)" }}>
          Across your last {report.weeks_measured} approved{" "}
          {report.weeks_measured === 1 ? "roster" : "rosters"}. Shown whether or
          not it has been repeated often enough to act on.
        </p>

        {report.patterns.length === 0 ? (
          <p className="text-[13px]" style={{ color: "var(--ink-mute)" }}>
            No corrections recorded — the rosters went out as generated.
          </p>
        ) : (
          <div className="space-y-1.5">
            {report.patterns.map((p) => (
              <div key={p.signature}
                   className="flex items-center gap-3 text-[13px] py-1.5"
                   style={{ borderBottom: "1px solid var(--hairline)" }}>
                <span className="font-mono text-[11px] w-8 shrink-0"
                      style={{ color: p.count >= report.min_repeats
                        ? "var(--accent)" : "var(--ink-mute-2)" }}>
                  ×{p.count}
                </span>
                <span className="w-20 shrink-0" style={{ color: "var(--ink-mute-2)" }}>
                  {DAY_LABELS[p.day] || p.day}
                </span>
                <span className="flex-1 min-w-0 truncate">
                  {describe(p)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * One correction as a sentence.
 *
 * Written the way a manager would say it out loud — "you took Jane off
 * Wednesday" — rather than as a field dump. A screen full of
 * `{kind: "removed", slot: "09:00-17:00"}` is data, not an explanation, and
 * the point of this page is that somebody can disagree with what it says.
 */
function describe(p) {
  const who = p.employee_name || "Someone";
  if (p.kind === "swap") {
    return `You used ${who} instead of ${p.replaced_employee_name} for ${p.slot}`;
  }
  if (p.kind === "moved") {
    return `You moved ${who} from ${p.from_slot} to ${p.to_slot}`;
  }
  if (p.kind === "removed") {
    return `You took ${who} off (${p.slot})`;
  }
  return `You added ${who} (${p.slot})`;
}
