# Scheduler v2 — demand-driven rostering

Status: **proposed**. Replaces the block-based assignment loop in
`app/services/scheduler.py`.

Evidence: 30 weeks of real rosters from Top Oil South Link, 2,106 shifts.

---

## 1. Why the current model cannot work

Today the solver tiles each day into non-overlapping segments and staffs each
one to a `min_staff` floor.

```
CURRENT:   [00:00────08:00][08:00────16:00][16:00────23:59]
              1 person        1 person        1 person       = 24 person-hours/day
```

The shop actually runs like this:

```
REAL:      [23:30──────────07:00]                              night
                 [06:00────────────16:00]                      early
                    [07:30──────────16:00]                     early
                              [13:00────────21:00]             mid
                                   [16:00──────────00:00]      late
                                                               = 66-82 person-hours/day
```

Two structural problems, not tuning problems:

1. **Non-overlapping blocks cannot express staggered shifts.** No value of
   `min_staff` produces a 06:00-16:00 shift overlapping a 13:00-21:00 one.
2. **A flat floor per block cannot express a demand curve.** Real staffing
   peaks at 13:00-14:00 and falls to a single person overnight.

The result is a roster staffing roughly a third of what the business needs.

---

## 2. What replaces it

Three learned inputs, one new assignment loop.

### 2.1 Demand curve — how many people, per day, per hour

Derived from approved history; editable by the shop owner. Measured values:

| | 00-06 | 06 | 09 | 13 | 16 | 18 | 21 | 23 |
|---|---|---|---|---|---|---|---|---|
| Mon | 1.0 | 3.8 | 3.9 | 5.5 | 3.7 | 4.3 | 2.9 | 3.0 |
| Tue | 1.0 | 3.2 | 3.9 | 5.8 | 3.6 | 4.5 | 3.1 | 3.0 |
| Sat | 1.0 | 3.1 | 3.5 | 4.3 | 4.1 | 4.4 | 3.2 | 3.0 |
| Sun | 1.0 | 3.0 | 3.0 | 4.0 | 4.2 | 4.0 | 3.0 | 3.0 |

Stored as a 7x24 integer matrix per shop.

### 2.2 Role mix — which roles make up that headcount

Also learned. The measured mix, pooled across days:

| hour | Mgr | Sup | Floor | Stock | Night |
|---|---|---|---|---|---|
| 00-06 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| 09:00 | 1.4 | 0.3 | 1.5 | 0.6 | 0.0 |
| 13:00 | 2.1 | 0.4 | 2.0 | 0.6 | 0.1 |
| 18:00 | 1.3 | 0.8 | 1.9 | 0.0 | 0.3 |
| 23:00 | 0.4 | 0.7 | 0.8 | 0.0 | 1.2 |

This is what implements the **role saturation rule**: once a role has met its
target for an hour, further candidates of that role are deprioritised in favour
of an under-target role. Two managers and a supervisor already on at 13:00
means the next hire for that hour is Floor, because Floor is furthest below
target.

Learning it rather than hard-coding "never two supervisors" also captures
behaviour the rule misses — managers taper from 2.2 at 14:00 to 0.4 at 23:00
while supervisors rise from 0.4 to 0.8. Evening cover shifts from managers to
supervisors, and no hand-written rule said so.

### 2.3 Shift pattern catalogue

The solver may only assign shift shapes the shop actually uses. Top patterns
from history:

```
06:00-16:00  15.1%      07:30-16:00   6.4%      10:00-18:00  3.5%
23:30-07:00   9.9%      06:00-14:00   6.0%      19:00-00:00  3.3%
16:00-00:00   8.5%      13:00-21:00   4.8%      10:00-19:00  3.0%
18:00-00:00   6.7%      16:00-23:00   4.0%      ... top 20 = 85.9%
```

Inventing arbitrary blocks is what produced 00:00-08:00 shifts nobody works.

---

## 3. The assignment loop

```
for each day:
    apply fixed shifts                       (unchanged)
    coverage[hour] = 0 for all hours
    add coverage from fixed shifts

    while any hour is under its requirement:
        gap_hour   = the under-covered hour with the largest shortfall
        candidates = shift patterns that cover gap_hour
        pattern    = the candidate closing the most total unmet demand
                     (ties -> the pattern most used historically)

        eligible   = employees passing ALL hard constraints for that pattern
        if none:
            record CRITICAL if coverage would be zero, else advisory
            mark the hour unfillable; continue

        person     = best of eligible, ranked by:
                       1. role deficit   (how far their role is below target)
                       2. role priority  (RULE 1 — seniority)
                       3. learned affinity (day / pattern / coworker history)

        assign; update coverage; loop
```

**Termination.** Every iteration either assigns a shift or marks an hour
unfillable, and both strictly reduce remaining work, so the loop cannot spin.
A hard iteration cap remains as a backstop.

---

## 4. What does not change

The hard constraint filter is untouched and still runs *before* any scoring:

- under-16 curfew
- weekly hour caps
- 11-hour maximum shift
- booked leave and unavailability
- approved custom rules
- continuous coverage floor (>= 1 person whenever open)

A demand curve is a *target*. It can never license an illegal assignment. If
the curve asks for 6 people and only 3 are legally available, the roster gets 3
and an advisory — never a curfew breach.

---

## 5. Reconciling with RULE 1 (role priority)

These pull in opposite directions and the resolution needs stating plainly.

- **Role priority** governs *who gets hours across the week*. Seniors still get
  first claim.
- **Role deficit** governs *which role fills a given hour*. Once managers meet
  their target for 13:00, an additional manager scores below a Floor Assistant
  for that hour.

Ordering is: role deficit first, seniority as the tie-break within it. A
manager still outranks a floor assistant when both roles are equally short.
Without this ordering, four managers absorb the entire week — which is exactly
what happens today.

---

## 6. Failure modes

| Risk | Mitigation |
|---|---|
| Learned curve is wrong -> every roster wrong | Curve is visible and editable in the UI; regenerate is cheap |
| Cold start: no history | Fall back to current block behaviour below ~4 approved weeks |
| Curve exceeds available staff | Advisory listing unmet hours, so it reads as a hiring signal not a bug |
| Over-fitting to a quiet period | Learn from a trailing window (e.g. last 12 weeks), not all history |
| Greedy misses a better global fit | Accepted. Optimal scheduling is NP-hard; a human approves the result |

---

## 7. Files

| File | Change |
|---|---|
| `app/services/demand.py` | **new** — learn/store curve, role mix, pattern catalogue |
| `app/services/scheduler.py` | replace `_staff_segment` / segment logic with the demand loop |
| `app/routes/rosters.py` | pass the demand profile into `solve_roster` |
| `app/routes/shop.py` | endpoints to read/edit the curve |
| `tests/test_scheduler.py` | rewrite block-based assertions; keep all constraint tests |
| `tests/test_demand.py` | **new** — curve learning, role deficit ordering |
| `ml/show_roster.py` | show target vs actual coverage per hour |

The four non-negotiable rules keep their existing tests unchanged. Those are
the contract; everything above is implementation.

---

## 8. Success criteria

Regenerating week 2026-08-10 should produce:

- ~70 shifts, not 21
- 66-82 person-hours per day, not 24
- Floor Assistants roughly 40% of peak headcount, not 0%
- at most one supervisor on at a time outside evenings
- no shift pattern the shop has never used
- all 29 existing constraint tests still green
