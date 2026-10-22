# Cross-group overnight overlap: TDD evidence

22 October 2026. Source plan: the user's approved request to fix the two
reproduced overnight gaps while keeping genuine overlaps non-overridable.

## User journeys and implementation

- A person working in Deli overnight must not be generated into overlapping
  Shop Floor hours, even when the starting weekdays differ.
- Approval must consider previous Sunday and next Monday commitments, and a
  password must never authorize a physical overlap.
- Manual edits and sick replacement must identify the conflicting group and
  times rather than provide a bypass.
- The UI and print sheet must show overnight continuations on the correct day.
- Adjacent weeks must not spend this week's hours, days, contract or coverage.

The existing external-commitment flow now carries a day offset and calendar
date, reads adjacent weeks, and uses a shared minute-interval comparison.
Safety reads are streamed rather than silently page-limited. Weekly accounting
still uses only shifts starting in the current week. No migration or stored
roster rewrite is required. All production reads remain tenant scoped.

## RED evidence

`backend/tests/test_cross_group_overnight.py` initially produced **9 failures
and 4 passing controls** against the old application code. RED checkpoint:
`7785a59` on the active branch. Tests ran through the real FastAPI routes with
in-memory MongoDB and explicitly disabled external integrations.

The later many-draft test failed after the test fixture modeled Motor's real
page length. mongomock's `to_list` otherwise ignored it, concealing the truncation.

## Guarantees checked

| Behaviour | Regression | Type |
|---|---|---|
| Generation avoids cross-midnight work in another group | `test_generation_never_overlaps_another_group_across_midnight` | API + solver |
| Both neighbouring weeks are considered; normal and forced approval refuse overlap | `test_overlap_cannot_be_approved_even_with_password` | API |
| Manual refusal names the conflicting group and times | `test_manual_overlap_names_the_other_group_and_times` | API |
| Adjacent weeks do not consume this week's hours/days | `test_adjacent_weeks_do_not_spend_this_weeks_hours_or_days` | API |
| Previous-week commitments never include another shop | `test_previous_sunday_shifts_are_returned_without_other_shop_data` | API |
| Hundreds of newer drafts cannot hide a commitment | `test_many_draft_versions_cannot_hide_a_boundary_commitment` | API |
| Touching or fully rested shifts are not physical overlaps | `test_non_overlapping_boundary_shifts_are_not_hard_blocked` | API |
| A rested later shift can still be generated with a small cap | `test_previous_week_does_not_consume_hours_or_prevent_a_rested_later_shift` | API + solver |
| No expiry tied to today's year | `test_overlap_guard_is_not_tied_to_this_year` | API, runtime year + 50 |
| Sick-cover suggestions and assignment cannot bypass the check | `test_sick_cover_cannot_bypass_a_previous_week_overnight_commitment` | API |
| Grid and print projection put last Sunday's continuation on Monday | `RosterCommitments.test.js`, `RosterLoading.test.js` | React rendering |

All date-sensitive backend fixtures derive future weeks from the runtime date;
the additional long-horizon case derives its year at runtime too. Static dates
in pure display tests do not depend on whether that date is past or future.

## Commands and results

Backend runtime used: existing Desktop checkout's `backend/venv/Scripts/python.exe`,
executing the active `C:/Users/anees/Roster` source.

```powershell
python -m pytest -q -p no:cacheprovider backend/tests/test_cross_group_overnight.py backend/tests/test_departments.py backend/tests/test_api.py::test_roster_list_filters_week_and_batches_cross_group_reads backend/tests/test_sick_cover.py backend/tests/test_roster_validation.py
```

Focused suite: passed, including all **19 new backend cases**. Full backend
verification is recorded below after completion.

Frontend used bundled Node with the already-installed Desktop dependency tree,
CRA/craco and Jest's `--modulePaths` pointing at that tree. No packages installed.

```text
craco test --watchAll=false --runInBand --modulePaths <installed-node_modules>
```

**48 tests passed across 9 suites**, including 6 new display/grid cases.

## Negative controls and coverage

- Replacing the solver's overlap refusal with its former `continue`, only in
  memory, made the same-week cross-midnight generation regression fail.
- Filtering adjacent-week commitments out in memory made the force-approval
  regression fail.
- A test-only Babel transformer replaced the display helper with the old
  weekday-only mapping; all five `RosterCommitments` tests failed.
- No application file was modified by these negative controls. The first
  filesystem-hook attempt at UI mutation did not execute; its passing result
  was discarded, not counted as evidence.

Jest coverage of the new display helper: **17/18 statements (94.4%)**. Print
component line coverage: **92.5%**. Combined existing API/print modules were
65.38% line-covered; this is not a claim of 80% whole-project coverage. Backend
coverage tooling is not installed, so no backend percentage is claimed.

## Boundaries

No live data, credentials, emails, AI requests, payments or deployments were
used. Browser/live-server verification and concurrent requests were not tested.
The tests are not proof of race-free simultaneous approval, nor a full security
audit. Existing approved records are not automatically reopened or repaired.
Both backend and frontend changes must be deployed to update the live app.

## Final verification

Final full backend run: **1,258 passed, 1 existing expected failure**, no errors,
in 144.62 seconds. Command:

```text
python -m pytest -p no:cacheprovider backend/tests --tb=short --basetemp <new-task-specific-directory>
```

The first full run encountered four Windows temporary-directory permission
errors, not assertion failures. Fresh task-specific directories resolved them;
no tests were disabled or skipped to obtain the clean result.

Final frontend run: **48 passed**, including the actual-grid rendering test.
Production compilation: **passed with CI=true**. The first attempt could not
resolve `react-dom/client` because dependencies live in the Desktop checkout.
A temporary artifact-only craco wrapper added that installed directory to
Webpack's module/loader resolution; the active source then compiled successfully.
No dependency installation or application configuration change was needed.

The GREEN implementation checkpoint contains this evidence and the new tests;
the RED checkpoint remains separately reachable in local Git history. Neither
checkpoint has been pushed or deployed by this task.
