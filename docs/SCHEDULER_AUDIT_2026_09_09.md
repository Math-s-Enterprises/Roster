# Scheduler audit — 9 September 2026

**Status update:** both confirmed defects below were repaired in `30a47cf` and merged through PR #3 (`bf667f6`). The findings and reproductions below describe the pre-repair code. See [the work queue](WORK_QUEUE.md) for post-repair validation and remaining work.

## Findings

Two defects were reproduced. The 27 July role mismatch itself also has specific explanations that do not establish a solver defect. No production scheduling or approval logic was changed during this investigation.

### 1. Approval coverage disagrees with the solver at the week boundary

`backend/app/services/compliance.py:166` always uses `wrap_week=True`: it counts this week's Sunday overnight shift toward this week's Monday. It receives neither the target week nor the previous approved week's shifts.

The solver instead seeds Monday from the **previous** approved Sunday (`scheduler.py:_seed_carry_in`) and avoids wrapping the new Sunday when carry-in exists. The two calculations can disagree even though both count whole hours.

Reproduced with the 24 August baseline simulation:

- Solver's final coverage counters: no empty opening hours.
- Approval checker: Monday 00:00–06:00 flagged empty.
- The previous Sunday's night shift supplies those Monday hours in the solver. The current Sunday's pattern does not, and belongs to next Monday anyway.

The checker feeds the roster page, manual-edit warnings and approval. The reverse mismatch can also hide a Monday gap by crediting the following Sunday's shift; that reverse consequence follows from the code but was not observed in this live trace.

**Fix design:** give every coverage-check caller the same previous-week context and boundary policy as the solver. Test both genuine carry-in and the false credit from the following Sunday, plus the existing no-history fallback. Do not fix only the diagnostic and leave approval using another answer.

### 2. Leave in any week disables contract top-ups and hour fitting

`scheduler.py:3843` and `scheduler.py:4392` use `if self.employee_off_dates.get(employee_id)` to skip a salaried employee. `_index_holidays` retains dates from all supplied holiday records, and generation fetches all those records. Neither skip checks whether leave overlaps the target week.

Independent synthetic reproduction for the week of **17 August**, with identical shop, employee, history and contract:

| Isolated pass | No leave record | A leave record on 1 December |
|---|---:|---:|
| Add shifts to reach a 40-hour contract, starting empty | 40 hours added | 0 hours added |
| Fit four existing 8-hour shifts toward the contract band | 38.5 hours total | 32 hours total |

There is no leave in the August week in either case. The 38.5-hour lower bound comes from the configured/default contract tolerance. This reproduces pass behaviour independently of the reference shop; it does not claim every affected full solve will be short, since earlier filling can already meet a contract.

Reproduce locally with `python ml/verify_scheduler_findings.py` from `backend/`. No database is required. **Fix design:** check leave dates against the week's actual dates in both passes; retain the existing treatment of leave that really is in the target week. Add regressions for past/future leave, overlapping leave, and both top-up paths.

## Why 27 July had different role counts

### Nine “Night Shift” role assignments were not nine overnight shifts

The generated week contains exactly **seven 23:30–07:00 shifts**, one starting each day. The extra two assignments under employees whose role is “Night Shift” are:

- Kelvin: Wednesday 18:00–00:00.
- Andi: Sunday 15:00–00:00 (initially 16:00–00:00, then extended for a short changeover).

The trace records Kelvin as the highest historical non-owner candidate for Wednesday evening; no Supervisor was in the eligible list for that particular choice. Andi has owner rank zero on the Sunday evening slot, so the existing ownership rule takes precedence over an eligible Supervisor. Those are consequences of the current rules and earlier history, not two extra overnight arrivals. Whether this role mix is acceptable is a manager decision, not something implied by the job title.

### Eight versus six Supervisor assignments uses different employee settings

The manager's reference includes Tintu on five weekdays and Aneesh on Wednesday, Saturday and Sunday. Current settings mark Tintu inactive and constrain Aneesh to Saturday/Sunday with a 20-hour student cap. Conor, currently active, receives four shifts in the generated week; Aneesh receives two.

Thus this simulation cannot faithfully reconstruct July's workforce. Role-based evaluation removes name matching from the score, but does not remove eligibility and active-status differences from the generation inputs. The result does not prove a role-demand defect by itself.

## Corrected ML comparison

The first backtest used the approval check as its uncovered-hour measurement. That was an error in the evaluation. It is now recorded separately from the solver's final counters, including previous-week carry-in.

| Eight-week total | Existing solver | Experimental model |
|---|---:|---:|
| Solver uncovered whole hours | **0** | **5** |
| Approval checker reported hours (contains boundary error) | 6 | 11 |
| Role-at-time difference, person-hours | 2,623.5 | 2,767.0 |

The model still does not improve this experiment. The existing solver covered all opening hours under its whole-hour convention; the five experimental gaps remain on 24 August. These figures are not an exact-minute coverage certification.

Corrected local report: `C:/Users/anees/.codex/visualizations/2026/09/08/01a082fe-db1c-7a60-84dc-09c69ef7b990/role-backtest-audited-2026-09-09/REPORT.md`. The corrected report supersedes the earlier uncovered-hour interpretation. Role counts and role/time distances did not change.

## Scope and verification

Read-only shop-scoped traces were run for 27 July and 24 August. Eight baseline/model simulations were rerun with corrected coverage accounting. Two standalone contract-pass probes reproduced the leave defect without shop-specific data. Source review connected the coverage discrepancy to the application callers. Diagnostic outputs stay local; no roster, employee, holiday or shop settings were changed.

Recommended next work: repair the two confirmed defects and their regression tests before changing the model or tuning the role ranking. Historical workforce reconstruction remains a separate data limitation.
