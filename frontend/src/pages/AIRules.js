import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { toast } from "sonner";
import { Plus } from "lucide-react";

/**
 * AI rules engine — table layout (handoff: AI rules).
 *
 * The form-plus-cards layout became one table grouped LEGAL / SAFETY /
 * CUSTOM, with creation moved to a drawer behind the New rule button.
 * Styling is the handoff's palette, scoped to .air-* in index.css.
 *
 * WHERE THIS DEPARTS FROM THE HANDOFF, AND WHY
 *
 * The handoff's state machine goes Compile -> "On · compiled". The backend
 * does not work that way and deliberately so: POST /compile sets
 * approved:false, and the solver honours a rule only once a human approves
 * the compiled constraint. The comment on that endpoint says why — it stops
 * a model misreading a rule from silently changing how people are
 * scheduled. Printing "On · compiled" over an unapproved rule would tell
 * the manager their constraint is live while the solver ignores it, which
 * is exactly the failure the approval step exists to prevent.
 *
 * So the STATE column reports what the solver is actually doing:
 *
 *   Always on      locked system rule, enforced, cannot be changed
 *   Enforced       compiled and approved
 *   Needs approval compiled, awaiting sign-off — NOT enforced yet
 *   Not in force   no compiled constraint; the solver cannot read it
 *   Paused         enabled:false
 *
 * "Not in force" is the one worth keeping. A rule the parser could not
 * read saves, displays, and does nothing; before this the page showed it
 * looking like any other rule.
 *
 * Other departures, all forced by the API:
 *   - Locked rules expose no actions. compile/update/delete all 403 on
 *     them, so a Compile button there could only ever fail.
 *   - Pause takes no reason. There is no field to store one.
 *   - No "Needs compiling" state and no "last compiled" timestamp in the
 *     footer: a rule carries no compiledAt or textUpdatedAt, so staleness
 *     cannot be derived. Editing re-compiles automatically anyway.
 */

const FILTERS = [
  { key: "all", label: "All" },
  { key: "legal", label: "Legal" },
  { key: "safety", label: "Safety" },
  { key: "custom", label: "Custom" },
];

const GROUPS = [
  { key: "legal", caption: "CANNOT BE TURNED OFF" },
  { key: "safety", caption: null },
  { key: "custom", caption: "WRITTEN BY YOU" },
];

/** What the solver is actually doing with this rule. */
function stateOf(rule) {
  if (rule.locked) return { key: "always", label: "Always on", tone: "on" };
  if (rule.enabled === false) return { key: "paused", label: "Paused", tone: "off" };
  if (rule.compiled && rule.approved) return { key: "enforced", label: "Enforced", tone: "on" };
  if (rule.compiled) {
    return {
      key: "needs-approval",
      label: "Needs approval",
      tone: "warn",
      why: "not enforced yet",
    };
  }
  return {
    key: "not-in-force",
    label: "Not in force",
    tone: "bad",
    why: "nothing compiled",
  };
}

/** A rule counts as live only when the solver will actually apply it. */
const isLive = (rule) =>
  rule.enabled !== false && (rule.locked || (rule.compiled && rule.approved));

/** Plain-English readback of what the compiler understood. */
function understood(rule) {
  if (!rule.compiled) return null;
  const base = rule.compiled.description || rule.compiled.type?.replace(/_/g, " ");
  if (!base) return null;
  const days = Array.isArray(rule.compiled.days) && rule.compiled.days.length
    ? ` · ${rule.compiled.days.join(", ")}`
    : "";
  return `Understood as: ${base}${days}`;
}

export default function AIRules() {
  const [rules, setRules] = useState([]);
  const [filter, setFilter] = useState("all");
  const [compiling, setCompiling] = useState(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(null); // { rule_id?, title, description }

  const load = useCallback(async () => {
    try {
      setRules((await api.get("/ai-rules")).data || []);
    } catch (err) {
      toast.error(errorMessage(err, "Could not load rules"));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => {
    const by = { legal: 0, safety: 0, custom: 0 };
    rules.forEach((r) => { if (by[r.category] !== undefined) by[r.category] += 1; });
    return by;
  }, [rules]);

  const hero = useMemo(() => ({
    live: rules.filter(isLive).length,
    total: rules.length,
    paused: rules.filter((r) => !r.locked && r.enabled === false).length,
    pending: rules.filter((r) => !r.locked && r.enabled !== false && r.compiled && !r.approved).length,
    dead: rules.filter((r) => !r.locked && r.enabled !== false && !r.compiled).length,
  }), [rules]);

  const shown = useMemo(
    () => (filter === "all" ? rules : rules.filter((r) => r.category === filter)),
    [rules, filter],
  );

  const stale = useMemo(
    () => rules.filter((r) => !r.locked && r.enabled !== false && !(r.compiled && r.approved)),
    [rules],
  );

  // --- mutations ----------------------------------------------------

  const save = async () => {
    if (!draft?.title?.trim() || !draft?.description?.trim()) return;
    setBusy(true);
    const payload = {
      title: draft.title.trim(),
      description: draft.description.trim(),
      category: draft.category || "custom",
      enabled: true,
    };
    try {
      if (draft.rule_id) {
        await api.put(`/ai-rules/${draft.rule_id}`, payload);
        toast.success("Rule updated — re-read and re-checked");
      } else {
        await api.post("/ai-rules", payload);
        toast.success("Rule added");
      }
      setDraft(null);
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not save the rule"));
    } finally {
      setBusy(false);
    }
  };

  const compile = async (rule) => {
    setCompiling(rule.rule_id);
    try {
      await api.post(`/ai-rules/${rule.rule_id}/compile`);
      toast.success("Compiled — review it, then approve to enforce");
      await load();
    } catch (err) {
      // 503 means no ANTHROPIC_API_KEY on the server. Saying so is more use
      // than "compilation failed", which sounds like the wording was wrong.
      const status = err?.response?.status;
      toast.error(status === 503
        ? "The rule compiler is switched off on the server (no AI key configured)."
        : errorMessage(err, "Could not compile the rule"));
    } finally {
      setCompiling(null);
    }
  };

  const approve = async (rule) => {
    try {
      await api.post(`/ai-rules/${rule.rule_id}/approve-compiled`);
      toast.success("Approved — the solver will enforce it");
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not approve the rule"));
    }
  };

  const setEnabled = async (rule, enabled) => {
    try {
      await api.put(`/ai-rules/${rule.rule_id}`, {
        title: rule.title,
        description: rule.description,
        category: rule.category,
        enabled,
      });
      toast.success(enabled ? "Resumed" : "Paused — the solver will ignore it");
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not change the rule"));
    }
  };

  const remove = async (rule) => {
    if (!window.confirm(
      `Remove ${rule.title}?\n\nRosters already generated are unchanged.`
    )) return;
    try {
      await api.delete(`/ai-rules/${rule.rule_id}`);
      toast.success("Rule removed");
      await load();
    } catch (err) {
      toast.error(errorMessage(err, "Could not remove the rule"));
    }
  };

  /** Compile everything the solver is not currently enforcing. */
  const compileAll = async () => {
    if (stale.length === 0) return;
    setBusy(true);
    let ok = 0;
    let failed = 0;
    for (const rule of stale) {
      try {
        await api.post(`/ai-rules/${rule.rule_id}/compile`);
        ok += 1;
      } catch {
        failed += 1;
      }
    }
    setBusy(false);
    await load();
    if (ok && !failed) toast.success(`Compiled ${ok} — approve them to enforce`);
    else if (ok) toast.warning(`Compiled ${ok}, ${failed} failed`);
    else toast.error("Nothing compiled — the rule compiler may be switched off on the server.");
  };

  // --- rendering ----------------------------------------------------

  const actionsFor = (rule) => {
    const state = stateOf(rule);
    const custom = rule.category === "custom";

    // Locked rules reject compile, update and delete with a 403, so a
    // button here could only ever fail.
    if (rule.locked) return <span className="air-none">System rule</span>;

    const acts = [];
    if (state.key === "needs-approval") {
      acts.push(
        <button key="a" type="button" className="air-act air-act-1"
          onClick={() => approve(rule)} aria-label={`Approve ${rule.title}`}>
          Approve
        </button>
      );
    }
    if (state.key === "not-in-force" || state.key === "needs-approval") {
      acts.push(
        <button key="c" type="button" className="air-act air-act-2"
          disabled={compiling === rule.rule_id}
          onClick={() => compile(rule)} aria-label={`Compile ${rule.title}`}>
          {compiling === rule.rule_id ? "Compiling…" : "Compile"}
        </button>
      );
    }
    if (state.key === "paused") {
      acts.push(
        <button key="r" type="button" className="air-act air-act-1"
          onClick={() => setEnabled(rule, true)} aria-label={`Resume ${rule.title}`}>
          Resume
        </button>
      );
    }
    if (state.key === "enforced") {
      acts.push(
        <button key="p" type="button" className="air-act air-act-2"
          onClick={() => setEnabled(rule, false)} aria-label={`Pause ${rule.title}`}>
          Pause
        </button>
      );
    }
    if (custom) {
      acts.push(
        <button key="e" type="button" className="air-act air-act-2"
          onClick={() => setDraft({ ...rule })} aria-label={`Edit ${rule.title}`}>
          Edit
        </button>
      );
      acts.push(
        <button key="d" type="button" className="air-act air-act-2 air-act-del"
          onClick={() => remove(rule)} aria-label={`Delete ${rule.title}`}>
          Delete
        </button>
      );
    }
    return acts.length ? acts : <span className="air-none">—</span>;
  };

  const row = (rule) => {
    const state = stateOf(rule);
    const read = understood(rule);
    return (
      <div
        className="air-row air-rule"
        role="row"
        key={rule.rule_id}
        data-testid={`rule-${rule.rule_id}`}
        data-off={state.key === "paused"}
      >
        <div role="cell" style={{ minWidth: 0 }}>
          <div className="air-rule-name">{rule.title}</div>
          <div className="air-rule-desc">{rule.description}</div>
          {read && <div className="air-understood">{read}</div>}
          {state.key === "not-in-force" && (
            <div className="air-error">
              The compiler could not read this rule, so the solver is not applying it.
            </div>
          )}
        </div>
        <div role="cell">
          <span className="air-state" data-tone={state.tone}>{state.label}</span>
          {state.why && <span className="air-state-why">{state.why}</span>}
        </div>
        <div className="air-acts" role="cell">{actionsFor(rule)}</div>
      </div>
    );
  };

  return (
    <div className="air-page">
      <header className="air-head">
        <div>
          <div className="air-eyebrow">POLICY</div>
          <h1 className="air-h1">AI rules engine</h1>
          <p className="air-sub">
            Legal, safety and custom rules the AI must respect when generating a roster.
          </p>
        </div>
        <div className="air-actions">
          <button
            type="button"
            className="air-btn air-btn-2"
            disabled={stale.length === 0 || busy}
            onClick={compileAll}
          >
            {busy ? "Compiling…" : `Compile all${stale.length ? ` (${stale.length})` : ""}`}
          </button>
          <button
            type="button"
            data-testid="btn-add-rule"
            className="air-btn air-btn-1"
            onClick={() => setDraft({ title: "", description: "", category: "custom" })}
          >
            <Plus size={15} strokeWidth={2} /> New rule
          </button>
        </div>
      </header>

      <div className="air-hero">
        <div className="air-hero-l">
          <div className="air-hero-label">
            RIGHT NOW — {new Date().toLocaleDateString(undefined, {
              weekday: "short", day: "numeric", month: "short", year: "numeric",
            }).toUpperCase()}
          </div>
          <div className="air-hero-row">
            <span className="air-hero-num">{hero.live}</span>
            <span>
              <span className="air-hero-head">
                {hero.live === 1 ? "rule is" : "rules are"} enforced on every roster
              </span>
              <span className="air-hero-sub">
                {counts.legal} legal · {counts.safety} safety · {counts.custom} custom
                {hero.paused > 0 && ` · ${hero.paused} paused`}
              </span>
            </span>
          </div>
        </div>
        <div className="air-hero-r">
          <div className="air-say">
            {hero.pending > 0 || hero.dead > 0 ? (
              <>
                {hero.pending > 0 && (
                  <><strong>{hero.pending}</strong> compiled {hero.pending === 1 ? "rule is" : "rules are"} waiting
                    to be approved. </>
                )}
                {hero.dead > 0 && (
                  <><strong>{hero.dead}</strong> {hero.dead === 1 ? "rule has" : "rules have"} nothing compiled,
                    so {hero.dead === 1 ? "it is" : "they are"} <strong>not being applied</strong>. </>
                )}
                Legal rules are never broken — the AI fails the run instead.
              </>
            ) : (
              <>
                <strong>Legal and safety rules are never broken</strong> — the AI fails the run instead of
                bending one. A custom rule only takes effect once its compiled constraint has been approved.
              </>
            )}
          </div>
          <div className="air-hero-acts">
            <button
              type="button"
              className="air-link"
              onClick={() => setFilter("custom")}
            >
              Show custom rules
            </button>
            <button
              type="button"
              className="air-link air-link-mute"
              onClick={() => toast(
                "Compiling turns your wording into a constraint. Approving it is what makes the solver apply it."
              )}
            >
              How rules apply
            </button>
          </div>
        </div>
      </div>

      <div className="air-section">
        <h2 className="air-h2">Active rules <span>({hero.live})</span></h2>
        <div className="air-pills" role="group" aria-label="Filter by category">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className="air-pill"
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.label}{f.key !== "all" ? ` (${counts[f.key]})` : ""}
            </button>
          ))}
        </div>
      </div>

      <div className="air-table" role="table" aria-label="AI rules">
        <div className="air-row air-colhead" role="row">
          <span role="columnheader">Rule</span>
          <span role="columnheader">State</span>
          <span role="columnheader" aria-label="Actions" />
        </div>

        {GROUPS.map((g, gi) => {
          const list = shown.filter((r) => r.category === g.key);
          if (list.length === 0 && filter !== "all" && filter !== g.key) return null;
          if (list.length === 0 && g.key !== "custom") return null;
          return (
            <div key={g.key} role="rowgroup">
              <div className="air-grouphead" data-later={gi > 0}>
                {g.key} ({list.length}){g.caption ? ` — ${g.caption}` : ""}
              </div>
              {list.length === 0 ? (
                <div className="air-emptyrow">
                  <span>No custom rules yet — describe one in plain English.</span>
                  <button
                    type="button"
                    className="air-link"
                    onClick={() => setDraft({ title: "", description: "", category: "custom" })}
                  >
                    New rule
                  </button>
                </div>
              ) : list.map(row)}
            </div>
          );
        })}

        <div className="air-foot">
          <span>
            {hero.dead > 0
              ? `${hero.dead} rule${hero.dead === 1 ? "" : "s"} not in force · ${hero.pending} awaiting approval`
              : hero.pending > 0
                ? `${hero.pending} compiled rule${hero.pending === 1 ? "" : "s"} awaiting approval`
                : "Every rule here is compiled and approved."}
          </span>
          <button
            type="button"
            className="air-link"
            disabled={stale.length === 0 || busy}
            onClick={compileAll}
          >
            Compile all
          </button>
        </div>
      </div>

      <p className="air-note">
        <strong>Compiling</strong> turns your plain English into a constraint the solver can read.
        It does not switch the rule on: the compiled result has to be <strong>approved</strong> first,
        so a misreading cannot quietly change how people are scheduled. A rule showing{" "}
        <strong>Not in force</strong> has nothing compiled behind it and is being ignored entirely.
        <strong> Legal rules cannot be paused, edited or removed</strong> — they are enforced on every
        run and the AI fails rather than break one. <strong>Pausing</strong> a rule leaves it in place
        but tells the solver to ignore it until you resume it.
      </p>

      {draft && (
        <div className="air-scrim" onClick={() => !busy && setDraft(null)}>
          <div
            className="air-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={draft.rule_id ? "Edit rule" : "New rule"}
            onClick={(e) => e.stopPropagation()}
          >
            <h2>{draft.rule_id ? "Edit rule" : "New rule"}</h2>

            <div className="air-field">
              <label className="air-label" htmlFor="air-title">Title</label>
              <input
                id="air-title"
                data-testid="rule-title"
                className="air-input"
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                placeholder="e.g. No lone opening"
              />
            </div>

            <div className="air-field">
              <label className="air-label" htmlFor="air-desc">Description</label>
              <textarea
                id="air-desc"
                data-testid="rule-desc"
                className="air-textarea"
                rows={5}
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                placeholder="Describe the constraint in plain English."
              />
              <p className="air-hint">
                Saving re-reads the wording. If it can be understood it is applied straight away;
                otherwise the rule shows as Not in force until it compiles.
              </p>
            </div>

            <div className="air-drawer-acts">
              <button
                type="button"
                data-testid="btn-save-rule"
                className="air-btn air-btn-1"
                disabled={busy || !draft.title.trim() || !draft.description.trim()}
                onClick={save}
              >
                {busy ? "Saving…" : draft.rule_id ? "Save changes" : "Add rule"}
              </button>
              <button
                type="button"
                className="air-link air-link-mute"
                disabled={busy}
                onClick={() => setDraft(null)}
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
