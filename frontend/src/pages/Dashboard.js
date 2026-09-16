import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage, fmtHours, fmtMoney, mondayOf } from "@/lib/api";
import { toast } from "sonner";
import { CheckCircle2, AlertCircle, Wand2, Sparkles } from "lucide-react";

/**
 * Dashboard — shop home (handoff: Dashboard).
 *
 * Land, see the shop is in a fit state, deal with anything flagged, generate
 * the next roster. Styling is the handoff's palette, scoped to .db-*.
 *
 * Everything is read from endpoints this page already used: /shop,
 * /employees, /rosters, /activity, /setup-status. The force-approval band
 * reads force_approved, force_approved_by, force_approved_reason and
 * overridden_rules, which approve_roster already writes.
 *
 * DEVIATIONS
 *
 * 1. Generate roster navigates to the roster page for the next un-rostered
 *    week rather than running the solver here. Generation carries pinned
 *    shifts, plan limits, refusal dialogs and rebalance-by-day, and a second
 *    implementation of it on this page would drift from the first. The
 *    button still answers the question "which week am I generating?" by
 *    finding that week itself.
 *
 * 2. Recent rosters is a CSS grid with table roles rather than a real
 *    <table>. The handoff asks for both a real table and minmax() tracks,
 *    and a table cannot express minmax. Same choice as the sibling pages.
 *
 * 3. Activity entries carry no actor or link of their own — the log stores
 *    an action and a sentence. The action is mapped to a route so entries
 *    are still clickable, a leading email is emboldened as the actor, and
 *    anything mentioning broken rules is marked in amber.
 *
 * 4. "Load demo team" is kept, shown only when the shop has no employees.
 *    It is how a new shop gets something to look at, and dropping it would
 *    leave the empty state with no way forward but manual entry.
 */

/**
 * Rows per column, chosen so the two columns come out the same height.
 *
 * They are not the same number because the rows are not the same height. A
 * roster row is two short lines and runs about 69px; an activity entry is a
 * sentence that usually wraps in a ~300px column plus a timestamp, about
 * 95px. Six entries is roughly 568px, which is eight roster rows.
 *
 * Both footers are pinned to the bottom of their column, so an uneven count
 * only shows as a gap above one of them — these numbers keep that gap small.
 */
const ACTIVITY_ROWS = 6;
const ROSTER_ROWS = 8;

const iso = (d) => d.toISOString().slice(0, 10);

/** Where an activity entry should take you, by action. */
function hrefForAction(action = "") {
  if (action.startsWith("roster")) return "/roster";
  if (action.startsWith("employee")) return "/employees";
  if (action.startsWith("rule") || action.startsWith("ai_rule")) return "/rules";
  if (action.startsWith("holiday") || action.startsWith("leave")) return "/calendar";
  if (action.startsWith("fixed")) return "/fixed-shifts";
  if (action.startsWith("shop") || action.startsWith("setup")) return "/onboarding";
  return "/roster";
}

/**
 * Render one log line: bold a leading email (the actor the log embeds in its
 * sentence) and pick out anything about broken rules in amber.
 */
function entryParts(detail = "") {
  const text = String(detail);
  const email = text.match(/^\S+@\S+\.\S+/);
  const head = email ? email[0] : null;
  const rest = head ? text.slice(head.length) : text;
  const broken = rest.match(/(\d+\s+rule\(?s?\)?\s+broken)/i);
  if (!broken) return { head, before: rest, warn: null, after: "" };
  const at = rest.indexOf(broken[0]);
  return {
    head,
    before: rest.slice(0, at),
    warn: broken[0],
    after: rest.slice(at + broken[0].length),
  };
}

const fmtStamp = (value) => {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return { label: String(value || ""), iso: "" };
  return {
    label: d.toLocaleString(undefined, {
      weekday: "short", day: "numeric", month: "short",
      hour: "2-digit", minute: "2-digit",
    }),
    iso: d.toISOString(),
  };
};

const fmtWeek = (weekStart) => {
  const d = new Date(`${weekStart}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? weekStart
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

export default function Dashboard() {
  const [shop, setShop] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [rosters, setRosters] = useState([]);
  const [activity, setActivity] = useState([]);
  const [setup, setSetup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const [s, e, r, a, st] = await Promise.all([
        api.get("/shop"),
        api.get("/employees"),
        api.get("/rosters"),
        api.get("/activity").catch(() => ({ data: [] })),
        api.get("/setup-status").catch(() => ({ data: null })),
      ]);
      setShop(s.data);
      setEmployees(e.data || []);
      setRosters(r.data || []);
      setActivity(a.data || []);
      setSetup(st.data);
    } catch (err) {
      toast.error(errorMessage(err, "Could not load the dashboard"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const latest = rosters[0];
  const thisWeek = mondayOf();

  /** The current week's roster, which is what the force band is about. */
  const currentWeek = useMemo(
    () => rosters.find((r) => r.week_start === thisWeek && r.approved)
      || rosters.find((r) => r.week_start === thisWeek)
      || null,
    [rosters, thisWeek],
  );

  const forced = currentWeek?.force_approved ? currentWeek : null;
  const brokenRules = forced?.overridden_rules || [];

  /**
   * The first week from today with no roster at all — the week Generate is
   * actually for. Capped so a fully-rostered shop still gets an answer.
   */
  const nextOpenWeek = useMemo(() => {
    const taken = new Set(rosters.map((r) => r.week_start));
    const d = new Date(`${thisWeek}T00:00:00`);
    for (let i = 0; i < 12; i += 1) {
      const week = iso(d);
      if (!taken.has(week)) return week;
      d.setDate(d.getDate() + 7);
    }
    return thisWeek;
  }, [rosters, thisWeek]);

  /** Approved rosters plus this week's drafts, newest first, capped at five. */
  const recent = useMemo(() => {
    const list = rosters.filter((r) => r.approved || r.week_start === thisWeek);
    return list.slice(0, ROSTER_ROWS);
  }, [rosters, thisWeek]);

  const peakCost = useMemo(
    () => Math.max(0, ...recent.map((r) => Number(r.labor_cost) || 0)),
    [recent],
  );

  const archivedDrafts = useMemo(
    () => rosters.filter((r) => r.week_start === thisWeek && !r.approved).length,
    [rosters, thisWeek],
  );

  const complianceTone = (score) =>
    score == null ? undefined : score < 75 ? "bad" : score < 90 ? "warn" : "good";

  const seedDemo = async () => {
    try {
      await api.post("/seed-demo");
      toast.success("Demo team loaded");
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not load the demo team"));
    }
  };

  const resetAll = async () => {
    if (confirmText !== "RESET") return;
    setResetting(true);
    try {
      await api.post("/dev/reset");
      toast.success("Data reset — the shop is empty");
      setConfirmOpen(false);
      setConfirmText("");
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not reset the shop"));
    } finally {
      setResetting(false);
    }
  };

  const setupComplete = setup?.complete;
  const stepsLeft = setup ? Math.max(0, setup.total - setup.done) : 0;
  const outstanding = (setup?.steps || [])
    .filter((s) => !s.done)
    .map((s) => s.title || s.label || s.id)
    .filter(Boolean);

  if (loading) {
    return <div className="db-page"><div className="db-empty">Loading…</div></div>;
  }

  return (
    <div className="db-page">
      <header className="db-head">
        <div>
          <div className="db-eyebrow">SHOP</div>
          <h1 className="db-h1">{shop?.name || "Your shop"}</h1>
          <p className="db-sub">
            {setupComplete
              ? "Everything is set up. Generate this week's roster in one click."
              : outstanding.length > 0
                ? `Still to do: ${outstanding.slice(0, 3).join(", ")}${outstanding.length > 3 ? `, and ${outstanding.length - 3} more` : ""}.`
                : "Finish setting up the shop before generating a roster."}
          </p>
        </div>
        <div className="db-actions">
          {employees.length === 0 && (
            <button type="button" data-testid="btn-seed" className="db-btn db-btn-2" onClick={seedDemo}>
              <Sparkles size={15} strokeWidth={1.8} /> Load demo team
            </button>
          )}
          <button
            type="button"
            data-testid="btn-reset"
            className="db-btn db-btn-danger"
            onClick={() => { setConfirmText(""); setConfirmOpen(true); }}
            aria-describedby="db-reset-desc"
          >
            Reset all data
          </button>
          <span id="db-reset-desc" className="sr-only">
            Permanently deletes every employee, roster and rule in this shop.
          </span>
          <button
            type="button"
            data-testid="btn-generate-roster"
            className="db-btn db-btn-1"
            onClick={() => navigate(`/roster?week=${nextOpenWeek}`)}
          >
            <Wand2 size={15} strokeWidth={1.8} /> Generate roster
          </button>
        </div>
      </header>

      {setup && (
        <div className="db-setup">
          <div className="db-setup-main">
            {setupComplete ? (
              <CheckCircle2 size={16} color="var(--t-accent)" strokeWidth={1.8} aria-hidden="true" />
            ) : (
              <AlertCircle size={16} color="var(--t-warn)" strokeWidth={1.8} aria-hidden="true" />
            )}
            <span className="db-setup-head" data-state={setupComplete ? "done" : "todo"}>
              {setupComplete ? "Setup complete" : `${stepsLeft} step${stepsLeft === 1 ? "" : "s"} left`}
            </span>
            <span className="db-setup-rest">
              {setupComplete
                ? `· ${employees.length} ${employees.length === 1 ? "person" : "people"}, shop hours and fixed shifts all in place`
                : `· ${outstanding.join(", ")}`}
            </span>
          </div>
          <button type="button" className="db-link" onClick={() => navigate("/onboarding")}>
            {setupComplete ? "Review steps" : "Finish setup"}
          </button>
        </div>
      )}

      <div className="db-stats">
        <div className="db-stat">
          <div className="db-stat-label">Team</div>
          <div className="db-stat-value">
            {employees.length}<span className="db-stat-unit">people</span>
          </div>
        </div>
        <div className="db-stat">
          <div className="db-stat-label">Compliance</div>
          <div className="db-stat-value" data-tone={complianceTone(latest?.compliance_score)}>
            {latest ? latest.compliance_score : "—"}
            {latest && <span className="db-stat-unit">/100</span>}
          </div>
        </div>
        <div className="db-stat">
          <div className="db-stat-label">Weekly cost</div>
          <div className="db-stat-value">{latest ? fmtMoney(latest.labor_cost) : "—"}</div>
        </div>
        <div className="db-stat">
          <div className="db-stat-label">Utilisation</div>
          <div className="db-stat-value">
            {latest ? `${latest.utilization}%` : "—"}
            {latest && <span className="db-stat-unit">of capacity</span>}
          </div>
        </div>
      </div>

      {/* Only when the current week was forced. The absence is the message. */}
      {forced && (
        <div className="db-forced">
          <div className="db-forced-inner">
            <div>
              <div className="db-forced-label">This week was force-approved</div>
              <p className="db-forced-say">
                {forced.version} for the week of {fmtWeek(forced.week_start)} went out with{" "}
                <strong>
                  {brokenRules.length} rule{brokenRules.length === 1 ? "" : "s"} broken
                </strong>
                {forced.force_approved_by ? ` by ${forced.force_approved_by}` : ""}
                {forced.force_approved_reason ? ` — “${forced.force_approved_reason}”` : ""}
                {" "}— worth checking before the same happens next week.
              </p>
            </div>
            <div className="db-forced-acts">
              <button
                type="button"
                className="db-link"
                onClick={() => navigate(`/roster?week=${forced.week_start}&roster=${forced.roster_id}`)}
              >
                See what broke
              </button>
              <button
                type="button"
                className="db-link db-link-mute"
                onClick={() => navigate(`/roster?week=${forced.week_start}`)}
              >
                Open roster
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="db-split">
        <div className="db-left">
          <div className="db-colhead-wrap">
            <h2 className="db-h2">Recent rosters</h2>
            <button type="button" className="db-link" onClick={() => navigate("/roster")}>
              Open roster
            </button>
          </div>

          {recent.length === 0 ? (
            <div className="db-empty">
              <span>No rosters yet — generate your first.</span>
              <button
                type="button"
                className="db-btn db-btn-1"
                onClick={() => navigate(`/roster?week=${nextOpenWeek}`)}
              >
                <Wand2 size={15} strokeWidth={1.8} /> Generate roster
              </button>
            </div>
          ) : (
            <div className="db-tablewrap" role="table" aria-label="Recent rosters">
              <div className="db-row db-colhead" role="row">
                <span role="columnheader">Week · version</span>
                <span className="db-num" role="columnheader">Hours</span>
                <span className="db-num" role="columnheader">Cost</span>
                <span className="db-num" role="columnheader">Score</span>
                <span className="db-num" role="columnheader">State</span>
              </div>

              {recent.map((r) => {
                const cost = Number(r.labor_cost) || 0;
                const stamp = r.approved_at ? fmtStamp(r.approved_at) : null;
                return (
                  <button
                    type="button"
                    key={r.roster_id}
                    className="db-row db-rosterrow"
                    role="row"
                    data-testid={`roster-row-${r.roster_id}`}
                    onClick={() => navigate(`/roster?week=${r.week_start}&roster=${r.roster_id}`)}
                    aria-label={`Week of ${fmtWeek(r.week_start)}, ${r.version}, ${r.approved ? "approved" : "draft"}. Open it.`}
                  >
                    <span role="cell" style={{ minWidth: 0 }}>
                      <span className="db-rowtitle">
                        Week of {fmtWeek(r.week_start)} · {r.version}
                      </span>
                      <span className="db-rowsub">
                        {r.approved
                          ? stamp ? `Approved ${stamp.label}` : "Approved"
                          : r.archived ? "Superseded" : "Draft — not approved"}
                        {r.force_approved ? " · force-approved" : ""}
                      </span>
                    </span>
                    <span className="db-num db-val" role="cell">{fmtHours(r.total_hours)}</span>
                    <span
                      className="db-num db-val"
                      role="cell"
                      data-peak={peakCost > 0 && cost === peakCost}
                    >
                      {fmtMoney(cost)}
                    </span>
                    <span className="db-num db-val" role="cell">{r.compliance_score ?? "—"}</span>
                    <span className="db-num" role="cell">
                      {r.approved
                        ? <span className="db-tag">Approved</span>
                        : <span className="db-state-draft">Draft</span>}
                    </span>
                  </button>
                );
              })}

              <div className="db-listfoot">
                <span>
                  {archivedDrafts > 0
                    ? `${archivedDrafts} draft${archivedDrafts === 1 ? "" : "s"} for the week of ${fmtWeek(thisWeek)}`
                    : `Showing ${recent.length} of ${rosters.length}`}
                </span>
                <button type="button" className="db-link" onClick={() => navigate("/past")}>
                  Past rosters
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="db-right">
          <div className="db-colhead-wrap">
            <h2 className="db-h2">Activity</h2>
            <span className="db-today">Latest</span>
          </div>

          {activity.length === 0 ? (
            <div className="db-empty">Nothing has happened yet.</div>
          ) : (
            <>
              <ol className="db-feed">
                {activity.slice(0, ACTIVITY_ROWS).map((a) => {
                  const parts = entryParts(a.detail);
                  const stamp = fmtStamp(a.created_at);
                  return (
                    <li className="db-entry" key={a.log_id}>
                      <button
                        type="button"
                        className="db-entry-btn"
                        onClick={() => navigate(hrefForAction(a.action))}
                      >
                        <span className="db-entry-text">
                          {parts.head && <strong>{parts.head}</strong>}
                          {parts.before}
                          {parts.warn && <em>{parts.warn}</em>}
                          {parts.after}
                        </span>
                        <time className="db-entry-time" dateTime={stamp.iso}>{stamp.label}</time>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <div className="db-listfoot">
                <span>
                  {activity.length > ACTIVITY_ROWS
                    ? `Showing ${ACTIVITY_ROWS} of ${activity.length}`
                    : `${activity.length} recent`}
                </span>
                <button type="button" className="db-link" onClick={() => navigate("/roster")}>
                  Show everything
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <p className="db-note">
        <strong>Generate roster</strong> builds a draft for the next week with no roster yet
        {nextOpenWeek ? ` — currently the week of ${fmtWeek(nextOpenWeek)}` : ""}. It never overwrites an
        approved roster: reopening one starts a new version and says so.{" "}
        <strong>Reset all data cannot be undone</strong> — it deletes every employee, roster, rule and
        fixed shift in this shop, and there is no copy kept.
      </p>

      {confirmOpen && (
        <div className="db-scrim" onClick={() => !resetting && setConfirmOpen(false)}>
          <div
            className="db-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Reset all data"
            onClick={(e) => e.stopPropagation()}
          >
            <h2>Reset all data</h2>
            <p>
              This deletes <strong>every employee, roster, rule and fixed shift</strong> in{" "}
              {shop?.name || "this shop"}. It cannot be undone and no copy is kept.
            </p>
            <label className="db-setup-rest" htmlFor="db-confirm">
              Type RESET to confirm
            </label>
            <input
              id="db-confirm"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="RESET"
              autoComplete="off"
              style={{ marginTop: 8 }}
            />
            <div className="db-dialog-acts">
              <button
                type="button"
                className="db-btn db-btn-danger"
                disabled={confirmText !== "RESET" || resetting}
                onClick={resetAll}
              >
                {resetting ? "Resetting…" : "Reset everything"}
              </button>
              <button
                type="button"
                className="db-link db-link-mute"
                disabled={resetting}
                onClick={() => setConfirmOpen(false)}
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
