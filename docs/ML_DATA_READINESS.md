# ML data readiness — 10 September 2026

## Implementation update — 10 September 2026

Training evidence capture is complete for future generated approvals. The production scheduler still makes every roster decision; no ML model has been deployed.

Before solving, `training_context` now freezes the scheduling-specific shop and employee inputs, availability, contracts, leave, fixed shifts, enabled compiled rules, locked shifts, seed, source-history IDs and hashes, learned preference weights, the complete learned demand profile (including arrivals), normalized effective hard constraints and a service-source fingerprint. Contact details, pay rates and roster-recipient lists are omitted. Stable context and input hashes make changed decision conditions explicit.

After solving, `training_proposal` records each placed shift, its role, inferred assignment source, proposal hash and the resulting uncovered hours, compliance breaches and contract shortfalls. At approval, `training_approval` records the final shifts, corrections, approval outcome, final constraint result and whether the decision context still matches generation. Later sick-cover edits do not overwrite this approval snapshot. Deliberate reapproval replaces it; this remains a decision snapshot rather than a complete event stream.

Ordinary training eligibility is explicit. Forced or breaching approvals, uncovered hours, changed/missing context, missing generated baselines and exception rows are retained with exclusion reasons. A clean same-slot employee swap may become a pairwise preference label only when the whole approval is eligible. Moves, additions and removals remain useful manager-action evidence but are not guessed to mean that another employee was unsuitable. An unchanged clean approval is recorded as a positive outcome, including when the generated shift list was empty.

`backend/ml/export_training_history.py --shop-id ID --output FILE` is read-only and shop-scoped, uses exclusive file creation, and never writes to MongoDB. A validation export against Top Oil on 10 September produced **2,175 historical observations, 185 manager-correction records, 29 quarantine records and 31 legacy approval outcomes**. The older edits were retained but not labelled because those approvals predate the new decision context. Both records of a duplicated approved week are quarantined. The final local JSONL is outside the repository at `C:/Users/anees/.codex/visualizations/2026/09/09/01a0884f-630f-7b21-ab28-59e2b7d9b88c/training-evidence-v2-final-2026-09-10.jsonl`; it contains employee identifiers and is not public. No live records were changed.

Validation: **873 passed and 1 expected failure**. Tests cover immutable/minimized context, stable hashes, effective hard constraints, demand-profile round trips, proposal and approval capture, clean unchanged outcomes, safe pairwise swaps, ambiguous and legacy corrections, exception/forced/gap exclusions, and empty generated snapshots. This implementation is local and has not been deployed.

The context remains deliberately marked `replay_complete: false`. History documents are identified by hashes rather than copied in full, the source fingerprint does not preserve a complete executable build, and every rejected candidate at each intermediate solver pass is not recorded. The captured inputs, outputs and constraint results are sufficient for future evidence-backed experiments without claiming exact historical replay.

## Product direction

Success means a workable roster that follows the manager's intentions, not an exact reproduction of a historical roster. Each shop's written rules must constrain scheduling. A trained model should influence assignments and learn preferences from edits. Explicit constraints remain enforced; suggestions should be based on contextual evidence rather than a fixed repetition count.

This report audits code and proposes the first experiment. It does not establish that the available live data is sufficient to train a useful model.

## Verified foundations

| Evidence | What exists | Training value / limitation |
|---|---|---|
| `backend/app/services/learning.py` | Approved-history frequency counts, deduplication by week, exception filtering | Useful baseline; no fitted model |
| `backend/app/routes/rosters.py`, generation | Generated shifts, seed, creation time, department and solver results are saved | Captures the proposal; not a complete snapshot of the inputs or solver version |
| Same file, approval | Corrections, edit count, approval time, gap count and override information are saved | Useful feedback; approval does not establish that every assignment is preferred or compliant |
| `backend/app/services/corrections.py` | Differences for moved, swapped, removed and added shifts | Captures the final difference, not the reasons for ordinary edits or every intermediate decision |
| Same file, suggestions | `MIN_REPEATS = 3` and fixed suggestion mapping | Three occurrences in the reporting window, not necessarily three consecutive weeks; no trained preference inference |
| `backend/app/tenancy.py` | Shop-scoped collections | Training reads must preserve shop isolation |

The generation record does not preserve a complete copy of employees' availability/contracts, holidays, fixed shifts, shop settings and active compiled rules as they were then. Current employee records cannot safely reconstruct those facts for a historical week. A saved seed alone cannot reproduce a solve when its inputs and code change.

Approval saves corrections before later sick-cover changes, which is useful. A training extractor must distinguish approval-time feedback from the subsequently amended working schedule. Historical weeks without a generated baseline must not be interpreted as zero-edit successes. The current measurable flag uses truthiness of `generated_shifts`, so an empty proposal is also treated as unmeasurable.

## Written-rule check

Executed the existing pure parser with no employees:

- “I want either manager or supervisor to be rostered during the shop closing” returned `None`.
- “A manager or supervisor must be present during shop closing” returned `supervisor_required`, described as coverage “at all times,” with no closing-time scope.

This verifies a local parsing gap, not the behaviour of the optional LLM compilation path. Closing-only scope needs a supported representation and checks through parsing, assignment, post-edit validation and approval. Clarify whether closing means the final opening interval or a separate closing task before implementing it. An unsupported rule must be visibly inactive; a broader rule must not be silently substituted.

## Data access — resolved on 8 September 2026

The initial connection error was a DNS timeout inside the restricted environment. The same configured connection succeeded outside the sandbox; credentials and database configuration were not changed. Read-only inventory completed, discovering shop registry metadata and using `ShopScope` for tenant records. No database writes or personal contact exports were performed.

| Shop | Roster records | Approved records | Distinct approved weeks | Imported weeks after deduplication | Weeks with proposal/corrections | Recorded corrections |
|---|---:|---:|---:|---:|---:|---:|
| Top oil South Link | 80 | 33 | 32 | 29 | 3 | 185 |
| ILS | 26 | 7 | 6 | 5 | 1 | 1 |

Two other registered shops have no rosters. Shops were not pooled into a training dataset. No approved records were marked `exclude_from_ai`.

Top Oil has 31 employee records, 25 currently active under the `is_active` / `past_staff` flags. Its approved weeks span 19 January–7 September 2026, with 2,271 shift rows. The existing exception filter excludes 25, leaving 2,246 potential historical signal rows before further quality checks. These are not 2,246 independently verified training examples. ILS has two employees and 42 shift rows across 3 August–7 September 2026.

### Correction evidence

| Top Oil week | Added | Moved | Removed | Swap | Total |
|---|---:|---:|---:|---:|---:|
| 24 August | 16 | 27 | 16 | 4 | 63 |
| 31 August | 17 | 27 | 15 | 5 | 64 |
| 7 September | 14 | 21 | 12 | 11 | 58 |

All three have stored `approved_with_gaps = 0` and no force-approval flag. These are recorded outcomes, not an independent revalidation of historical coverage or rules. ILS has one swap on 7 September. There are no measurable unchanged approvals in either shop. The remaining historical weeks lack generated proposals; they must not be labelled unchanged approvals.

The 185 changes are clustered in three weeks, not 185 independent weekly preference observations. They do not yet establish reliable contextual suggestion learning. Top Oil has one stored suggestion-response record; ILS has none, so suggestion-acceptance evaluation is also very limited.

### Data quality

- Duplicate approved weeks: Top Oil 1 June 2026 and ILS 24 August 2026 each have two records. Counts above use the existing newest-created-per-week selection; retain source provenance and review conflicting versions before training. No records were deleted.
- Top Oil's selected 31 August week contains one duplicate employee-day: Friday has `07:00–15:00` and `18:00–00:00` for the same employee. These are separate non-overlapping shifts, but the correction code identifies a shift solely by employee/day and overwrites one in its internal map. Quarantine that employee-day's feedback (including comparisons involving it); do not assume the stored corrections capture both rows. Whether the schedule itself should be corrected needs review, not automatic deletion.
- No missing employee references or malformed weekday/HH:MM values were found in selected approved weeks. This was a structural check, not a full historical constraints audit.
- Actual roster field inventories confirm no complete generation-input or approval-context snapshot fields. Top Oil has 91 holiday records, but their presence alone does not prove which information was available when an earlier roster was generated.
- Top Oil has 68 activity records and two import records; ILS has 64 and ten. Their ability to recover historical context has not been verified. Do not assume these totals imply complete event history.

## Earlier access attempt and remaining unknowns

No XLSX or CSV files were found in the initial repository file search. Documentation references reference-shop history, but that is not a verified current dataset count.

The project's virtual environment could not start because access to its underlying Python executable failed. A bundled Python runtime successfully executed the parser probes. A read-only MongoDB check using the existing configuration then failed with `ConfigurationError`; no records were retrieved or changed. Credentials were not printed. The exact configuration cause has not been diagnosed.

The initial inventory questions were:

1. Count distinct approved weeks, dates, imported versus generated weeks, duplicate weeks and excluded records.
2. Count measurable approved proposals and corrections by type; separate unchanged approvals from missing baselines.
3. Check missing employee references, malformed/duplicate shifts, exceptions and forced approvals.
4. Establish whether historical availability, contracts and rule changes exist outside the current generation record.
5. Determine how much later, unseen history can be reserved for evaluation. One shop cannot establish generalisation to other shops.

Items 1–3 now have the results above. Historical effective-dated availability/contracts and exact rule changes remain unverified. A chronological split can be constructed from the 32 Top Oil weeks after quality review, but its size should be selected after examining date gaps and usable features. No claim of predictive performance has been made.

## First implementation proposal

Capture immutable decision context on generation, plus the final approval snapshot and relevant context changes. Include scheduling inputs, explicit candidate eligibility where practical, seed, solver/model version and source-history identifiers. Keep this evidence shop-scoped and avoid unrelated personal/contact data. Record facts observed at decision time; do not backfill guesses from today's settings.

This is evidence storage, not a cached derived preference flag. Model artefacts will likewise need versioning and training-source provenance, including a policy for removing unapproved/excluded history from future training.

Do not make reasons mandatory for every edit. Existing leave/override facts can explain some changes; otherwise mark the reason unknown and offer lightweight optional feedback when needed. An unknown reason must not automatically become a permanent preference.

## First model experiment

Proposed task: rank eligible employees for a shift, initially in offline comparison with the existing frequency baseline. Model family and dataset size requirements remain undecided until the data inventory is complete.

- Historical assignments are examples of acceptable choices, not proof that unchosen employees were wrong.
- A manager's replacement can provide a contextual comparison only when both alternatives were eligible and no known exception explains the change. Other edits remain ambiguous evidence.
- Use only information available before the target decision. Split by complete weeks in time order; rebuild historical features using earlier weeks only. Never randomly split shifts from the same week across training and evaluation.
- Historical data without contemporaneous constraints can support descriptive experiments, but cannot justify confident eligibility labels or a faithful retrospective roster replay.
- Evaluate the resulting whole roster, not just candidate ranking. A local improvement can worsen weekly hours or leave a later shift uncovered.
- Preserve a working baseline for new shops and insufficient-data cases. Do not replace production assignment logic on offline ranking accuracy alone.

## Success scorecard

| Measure | Interpretation |
|---|---|
| Uncovered opening time and unmet staffing requirements | Whether the shop can operate; separate opening coverage from learned average demand |
| Explicit shop-rule and hard-constraint violations | Feasibility; report infeasible cases rather than hiding gaps |
| Contract shortfalls and deviation from feasible usual hours | Whether weekly hours are distributed appropriately |
| Manager judgement of roster acceptability | Whether valid alternatives follow the manager's intentions |
| Edit types, edit burden and time to approval | Supporting usability evidence; not a target of exact roster imitation |
| Suggestion acceptance/dismissal and later applicability | Whether learned suggestions are useful; temporary changes must not become permanent rules automatically |

Coverage evaluation should include actual intervals: the existing whole-hour coverage convention can credit partial-hour presence. Record this distinction when measuring whether the shop is continuously staffed.

## Recommended sequence

Access and the initial scoped inventory are complete. Next, agree the context-capture design and prepare a quality-filtered historical dataset with explicit provenance. An initial historical-pattern experiment is possible; reliable contextual correction learning is not yet demonstrated by three weeks. Verify closing-rule semantics end to end before evaluating compliance with that rule. Replace fixed suggestion triggers only once contextual learning can be evaluated. The older `docs/ML_PLAN.md` is historical: its assumptions that corrections are discarded and removals are always strong negative labels must not guide the new work.

No application behaviour was changed during this audit. Verification consisted of source inspection, two executed parser probes, a successful connection check and two read-only inventory queries; the application test suite was not run for this documentation-only change.
