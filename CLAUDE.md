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
   ladder (`role_hierarchy`) — *except* on a shift that already has a settled
   owner. See §2b.
4. **Nobody exceeds their own limits** — contracted hours, weekly cap, or the
   under-16 curfew (never before 08:00 or after 19:00).
5. **No shift longer than 12 hours** (`ABSOLUTE_MAX_SHIFT_HOURS`).
6. **At least `min_rest_hours` between shifts**, defaulting to 11
   (`MIN_REST_HOURS`) — the daily rest entitlement in the Organisation of
   Working Time Act. Per shop, and **floored at 10** in `models.py`: a shop
   that needs to go below the statutory figure goes to ten and no further,
   rather than switching the rule off by typing a number. A roster under the
   shop's own figure still reports every breach and still needs force
   approval, so the decision is recorded either way (§4b).

   **Every check must read the shop's figure, not the constant.** The solver
   did and `compliance.py` and `roster_validation.py` did not, so a manager
   who set 10 watched the caution keep saying 11 and reasonably concluded the
   page was stale. Two switches that can disagree is one too many (§11).
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

## 2b. The shift belongs to whoever normally works it

If one person has worked a slot **60% of the times it ran, over at least 4
occurrences**, that slot is theirs. Nobody else is offered it while they are
available. `slot_owners.py`.

Ownership is per **(day, slot)** — Emma may own Monday 06:00–16:00 without
owning Saturday's.

The order when filling a slot:

1. **the owner** — the shift is theirs
2. contract need — a full-timer below their band, among people with no claim
3. whoever else actually covers it, most often first
4. role priority, as before

> Why the owner moved above contract need: `_contract_need` returns a negative
> number for any salaried employee below their band and zero for everybody
> else, so while a full-timer was short they outranked the owner on **every**
> slot they were eligible for. Monday is built first, when the shortfall is
> still the whole contract, so Monday took the worst of it — four settled
> shifts changed hands on one day at the reference shop, including a 06:00
> opening its owner had worked in 14 of 24 weeks.
>
> The contract was never the problem. 41 hours can be reached from many
> combinations of shifts; it needs *enough* slots, not *that* slot.
> `_top_up_contracts` runs afterwards for anyone still short and
> `under_contract` reports whoever it cannot reach. Taking somebody's settled
> shift bought the contract nothing and cost the manager an edit.
>
> Only rank 0 jumps the contract. Somebody who covers a slot occasionally has
> a preference, not a claim.

> Why rule 3 was narrowed: familiarity only asks whether somebody *could*
> work a shift. A manager who covered a few early starts passes it and then
> wins on seniority — so the roster kept handing the opening to him instead
> of to the assistant who had opened it every week for months. The shop's own
> rosters are the evidence, and a rule that overrides them is not encoding
> seniority, it is ignoring the data.

Ownership never beats a hard constraint. An owner on leave, curfewed, at
their cap, inside the 11-hour rest window or already on five days does not
get the slot.

Two consequences that are easy to get wrong:

- **Senior cover (Pass 0b) runs first**, so it must prefer a shape the senior
  owns, then an unowned one, and only then somebody else's — weakest claim
  first. Otherwise it lands on the busiest shape, which is usually the one
  somebody has owned for months.
- **Slot claiming is two passes.** Somebody standing on a slot they own
  claims it before proximity matching runs. Monday has 06:00–16:00 *and*
  06:00–14:00; without this the manager on his own 06:00–14:00 cancels the
  wrong one and its owner loses her shift.

## 2c. Regenerate varies only what nobody has a claim on

The solver is deterministic, so Regenerate used to be a button that provably
did nothing — sixteen presses, sixteen identical weeks. The fix is **not** to
shuffle everything: a reshuffled roster hands back the 06:00 opening somebody
has worked for months, and every one of those is an edit the manager has to
undo.

So a **seed** varies only genuinely arbitrary choices (`_pick_for_slot`).
Three conditions must all hold before anything moves:

- the slot has **no owner** — a settled shift is not a coin toss
- the alternatives are **no worse on contract need** — contracted hours are
  already being paid for and are not traded for variety
- they are within `VARIATION_DEPTH` on preference — somebody who covered the
  slot twice does not get equal billing with whoever covers it most weeks

Choice is weighted, first choice twice as likely as second, so the usual
person stays the likeliest outcome. **Generate seeds; Rebalance does not** —
rebalancing exists to rearrange the week around a decision just made, and
anything else it moves is noise. The seed is stored on the roster, because a
version nobody can reproduce cannot be explained.

One consequence that is not a bug: an owned slot whose owner is *unavailable*
can change hands between seeds, because varying an unowned slot changes who is
already working that day. Nobody loses a shift they had. The guarantee is
narrower and exact — **a shift its owner actually got never moves.**

## 2d. Extra is the inverse of pinned

Two flags, one idea seen from opposite sides:

| | Means | Consumes a demand slot? |
|---|---|---|
| **pinned** | "*this* person fills this slot" | **yes** |
| **extra** | "this person *as well as* the slots" | **no** |

That single bit decides everything, with no special-casing. Emma **pinned** at
Monday 06:00 fills one of the two openings, so the solver places one more
person. Emma **extra** at Monday 06:00 fills none of them, so both are still
staffed and she is on top — three people, deliberately.

An extra shift is **kept through a rebalance** (it is a decision, like a pin),
its **hours still count** against the weekly cap, the contract and the
five-day limit, and the **legal limits still apply** — curfew, 12 hours, the
rest gap, booked leave. Bending those is the sick-cover flow's job, where the
override is named and recorded.

The one trap: `_apply_locked_shifts` must carry `extra` back through. Laid
down as an ordinary pin it starts cancelling a slot, turning "as well as"
into "instead of".

**What an extra teaches: the timing and who worked it, never the headcount.**
The three learners used to disagree, and none of them did that — `demand.py`
counted extras toward the staffing LEVEL, so adding somebody once meant the
shop was thought to need an extra body on that day for ever, while
`slot_owners.py` ignored extras entirely, so a shift added every week for six
months never became anybody's.

| | counts an extra? | why |
|---|---|---|
| `required()` staffing level | **no** | "as well as, this week" is not "we need another body every week" |
| `staff_targets` day size | **no** | same |
| `day_slots` shape vocabulary | **yes** | the same 17:00-21:00 ten weeks running IS a shift this shop runs |
| ownership, who works it | **only on a real slot** | see below |

Ownership is the careful one. Counting every extra would let somebody added
four times become the OWNER of a slot the shop does not run, and the solver
would then place them there as ordinary cover — "as well as" becoming
"instead of" by a different route. So an extra counts toward ownership only
for a shape that has ALREADY earned a place in `day_slots` on its own
frequency (`build_owners(known_shapes=...)`). Because extras no longer
inflate the level, that shape has to earn it honestly.

Called without `known_shapes` — as the `ml/` diagnostics do — extras are
ignored entirely, which is the older, safer behaviour.

## 2e. Rebalance Day re-solves one day and freezes the rest

The other six days are handed in as **locked shifts** — not skipped. Locking
means their hours still count against every cap, so two extra hours on
Wednesday cannot quietly push somebody over their week.

Locking alone is not enough, though: the fill passes must also be **narrowed
to the target day** (`only_day`), including `_top_up_contracts`,
`_fit_contract_hours` and `_close_short_hours`. Without that, a day that is
*short* gets quietly restaffed, and half an hour appears on somebody's Friday
finish. The manager asked about Wednesday.

## 2f. Hourly staff are evened out after the week is built, not during it

A salaried contract is a promise the shop pays either way, so `_contract_need`
pulls a full-timer up to their band. Somebody paid by the hour is promised
nothing in particular, and `_contract_need` returns **0.0** for all of them —
so they were perfectly tied on that term and nothing knew that one had been
given 25 hours and another 5.

Measured at the reference shop: the week was the right SIZE (+2% against a
normal week) and 11 of 18 hourly staff were more than 2h from what they had
been working. Jane on 13h against a recent 32; Roisín on 31h against 21. The
volume was right and the distribution was not.

**Two attempts to fix it inside the per-slot ranking changed nothing, and
could not have.** The sort answers *"who takes this shift"*; "Jane should
finish the week near 32 hours" is a property of all forty shifts together. A
local rule cannot express a global target, and ranked high enough to bite it
stops being a fair share-out and starts taking settled shifts off the people
who always work them. Both attempts are recorded in `feedback.md`; do not
try a third.

So `_rebalance_hours` runs **after** the fill, when coverage, contracts and
the demand shape are all settled, and what is left is only who holds the
shifts nobody has a claim on.

**The target is the median of the last `TREND_WEEKS` (8) weeks they appear
in**, bounded by what their availability can hold, leave booked in the target
week, and their cap.

- A **window**, not a decayed average over everything. The average always lags
  anybody who is CHANGING, which is exactly who this is for: Jane climbing
  from 14h to 34h read as 28.5h, and Aneesh dropping to weekends kept
  reading as full weeks.
- The **median**, so covering one holiday at 40 hours does not quietly become
  somebody's new baseline for two months.
- **Availability bounds it immediately.** Somebody who has just dropped to
  weekends cannot be given a full week, and their availability says so the
  moment it is entered rather than after eight weeks of evidence.

Four rules the pass never breaks:

1. **It moves work, it never deletes it.** Nothing happens unless somebody is
   below their usual week to receive it, and a refused move puts the shift
   straight back. Somebody over their hours with nobody able to take them
   KEEPS them — the shop needs those shifts, and dropping one to tidy a total
   would leave an hour unstaffed.
2. **Never an owned shift** (§2b), a pin, an extra, a fixed or a locked one.
3. **Every move must be strictly fairer, AND must not push the donor below
   their own usual week.** Total distance falling is not enough on its own:
   stripping 16 hours off somebody 10 hours over improves the total and
   leaves them 6 short. That happened, to Roisín, before the second half of
   this rule existed.
4. **Skipped entirely during a single-day rebalance.** The manager asked about
   Wednesday; quietly reshaping Monday to even out a weekly total is not an
   answer to that (§2e).

> Honest scale of the win: total distance from usual 68.4h → 50.6h, worst case
> −15.8h → −8.8h, nobody left above their usual. The COUNT of people more
> than 2h off did not move (11 of 18) — a count cannot tell −15.8 from −2.6.
> Whether that is worth a pass in the solver was a judgement call, made by the
> shop owner, not by the measurement.

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

## 4b. Editing warns; approving is where the rules bite

An edit that breaks a rule is **saved**, not refused. Refusing read as the app
knowing better than the manager, and it does not: somebody moving a shift at
6am knows things the app cannot see. It also made a roster impossible to
finish and taught people to work around the edit screen — which is where the
corrections signal comes from.

So: warn, allow, mark the person in the grid, and refuse at **approval** —
the moment a draft becomes the schedule people are told to work. A week with
breaches goes through only on **force approval**, which re-asks for the
account password and records who overrode what (`compliance.py`,
`overridden_rules` on the roster, plus the activity log).

**Two breaches no password clears** (`compliance.HARD_FLOOR`):

- `minor_curfew` — an under-16 outside 08:00–19:00. Criminal law, not a
  company rule, and a signed-off record of it is discoverable.
- `double_booked` — one person in two places at once. Not a judgement call;
  forcing it produces a roster that cannot physically happen.

**One structural check still refuses the edit itself:** the same person twice
on one day. `corrections.diff_roster` identifies a shift by `(employee, day)`
and says so in its own docstring — two rows with that key make the diff
ambiguous and would quietly corrupt the corrections history.

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

## 7b. Recent weeks count for more

Every week used to count the same, so a deliberate change took the full
24-week window to be believed. Cut two people from the evening and three
months later the profile still said five — and still *built* rosters with
five, so the manager deleted two every week. The product was generating its
own edit burden.

Weights halve every **8 weeks** (`RECENCY_HALF_LIFE_WEEKS`). The divisor is
the **sum of the weights**, not the number of weeks — dividing weighted counts
by a plain count reports a shop as quieter than it is.

- 8 weeks is a judgement, not a measurement. Shortening it to 4 makes a
  change land in two months instead of four, and also lets **one odd week**
  move the shape. There is a test for each side; they disagree below about 6.
- A change is followed within roughly **four months**, not two. That is the
  honest number and the tests say so.

**Christmas is not drift.** A recency-weighted average reads a busy December
as permanent growth, then reads January as collapse. So a week about 52 weeks
before the target keeps a weight floor (`SEASONAL_ECHO_WEIGHT`), which recency
alone would have reduced to about 0.01.

This does **nothing** until a shop has a year of history — you cannot know
December is busy without having seen a December. `seasonal_weeks` reports
whether any were found, and the UI says so rather than implying a yearly
pattern it has never observed. With only one prior year there is exactly one
observation of that week, and it deliberately does not outvote twelve recent
ones: the panel reports last year's figure instead, and the manager decides.

## 7c. "Against the usual" is information, not a rule

A second panel beside Advisories, and the split is the point. Advisories are
what the **solver** did — stretched a shift, moved a finish. "Against the
usual" is what **this week** looks like next to every other week the shop has
run: *"mon 17:00–21:00 — 1 on, this shop usually runs 3."*

It never blocks approval. Running leaner is a business decision the manager is
entitled to make; what they should not do is make it by accident. Consecutive
hours collapse into one note, and a gap under 2 hours is not mentioned at all
— a changeover hour is already handled by stretching a neighbour, and saying
so as well buries the hour that matters.

## 7d. Coverage is counted in whole hours, and edges land on them

`hours_covered` walks a shift in 60-minute steps **from its start minute** and
floors each to an hour. A shift beginning 17:30 is therefore credited with the
whole 17:00–18:00 block on the strength of being there for half of it.

That is a **units convention, not a bug**, and it is self-consistent: `demand.py`
uses the identical rounding when it learns, so `required(tue, 07)` was itself
computed by counting the shop's 07:30 starts as present at 07:00. Both sides of
the comparison speak the same slightly-wrong language.

It stops being harmless the moment a *pass writes new times against it*, because
then the app is choosing a shape on the strength of the rounding:

- **Gap-closing snaps to the hour.** Moving a finish 30 minutes and asking
  "covered now?" always got yes. The edge lands on the boundary instead —
  finish at `(hour+1):00`, start at `hour:00`. Costs up to half an hour more
  and buys cover that is real.
- **A stretch is capped at an hour, cumulatively.** Measured against the shape
  the shift started the pass with, not its current one: a shift short at 15:00,
  then 16:00, then 17:00 was being stretched an hour at a time into a four-hour
  extension nobody agreed to. Four consecutive short hours is a *missing shift* —
  leave it short and say so.
- **A contract trim rounds down to a whole hour.** A 42.5h band is 8.5h a day
  and the half-hour used to land on the finish. Rounding down gives back half an
  hour a shift; `_top_up_contracts` makes it up, and `under_contract` reports
  anyone it cannot reach.

**The step is learned, not assumed.** Rounding a contract trim to a whole hour
is right for a shop that ends shifts on the hour and wrong for one that runs
10:30 and 12:30 finishes — there, every trim would drag the rota toward a
convention it does not use. `demand.finish_granularity` reads it off the shop's
own rosters: the coarsest of 60, 30, 15 that ≥90% of finishes are a multiple
of, defaulting to 60 below 50 shifts. Coarsest-that-fits rather than most
common, because the question is what a trim may round to without inventing a
shape the shop does not write. **Only finishes** — starts are never rounded,
because familiarity is keyed on them.

Gap-closing stays hour-aligned whatever the shop's convention, because that one
is not convention: covering an hour means being there for all of it.

**Top Oil's own convention is the opposite of the obvious fix.** Top Oil writes
`07:30–16:00` and `23:30–07:00` — half-hour on the **start**, whole-hour finish
— and ends a shift on a half hour once in 555 shifts. Matching that by moving
starts was considered and **rejected**: familiarity is keyed on start time (§2),
so nudging a start to tidy a finish risks offering somebody a shift they have
never worked. Half an hour is not worth that.

Measured on 8 solved weeks, before → after: shifts ending off the hour 11.2% →
1.1% (manager 0.2%); hours where the model counts more people than are ever
present at once, 25/week → 12.75/week (manager 12/week). **The solver is now at
the manager's own baseline**, and everything left is the shop's shapes rather
than anything the solver invented.

`ml/check_partial_hours.py --source solve --edges` is the measurement. Making
`hours_covered` strict is still open, and is now the *only* remaining source —
but it would re-base learning and solving together, so the effect is not
predictable without trying it. Do not start it without that measurement in hand.

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

## 9b. Top Oil is a fixture, not the specification

Said plainly by the shop owner, and it is the right frame:

> Top Oil data is not the universal data. I am just using that data to test
> and give the feedback and improve what is wrong.

The importer had only ever been shaped by that one workbook, and it had
quietly taken its habits for rules:

| Assumed, because Top Oil does it | Actually true |
|---|---|
| one sheet is one week | a manager keeps a **month** in one tab, blocks stacked |
| the sheet **name** dates the week | it may be `Sheet1`; the dates are in the header rows |
| column 0 holds a role heading | it may hold **names**, and there may be no role column |

Every one of those produced a wrong import that looked like a solver
problem. Six weeks arrived as one week of 42 shifts, which put the shop
below `MIN_WEEKS_FOR_DEMAND`, so the profile stayed generic and nothing
could be owned — and the visible symptom was "it is ignoring who works
Mondays and using role priority instead". The parser was at fault three
layers upstream.

**So: when a real file does not import, the parser is the suspect, not the
shop.** And a fixture that has never failed is not evidence the code is
general — it is evidence the code has only met one shop. `find_header_rows`
returning more than one row is what the second shop needed and the first
never exercised.

The same warning applies to `ml/` diagnostics, which are all written
against Top Oil's shape.

## 10b. One shop's evidence, every shop's code

The logic is general — there is no shop id, name or special case anywhere in
`app/`, and the tests build synthetic shops from scratch rather than reading
the reference workbook. **The thresholds are not.** Every number below was
calibrated against Top Oil South Link's 30 weeks, which is one shop:

| Constant | Value | Where | Calibrated on |
|---|---|---|---|
| `OWNERSHIP_SHARE` | 0.6 | `slot_owners.py` | Top Oil's rota |
| `MIN_OCCURRENCES` | 4 weeks | `slot_owners.py` | Top Oil's rota |
| `DEFAULT_LOOKBACK_WEEKS` | 24 | `demand.py` | Top Oil's rota |
| `MIN_REPEATS` | 3 | `corrections.py` | judgement — untested |
| `VARIATION_DEPTH` | 2 | `scheduler.py` | judgement — untested |
| `FAMILIARITY_MIN_SHIFTS` | 8 | `availability.py` | Top Oil's rota |
| `TREND_WEEKS` | 8 | `hours_target.py` | judgement — chosen by the owner |
| `_REBALANCE_TOLERANCE_HOURS` | 2.0 | `scheduler.py` | judgement — untested |
| import defaults | €13 / 25 / 40h | `setup_status.py` | arbitrary |

What breaks, and how it will present:

- **A chaotic rota** — nobody clears 60%, so nothing has an owner and the
  solver falls back to contract need then role priority. It will look like
  the ownership work was never done. Symptom: `explain_day.py` shows an owner
  column that is almost all `—`.
- **A very rigid rota** — everybody owns everything, so Regenerate has
  nothing left to vary and looks broken again. Symptom: `_pick_for_slot`
  returns `ordered[0]` on every slot.
- **A shop that rotates staff on a longer cycle than 24 weeks** — the window
  cuts the pattern in half and the demand profile learns a shape the shop
  does not run.

**Do not tune these for a customer who does not exist yet.** Guessing at a
hypothetical shop is how the reference shop's own numbers stop being
evidence. But when a second shop complains that the roster "does not know who
works what", this table is the first place to look, and the fix is probably
per-shop settings rather than a different global default.

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
