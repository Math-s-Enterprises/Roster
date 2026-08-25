# Roster — working agreement

AI-assisted staff scheduling for retail. FastAPI + Motor/MongoDB backend,
React 19 + CRA/craco frontend. Built against a real shop: Top Oil South Link,
~24 staff, and 30 weeks of that manager's own rosters.

Read this before changing anything. Most of it was learned the hard way.

See also `feedback.md` — how to work on this project, and the mistakes already
made so they are not made again.

---

## 1. Rules that are never relaxed

These are the product. A roster that breaks one is wrong, however convenient.

1. **Somebody is on the floor from open to close.** Every day.
2. **A 24-hour shop always has someone in**, including overnight.
3. **Hours go to the most senior role first**, down the shop's configured
   ladder (`role_hierarchy`).
4. **Nobody exceeds their own limits** — contracted hours, weekly cap, or the
   under-16 curfew (never before 08:00 or after 19:00).
5. **No shift longer than 12 hours** (`ABSOLUTE_MAX_SHIFT_HOURS`).
6. **At least 11 hours between shifts** (`MIN_REST_HOURS`) — the daily rest
   entitlement in the Organisation of Working Time Act.
7. **Nobody works more than 5 days a week** (`MAX_WORKING_DAYS`), so everyone
   gets two off.

**If keeping these means leaving an hour empty, leave it empty and say so.**
Never invent coverage that cannot legally be staffed. An honest gap the
manager can act on beats a roster that quietly breaks the law.

## 2. Familiarity is an absolute block, not a warning

If somebody has never worked a shift starting near that time, they are not
offered it — no matter how short the day is. Keyed on **start time**, with a
tolerance, not on the exact pattern.

The one escape: **no history at all is not evidence of unsuitability.** A new
starter can be rostered anywhere, because there is nothing to be unlike.

> Why it matters: importing a *different* shop's roster gives everyone history
> that excludes your opening hours, and the solver then refuses to open the
> shop. Importing a mismatched roster is worse than importing none.

## 3. Approved weeks are locked

Approving is when a roster becomes the schedule people work, **and** when it
joins what the scheduler learns from. So:

- Generate, rebalance and manual edits are all refused on an approved week.
- **Unapprove** reopens it — and takes it back out of the learning. Nothing is
  cached, so clearing the flag *is* the unlearn.
- A week that has already finished cannot be reopened. It is a record now.
- **One approved roster per week, ever.** Two would count as two worked weeks
  in everything downstream.

**The one exception: a sick call.** Somebody phoning in at 6am cannot wait for
the week to be reopened. `POST /rosters/{id}/sick` changes one shift, keeps
the week approved, and writes to the activity log. Narrow, named, recorded —
not a general "edit anyway".

## 4. Emergencies are the manager's call, not the solver's

The solver refuses to break a rule. Correct when building a week from nothing:
there is always another arrangement to try.

Wrong at 6am with one person off and the shop opening in an hour. There, the
question is not "covered or uncovered" but **"which rule do I bend, and who do
I ask"**. So `sick_cover.py` ranks *everybody* and states what each would cost.
The list is never empty while anyone could physically do it.

**Hard floor — never offered, however short the shop is:**
under-16 curfew · over 12 hours · overlapping hours · booked annual leave.

Everything else is offered with the price named, and the override recorded.

## 5. Derive state, never store it

A `step_3_done: true` flag starts lying the moment the data behind it changes.
`setup_status.py` asks the data every time it renders. It costs a few counts
and it is always true.

Same reasoning: preference weights, the demand curve and familiarity history
are all recomputed from `{"approved": True}` on every generation. Never cached.

## 6. Multi-tenancy is welded in, not remembered

`ScopedCollection` in `tenancy.py` puts `shop_id` into every filter. **Never
query a collection directly** — go through `scope.*`. The prototype relied on
forty separate queries each remembering, and that is exactly how one shop's
staff data reaches another.

## 7. Learn from the shop's own history

`demand.py` learns per-day shift lists (`day_slots`) from a trailing
**24-week** window, needs at least **4 weeks** to use them, and falls back to
generic block coverage below that.

- **One roster per week** — `latest_per_week()`, newest wins. A duplicated week
  pulls twice as hard on every weight.
- **Largest-remainder apportionment** for slot counts, so rounding preserves
  totals rather than dropping shapes.
- Overnight hours belong to the day the shift **starts**.

## 8. Time is measured in real time, not clock time

The single most common source of wrong answers in this codebase.

A 23:30–07:00 Monday night **finishes on Tuesday**. A 17:00 Tuesday start is a
ten-hour turnaround, not thirty-four. Compare shifts as minutes from Monday
00:00 (`_week_span`), never as bare `HH:MM`.

Related distinctions that are easy to get wrong:

- **Back-to-back vs split shift.** Two shifts under an hour apart are one long
  stint and the 12-hour cap applies to the whole of it. With a real gap they
  are two shifts, and a split shift is ordinary in retail.
- **Span vs paid hours.** Salaried contracts are written in *span* (42.5h on
  the floor, breaks included). Hourly and student caps are *paid* hours.
  `breaks_are_paid` is per shop and moves every wage figure.
- **Month boundaries.** A roster week is Mon–Sun; a payroll month is not.
  Shifts are dated individually so January gets its days and February gets
  the rest.

## 9. Never invent data

- Imports do **not** fabricate email addresses. A spreadsheet has none, so the
  field stays empty and dispatch reports who it could not reach.
- Job titles resolve against the shop's own `role_hierarchy`, with explicit
  `role_aliases` for abbreviations. A title the shop does not have is **kept
  verbatim** and appears at the bottom of the ladder to be positioned.
- Rule parsing (`rule_parser.py`) is deterministic. Unparseable rules are
  **reported, not guessed**.

> Why: a hardcoded `ROLE_MAP` once rewrote every manager title to "Manager" and
> both "Night Shift" and "Goods Inwards" to a "Stocker" the shop had never
> configured — flattening five rungs of the hierarchy into one.

## 10. Conventions

**Tests** are named for the behaviour they protect, not the function they call:
`test_a_short_turnaround_is_refused`, not `test_rest_check`. Assert real
numbers, not "greater than zero" — a plausible-but-wrong roster gets believed.
When a constant matters, assert the value, not the constant.

**Comments explain why, not what.** Especially: what was tried before and why
it failed. Several comments in `scheduler.py` exist because the obvious fix
was wrong.

**Messages name the real cause.** "Everyone is on leave or curfew-restricted"
sent a manager hunting for holidays that did not exist, when the truth was two
employees and 109 hours to cover. Say the actual thing.

**Refusals carry structured reasons** (`{message, reasons[]}`) so the UI can
list them one per line. Never render an error object directly into JSX.

**Migrations are `ml/*.py` scripts** — dry run by default, `--commit` to apply,
and they print what they would change first.

## 11. Traps that have bitten before

- Verifying a claim about the data **before** designing around it. The 11-hour
  rest rule was checked against 2009 real shift pairs (99.6% compliant) before
  being made a constraint — because if history broke it, enforcing it would
  leave the solver fighting the patterns it learns from.
- `seed_system_rules` runs on **every authenticated request**, and the browser
  fires several in parallel. Read-then-insert races itself. Use upserts.
- Frontend and backend both had a roster paywall. Two switches that can
  disagree is one too many.
- `/dev/reset` also resets shop hours, `open_24h` and `onboarded` — not just
  the data.

## 12. Commands

```bash
# Backend (from backend/, venv active)
python -m pytest                    # full suite, must stay green
uvicorn app.main:app --reload --port 8001

# Frontend (from frontend/)
yarn start

# Diagnostics
python ml/diagnose.py --email <e> --week YYYY-MM-DD --dry-run
python ml/check_rest_gaps.py "<workbook.xlsx>"
```

## 13. Still outstanding

Docker, CI, rate limiting, error tracking, backups, GDPR paperwork
(privacy policy, DPA, export/delete), Resend email setup, and deciding
whether billing is enforced. None of these are code problems in the solver —
they are what stands between this and paying customers.
