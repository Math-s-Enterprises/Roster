# Scheduler baseline after the week-context repairs — 9 September 2026

## Verdict

The repaired scheduler produced eight fully covered simulations with no contract shortfalls and no compliance breaches. The repair removed the one previous under-contract case without changing role/day counts, arrival counts, exact role/time matches or total coverage.

Do not change production ranking from this result. The first fitted ranking model remains worse than the repaired baseline on arrival timing, role-at-time coverage, exact role/time matches and uncovered hours. It remains offline.

These are **current-settings simulations**, not faithful historical replays. Each target saw only earlier clean approved weeks as roster history, but current employee status, roles, availability, student limits, fixed shifts, holidays and rules were applied.

## Reproduction

Run from `backend/`:

```powershell
.\venv\Scripts\python.exe ml\run_role_backtest.py `
  --shop-id shop_5b185731ec13 `
  --output NEW_EMPTY_DIRECTORY `
  --weeks 8 `
  --reference-xlsx "C:\Users\anees\Downloads\new roster 26.xlsx" `
  --reference-week 2026-07-27
```

Input hash: `84dedc2602b0e87ddd771761a0947eed39524fded79f93a3cc63c0b3ba02a1f4`.

The local output is `C:/Users/anees/.codex/visualizations/2026/09/09/01a0884f-630f-7b21-ab28-59e2b7d9b88c/scheduler-baseline-post-repair-v2/`. `results.json` contains every role/day count, arrival-hour count, exact shift-shape count, per-role coverage total, uncovered-hour detail, contract case and breach message. The CSV files contain the generated role rosters.

The input contained 30 clean approved weeks, 31 employee records (25 currently active), 10 student records, three summer-break configurations, three availability configurations, 91 holiday records, four fixed-shift records and eight enabled rules. Two duplicate 1 June records and the duplicate-employee-day week of 31 August were quarantined as whole weeks.

## Eight-week baseline

Distances are sums of absolute count differences. A move can therefore add one missing and one extra count. Role-time distance is exact-minute missing plus extra person-hours relative to the reference; it is not uncovered shop time.

| Week | Earlier weeks | Reference shifts | Generated shifts | Role/day distance | Arrival-hour distance | Role/arrival distance | Role-time distance | Exact role/time matches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 13 Jul | 22 | 71 | 69 | 20 | 24 | 64 | 274.0h | 35 |
| 20 Jul | 23 | 70 | 69 | 19 | 23 | 65 | 258.0h | 33 |
| 27 Jul | 24 | 68 | 70 | 22 | 20 | 62 | 277.0h | 34 |
| 3 Aug | 25 | 70 | 69 | 39 | 31 | 85 | 452.0h | 21 |
| 10 Aug | 26 | 68 | 69 | 25 | 33 | 75 | 347.0h | 24 |
| 17 Aug | 27 | 70 | 69 | 33 | 35 | 73 | 363.5h | 25 |
| 24 Aug | 28 | 69 | 68 | 25 | 33 | 65 | 337.0h | 26 |
| 7 Sep | 29 | 71 | 69 | 24 | 36 | 72 | 315.5h | 30 |
| **Total** | — | **557** | **552** | **207** | **235** | **561** | **2,624.0h** | **228** |

The role-independent arrival distance is 235. The larger role/arrival distance of 561 shows that many timing differences are role substitutions at an hour, not a different number of people arriving.

## Role coverage

“Missing” and “extra” below compare exact role presence against the reference minute by minute. They do not mean the shop was empty: all open hours were covered.

| Role | Reference shifts | Generated shifts | Reference span | Generated span | Missing reference-role hours | Extra reference-role hours |
|---|---:|---:|---:|---:|---:|---:|
| Shop Floor | 232 | 206 | 1,743.0h | 1,530.0h | 553.5h | 340.5h |
| Duty Manager | 74 | 76 | 615.5h | 632.0h | 316.0h | 332.5h |
| Supervisor | 53 | 45 | 373.0h | 341.0h | 193.0h | 161.0h |
| Ambient Manager | 39 | 40 | 327.5h | 328.5h | 169.5h | 170.5h |
| Night Shift | 72 | 76 | 520.0h | 559.5h | 47.5h | 87.0h |
| Assistant Manager | 23 | 32 | 230.0h | 320.0h | 0.0h | 90.0h |
| Goods Inwards | 36 | 38 | 288.0h | 305.0h | 33.0h | 50.0h |
| Customer Service Manager | 28 | 39 | 275.0h | 355.0h | 0.0h | 80.0h |

The largest net mix difference is Shop Floor: 26 fewer generated shifts and 213 fewer total span-hours across the eight weeks. Senior-role surpluses explain much of that difference, especially current fixed assignments that did not exist in some historical reference weeks.

## Coverage, contracts and breaches

| Week | Solver uncovered opening hours | Recomputed approval gaps | Contract shortfalls | Compliance breaches |
|---|---:|---:|---:|---:|
| 13 Jul | 0 | 0 | 0 | 0 |
| 20 Jul | 0 | 0 | 0 | 0 |
| 27 Jul | 0 | 0 | 0 | 0 |
| 3 Aug | 0 | 0 | 0 | 0 |
| 10 Aug | 0 | 0 | 0 | 0 |
| 17 Aug | 0 | 0 | 0 | 0 |
| 24 Aug | 0 | 0 | 0 | 0 |
| 7 Sep | 0 | 0 | 0 | 0 |

The solver and the repaired approval coverage calculation now agree when both receive the actual previous approved week. The comparison script had initially called the repaired function without that context and reproduced the old six-hour 24 August false alarm; the diagnostics now pass `week_start` and earlier rosters explicitly.

The compliance audit covers weekly caps, contract bands, maximum days, maximum shift length, minor curfew, booked leave, double booking and the shop's rest setting. It is not an end-to-end validator for every custom natural-language rule. The manager-or-supervisor closing requirement is still unfinished and belongs to queue item 3.

## Largest differences and their causes

### 3 August: mostly missing historical context

This is the largest role/time mismatch: role/day distance 39 and role-time distance 452.0 hours.

- The reference contains no Assistant Manager or Customer Service Manager shifts. Current settings place Megan on fixed 06:00–16:00 shifts Monday–Thursday and John on fixed 06:00–16:00 shifts Tuesday–Saturday: nine senior-role shifts before ordinary slot filling begins.
- The reference has 36 Shop Floor shifts; the simulation has 25. Its Assistant Manager and Customer Service Manager fixed shifts account for nine of the senior-role additions, so this is not evidence that the ranking selected the wrong employee for nine ordinary slots.
- Tintu appears on four reference weekdays but is currently inactive. Aneesh appears on Tuesday, Wednesday, Saturday and Sunday in the reference but is now constrained to weekends with a 20-hour student cap. The simulation cannot reproduce that historical supervisor availability.
- Concrete arrival differences include Monday two reference starts at 12:00 versus none generated, and two generated starts at 16:00 versus none in the reference. Those are timing/profile differences after the current fixed shifts and eligibility context have already changed the available pool.

This week is therefore unsuitable for tuning employee ranking. Historical employee-state snapshots would be needed to decide how much residual difference belongs to the scheduler.

### 27 July: role labels differ more than operational coverage

The reference has three Assistant Manager, four Customer Service Manager, eight Supervisor and seven Night Shift assignments. The simulation has four, five, six and nine respectively.

- Current fixed shifts add one Assistant Manager day and one Customer Service Manager day relative to the reference.
- Tintu worked five reference weekdays but is now inactive. Aneesh worked Wednesday, Saturday and Sunday in the reference but current availability permits Saturday/Sunday only and the current student cap is 20 hours.
- The two additional assignments held by Night Shift employees are not two additional overnight starts: Kelvin works Wednesday 18:00–00:00 and Andi works Sunday 15:00–00:00. The simulation still contains exactly seven 23:30–07:00 overnight shifts.

These explain concrete role-count differences without establishing a coverage defect.

### Recurring arrival differences

Several weeks move one Friday arrival from 07:00 to 06:00: the reference commonly has two starts in each hour, while the simulation has three at 06:00 and one at 07:00. The role detail shows the current Goods Inwards/fixed-shift context contributing to that change. Later weeks also move changeover starts—for example, 7 September has two generated Shop Floor starts at Saturday 17:00 where the reference has none, and two reference starts at Tuesday 14:00 where the simulation has none.

These are real timing differences worth retaining in the baseline. They are not uncovered hours, and this run does not prove whether the manager would edit them under today's context.

## What the repair changed

Against the pre-repair audited run:

- under-contract cases fell from one to zero;
- 27 July Duty Manager Tuesday changed from 10:00–18:00 to 10:00–19:00;
- 3 August Duty Manager Tuesday changed from 10:00–19:00 to 10:00–18:30;
- 24 August Duty Manager Monday changed from 13:00–21:00 to 13:00–22:00;
- role/day distance remained 207, arrival and role/arrival distances remained unchanged, exact role/time matches remained 228, and uncovered opening hours remained zero;
- role-time distance moved by 0.5 hours, from 2,623.5 to 2,624.0, because the repaired contract fitting changed those finishes.

The intended result is visible: unrelated leave records no longer suppress contract fitting. The repair did not otherwise reshape the simulated weeks.

## Ranking decision

| Eight-week measure | Repaired baseline | First fitted model |
|---|---:|---:|
| Role/day distance | 207 | 207 |
| Arrival-hour distance, all roles | **235** | 241 |
| Role/arrival distance | **561** | 575 |
| Role-time distance | **2,624.0h** | 2,767.5h |
| Exact role/time matches | **228** | 220 |
| Uncovered opening hours | **0** | 5 |
| Contract shortfalls | 0 | 0 |

The fitted model does not improve the repaired scheduler. No production ranking change is justified. The next work should be evidence capture, followed by the explicit closing rule, before another model is designed or evaluated.
