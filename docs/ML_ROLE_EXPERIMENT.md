# First fitted model and role-based comparison — 9 September 2026

**Post-repair update:** the scheduler was rerun after `30a47cf`. The model verdict is unchanged: it remains worse and stays offline. The repaired baseline removed the sole contract shortfall without materially changing the comparison. See [the repaired scheduler baseline](SCHEDULER_BASELINE_2026_09_09.md).

## Result

The first employee-choice model did **not** improve the existing scheduler on this experiment. Keep it offline. Across eight historical simulations, daily role-count error stayed unchanged, role/time presence error increased by **5.47%**, and solver uncovered hours increased from zero to five. This is evidence about one model configuration under imperfect historical context, not evidence that ML cannot help.

**Audit correction:** the earlier figures of 6 versus 11 uncovered hours came from an approval-checker bug at the Monday boundary. The figures below use final solver coverage, including the previous Sunday's carry-in. See `docs/SCHEDULER_AUDIT_2026_09_09.md` for the reproduced defects.

| Measure, summed across eight weeks | Existing solver | Fitted model |
|---|---:|---:|
| Reference working shifts | 557 | 557 |
| Generated working shifts | 552 | 550 |
| Absolute daily role-count difference | 207 | 207 |
| Absolute role/start-hour arrival-count difference | 561 | 575 |
| Missing + extra role-at-time person-hours | 2,623.5 | 2,767.0 |
| Matching role/day/start/end shifts, ignoring employee identity | 228 | 220 |
| Solver uncovered hours, including previous-week carry-in | 0 | 5 |
| Under-contract cases | 1 | 1 |

Count distances sum absolute differences across groups: a shift moved from one role/day to another contributes one missing and one extra count. Person-hour differences compare exact minute intervals separately for each role, retaining Sunday overnight carry-out. They are differences from a reference schedule, not proof that every mismatch is operationally wrong. Solver uncovered hours use its existing whole-hour convention rather than the exact-minute comparison metric.

The five experimental-model gaps occur in the 24 August simulation. The existing solver reports no uncovered hours across all eight weeks. Compliance audit returned one contract-under case for each method on 27 July and no other breaches in these runs. This is not independent certification of every custom AI rule or historical legal compliance.

## Workbook verification

The user supplied `C:/Users/anees/Downloads/new roster 26.xlsx` after the first CSV showed different staffing and roles. The workbook supersedes that CSV for the final comparison.

Its 27 July reference has **68 working shifts** and exactly matches the stored Top Oil week on role/day/start/end multiplicities and role presence. All eight roles match existing employee roles after case normalisation; no guessed role mapping was used.

| Role, week of 27 July | Workbook shifts | Existing solver shifts |
|---|---:|---:|
| Assistant Manager | 3 | 4 |
| Customer Service Manager | 4 | 5 |
| Ambient Manager | 5 | 5 |
| Goods Inwards | 5 | 5 |
| Duty Manager | 10 | 10 |
| Supervisor | 8 | 6 |
| Shop Floor | 26 | 26 |
| Night Shift | 7 | 9 |
| Total | 68 | 70 |

The weekly size is close, but role mix and the times those roles are present differ. This supports evaluating counts and time coverage together instead of optimising names or weekly size alone. The model produced 70 shifts too, with 31 exact role/time matches versus the existing solver's 34.

The workbook has 31 parsed sheets, including an undated unusable sheet and two sheets dated 1 June. The parser reported eight unparsed cells on 6 July and two on 20 July. The selected 27 July reference has zero unparsed cells and one parser warning. Other workbook weeks were not silently substituted for the already imported database history; the experiment does not assert that all original workbook cells are clean. No workbook or database records were changed.

## Experiment design

- Target weeks: 13, 20 and 27 July; 3, 10, 17 and 24 August; 7 September 2026.
- Historical approved weeks with duplicate dates, duplicate working employee-days, invalid shift fields or forced approval were quarantined as whole weeks. Thirty clean database weeks remain.
- Each target uses **only earlier weeks** for demand, ownership, familiarity, usual finishes, baseline weights and model fitting. Target folds have 22–29 earlier weeks. No random split of shifts and no training on a target or later roster.
- The model is regularised multinomial logistic regression, implemented using NumPy. It fits observed employee identity from weekday, start-hour, exact start and weekday/start-hour features. Parameters are optimised; this is a fitted model, not another repetition threshold. Multiple people at the same start contribute multiple observations; absence is never labelled unsuitability.
- One fixed configuration: 350 gradient steps, learning rate 0.5, regularisation 0.01. No parameters were selected on the eight scored weeks. Saved training loss verifies optimisation only, not predictive quality.
- The experimental builder replaces non-owner historical ranking. Rank-zero owners remain protected, existing contract priority remains in the caller, and eligibility and downstream passes are retained. Comparisons with employees unseen during training fall back to existing ranking. Both builders use a deterministic unseeded solve.
- Model training and inference live in `backend/ml/`; no application route imports the model, and no production scheduler behaviour was changed by this experiment.

## Constraints and limits

The program **does enforce** holidays, student caps and configured summer breaks. Current Top Oil records include 10 student records, three summer-break configurations, three availability configurations, 91 holiday records, four fixed-shift records and eight enabled rules. These existing records were retained in both runs.

These are **current-context simulations**, not faithful historical replays. Current active status (25 of 31 employee records), roles, availability, contracts, fixed shifts and rules may differ from what applied in July. Even dated leave can have been entered later. The newly added context snapshots cannot reconstruct older decisions. Models use only earlier roster observations, but the operational input context is not a historical snapshot.

Role/time matching deliberately tolerates different employee names. It still cannot tell whether an unmatched but valid arrangement is one the manager would accept. Historical role labels fall back to current employee roles when absent on the shift. Results are from one shop and do not establish cross-shop generalisation. This experiment does not learn suggestion timing from the three weeks of correction records.

## Outputs and next decision

Implementation:

- `backend/ml/role_experiment.py`: training, chronological filtering and role metrics.
- `backend/ml/run_role_backtest.py`: shop-scoped read-only runner, workbook/CSV references and reports.
- `backend/tests/test_role_experiment.py`: role identity invariance, duplicate counts, minute/overnight handling, chronological isolation, fitted pattern behaviour, owner preservation and workbook ambiguity checks.

The corrected local output directory is `C:/Users/anees/.codex/visualizations/2026/09/08/01a082fe-db1c-7a60-84dc-09c69ef7b990/role-backtest-audited-2026-09-09/`. It contains the full report, per-week baseline and ML role-only CSVs, results JSON and fitted model artefacts. Artefacts contain internal employee IDs and are local research output.

The full backend suite passed with one expected failure before the workbook adapter was added; the affected experiment tests were rerun after that addition. No live roster was generated, approved, edited or published.

Next experiment proposal: investigate the largest role/time discrepancies and determine which come from missing historical constraints versus the scheduling objective. Role/day/time demand and manager acceptance should guide the next design; a marginal increase in historical matching alone is not a deployment criterion. Do not tune repeatedly on these same eight weeks and call the resulting score unseen performance.
