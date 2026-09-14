# Roster work queue

Updated: 10 September 2026.

Success means a workable roster that follows the shop manager's rules and needs. Historical comparisons measure role coverage, arrivals, hours and edit burden; matching employee names is not the goal.

## Completed

- [x] Audit the supplied Top Oil workbook and compare generated weeks by role and time.
- [x] Run an offline employee-ranking ML experiment. It did not improve the baseline and remains outside production.
- [x] Repair previous-week overnight coverage context and leave checks in contract top-up/hour-fitting passes. Commit `30a47cf`, merged through PR #3 in `bf667f6`. Validation of the repair commit: 853 passed, 1 expected failure.

## Next, in order

### 1. Establish the baseline after the repairs

- [x] Rerun the same eight comparison weeks using the repaired scheduler and earlier history only.
- [x] Report role/day counts, arrival times, role coverage hours, uncovered opening hours, contract shortfalls and rule breaches. Explain the largest differences with concrete shifts.
- [x] Separate missing historical context from scheduler defects. Current availability, student restrictions and employment status are not evidence of what applied in July.

Done. See [the repaired scheduler baseline](SCHEDULER_BASELINE_2026_09_09.md). The eight simulations were fully covered with no contract shortfalls or compliance breaches; the first fitted model remains worse and stays offline. Keep these labelled current-settings simulations until historical context is available.

### 2. Finish and review training evidence capture

- [x] Review the existing local generation/approval snapshots, export service and tests; complete missing context needed to explain decisions.
- [x] Capture usable approval and edit evidence, including unchanged approvals, with shop isolation and data minimisation.
- [x] Keep ambiguous imports, duplicate weeks and emergency overrides out of ordinary preference labels. A removed shift alone does not prove someone was unsuitable.
- [x] Validate and prepare the local changes for a separate review/commit.

Done. Future generated approvals now preserve effective hard constraints, learned scheduler inputs, proposal provenance, final constraints and manager changes. Only eligible clean swaps become pairwise labels; ambiguous and legacy edits remain quarantined evidence. The read-only Top Oil export retained 185 existing corrections without backfilling labels, and the full backend suite passed (873 passed, 1 expected failure). Full historical replay is still not claimed. This work remains local and uncommitted.

### 3. Make closing rules work end to end

- [x] Support “either a manager or supervisor must be rostered at closing” as a shop-specific rule with an explicit closing scope.
- [x] Verify parsing, generation and validation agree, including overnight closing and insufficient eligible staff.
- [x] Explain unsupported rules or unmet requirements clearly in the app.

Done. Anthropic now compiles free text into schema-constrained JSON, while the backend accepts only rule shapes the deterministic scheduler can enforce. Closing is derived from each shop's configured hours, including a split shift after midnight. Generation places and protects a qualified closer; edits, audits, approval and training evidence recheck the same rule. Unsupported output and impossible or 24-hour closing requirements are reported instead of silently ignored. Validation: 881 passed, 1 expected failure; frontend production build passed with one pre-existing hook warning in `RosterView.js`.

### 4. Design and evaluate the next ML model

- [ ] Use the updated baseline and evidence audit to choose the next model inputs and learning target.
- [ ] Evaluate on later, untouched weeks; compare with the existing scheduler on manager-relevant outcomes.
- [ ] Preserve eligibility checks, settled ownership and contractual priorities when integrating learned scores.

Done when the model demonstrates a useful improvement without increasing constraint breaches. The first model is not a production candidate: its pre-repair role/time distance was worse than the baseline.

### 5. Replace the fixed repeat-count suggestion trigger

- [ ] Learn contextual patterns from manager changes and accepted/rejected suggestions rather than triggering solely after three repetitions.
- [ ] Distinguish temporary cover or leave from a lasting preference; show the evidence behind each suggestion.
- [ ] Evaluate suggestions on later decisions and retain manager control over making a pattern fixed.

Done when suggestions reflect supported preferences and their usefulness can be measured. Existing correction data is sparse, so evidence collection precedes this change.

## Supporting reports

- [Scheduler audit](SCHEDULER_AUDIT_2026_09_09.md): historical findings; the two confirmed defects are now repaired.
- [Repaired scheduler baseline](SCHEDULER_BASELINE_2026_09_09.md): eight time-ordered current-settings simulations after the repairs.
- [ML data readiness](ML_DATA_READINESS.md): available evidence and limitations.
- [First role experiment](ML_ROLE_EXPERIMENT.md): offline results before the production repairs.
- [Earlier ML plan](ML_PLAN.md): historical proposal; this queue supersedes its execution order.

Queue updates do not imply deployment, a new commit or a push. The user handles GitHub pushes.
