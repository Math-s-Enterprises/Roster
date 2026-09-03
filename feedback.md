# Working with Aneesh on Roster — feedback for future sessions

Compiled at the end of a long build. Everything here is a correction he made,
a preference he stated, or a mistake I made and should not repeat.

Read this alongside `CLAUDE.md`. That file is about the *product*; this one is
about *how to work*.

---

## 1. How he wants to work

**Plan before coding. Always.** Stated early and repeated: *"Never jump
directly into coding"*, *"Before we start coding, we will go step by step."*
Explain the approach, get agreement, then build. He will say "yes please" when
ready — that is the signal, not silence.

**Ask when the decision is genuinely his.** He engages properly with
multiple-choice questions and often improves the options rather than picking
one. Examples: on skipped staff he rejected both of my options and wrote a
better third ("keep the shifts and the pattern but that employee should not be
added to the employee list"). On unknown roles he chose the conservative
option. Do not guess when the answer changes what gets built.

**Be concise.** His stated preference: *"as concise and direct as possible…
a good test is whether you can remove words and still get the same point
across."* Long explanations are not appreciated; the finding is.

**He has full permission to rewrite whole files.** The prototype came from
Emergent and is disposable. Do not tiptoe around existing code.

**He wants the reasoning, not just the result.** Every time I explained *why*
something broke — the mechanism, not the symptom — the conversation moved
faster. When I gave a conclusion without the chain, he asked for it.

**Currency is euros.** He corrected a `$` in the UI. Irish shop.

---

## 2. Corrections he made — and what I had wrong

**Overnight hours belong to the day the shift starts.**
I proposed a "scarcest hours first" fix for uncovered Sundays. He overruled me:
the real issue was that a Sunday night shift covers into Monday. He was right
and my fix would have been wrong. *Lesson: when he contradicts a diagnosis, he
is usually reasoning from the real shop and I am reasoning from the code.*

**Familiarity must block, not warn.**
I had it as a soft warning. *"These are not rules — if a person hasn't worked
that shift before, avoid it completely."* Same again for manual edits: *"It
should not allow me to do it. It should pop up a dialog saying it cannot be
done."* When he says a rule, he means a hard constraint.

**Let the solver choose shift lengths.**
I had fixed 10-hour blocks for contract staff. *"Let the solver decide the
shifts of full time workers based on the requirement… 8, 8.5, 9 and so on."*

**42.5 hours means time on the floor, breaks included.**
Not paid hours. This distinction moves every wage figure and I had it inverted
initially.

**Import comes before adding staff.** He reordered the setup checklist: import
is step 2, employees step 3, because the import creates the employees.

**12 hours, not 11, for maximum shift length.** He checked with his manager.

**Split shift ≠ back-to-back.** I was summing any two shifts in a day against
the 12-hour cap. He confirmed the distinction I proposed: touching shifts are
one long stint, shifts with a real gap are two. *"Yeah, that is what i meant.
Thanks for the correction."*

**He had already shared his repo link.** I ran `git init` and set up a fresh
repo when `github.com/Aneeeesh/Roster` already existed and he had told me so.
*Lesson: search the transcript before assuming something is missing.*

**"Have we built this or not?" — check the code, because twice it was "yes".**
He asked whether the app suggests a fixed shift when he keeps making the same
edit. It does: `corrections.py` → `/reports/corrections` → the What It Learned
page, 28 tests. He then asked whether pressing Agree sets it up automatically
or sends him to the employee page. It sets it up: `apply_suggestion` writes the
fixed shift or updates the employee record itself. Answering either from memory
would have had me rebuild working code. *Read the route before answering a
"does it do X" question.* The only thing actually wrong was the wording — the
suggestion said the setting lands "on their employee record where you can
change it back", which reads as an instruction to go and do it yourself.

**He collapses my design forks by reasoning about the manager.** I split his
request into A (suggest a fixed shift) and B (fix the learned demand shape) and
asked which. *"Option A. Because if the manager decides to put that change as a
fixed shift, there is no need for option B."* He is right that A covers the
case he has; the residue B would have handled — the shape still being wrong for
whoever covers when that person is off — is real but hypothetical, and by his
own §10b rule it waits for evidence.

**When my explanation is too abstract he says so, and the fix is his own shop.**
*"I did not understand this. Can you explain it to me like a ten-year-old?"*
came after a paragraph about double-counting and demand profiles. Rewriting it
as "twenty-four weeks, twenty-four votes, your change is one vote" landed
immediately. *Explain in shifts and weeks, not in weights and windows.*

**He expects the obvious thing, not a refusal.** On dragging a shift onto an
occupied cell: *"I want those two shifts to be exchanged."* The app said "that
slot already has a shift", which is true and useless — two people trading
shifts is the commonest reason to drag at all. Same instinct as §4b: refusing
is rarely the right answer to a manager who knows what they want.

**He knows his staff, and that beats my model every time.** In one session he
corrected four of my "findings" out of existence with facts the app already
held but was not using:

| I reported | He said | Where the app already knew |
|---|---|---|
| Teja 56.6h/week | — | duplicate week; `latest_per_week` |
| Everyone under their hours | six of them left months ago | `is_active` |
| Aneesh under by 8.8h | *"he changed his availability to Saturday and Sunday only… he might end up getting 16 or 17 hours. That's okay, that's how it works."* | availability rules |
| Emma and Jamie badly under | *"Emma was on holiday and Jamie was also on holiday"* | the holidays collection |
| Megan and John stealing each other's shifts | *"both of them work 6 to 4"* | `SlotHistory`'s own docstring |
| Emma stealing John's Friday 06:00 | *"Emma usually works on Friday at 6 a.m."* | same |

**Ask him before building.** Each of those was a question he could answer in
one line and I could not answer at all. A shortfall and a resignation are
indistinguishable from inside the data.

**"Top Oil data is not the universal data" — he has now said this three
times.** Once about the importer, once mid-session unprompted, and once more
after I proposed a fix. Every time he was right and every time it was because I
had started designing from one shop's symptom. The swap pass was built from a
gap that a corrupt import invented; deleting it was the direct consequence of
taking him seriously. **Treat the reference shop as a fixture that can be
wrong, not as the specification** (CLAUDE.md §9b, §10b).

**He asks the deflating question at exactly the right moment.** *"Do I have to
do these changes for my product to work?"* after I had laid out three
increasingly large options. The answer was no, and I should have led with it.
He also asked *"do I need AI because it decides whether it can swap or no?"* —
which correctly identified that I was reaching for machinery where arithmetic
would do. **When he asks whether something is necessary, he has usually already
noticed it is not.**

---

## 3. My recurring failure modes

**I diagnose from the symptom instead of the data.**
The worst instance: 66 uncovered hours. I confidently blamed the familiarity
rule, wrote several paragraphs of mechanism, and was completely wrong — he had
two employees and needed 109 hours of cover. The diagnostic output showed
`weeks learned: 0`, which killed my theory instantly.
**Fix: ask for the diagnostic output BEFORE explaining. One command beats four
paragraphs of plausible reasoning.**

**I assume schema and API shapes instead of checking.**
- Assumed `users.shop_id`; the link is actually `shops.owner_id → users.user_id`
- Assumed `read_xlsx` takes bytes; it takes a path
- Assumed `hours_by_day` returned a tuple; it returns a dict
- Wrote a test CSV with the wrong column layout for the parser
Each cost a round trip. **Grep the definition first — it takes seconds.**

**My arithmetic in tests has been wrong more than once.**
Wrote "87h vs 85h" when the numbers gave 82.5. Chasing that error did find a
better test, but I should verify the maths before writing the assertion.

**I write ambiguous status messages.**
`"Checked 0 employee(s)"` was equally true of a healthy shop and a mistyped
shop id — exactly when you need to tell them apart. Also wrote a genuinely
garbled comment in `models.py` about `min_rest_hours` that had to be rewritten.
**Read messages back as if you did not know the answer.**

**I introduce regressions in adjacent code.**
Made the calendar icon invisible with `filter: invert(1)` plus
`color-scheme: dark` — black on black. Left dead scaffolding (`if False else
None`) in a test. **Check the thing next to what you changed.**

**A rename is not a safe refactor, and I keep treating it as one.**
Renaming `was`/`now` to `was_start`/`now_start` in `_suggest_from` broke two
things at once: the block below still referenced the old names, and the guard
`if now <= was: return None` went with them. The second was the dangerous one —
without it the availability branch would have set somebody's earliest start
EARLIER than the one they already had, which is the opposite of what that
setting means and would not have looked wrong in the UI. Caught only because a
test existed for it. **After a rename, grep the old name before running
anything.**

**I nearly overturned a decided question as a side effect of an unrelated one.**
Asked to notice shifts being lengthened, my first version answered *any*
reshape with a fixed shift — which silently reversed
`test_an_earlier_start_suggests_nothing`, where somebody had deliberately
decided that being pulled in early says a person was free all along, not that
anything needs setting. The test failing is what stopped me; without it the
behaviour would have changed with no one noticing. **When a new branch widens
a condition, list what used to fall through it and check each was not a
decision.**

**I wrote an unverified claim into a comment again.** Same failure as the
`_apply_fixed_shifts` one below, one session later. I justified keying the swap
on `(employee, day)` by writing that matching on `shift_id` "would move every
shift at once" — true of that line in isolation, but the server stamps a
`shift_id` on every path that creates a shift, so it never happens. Checked
before committing and rewrote it to give the real reason (consistency with the
validator and `diff_roster`). **A comment that explains a choice by naming a
bug is asserting the bug exists. Verify it or do not name it.**

**I have stated things about his own app that were false.**
Told him no password reset flow existed when `ForgotPasswordReq` and
`ResetPasswordReq` were right there. Described the Supabase design register as
dark when it is white — and he picked a palette based on that, then had to
reject it. **Verify before describing, especially when he will act on it.**

**I used the wrong email.** Used his Claude account address in a script
instruction when his app login is different. Small, but it wasted a run.

**I write regression tests that pass without the fix.** Three times in one
session. Each looked green and proved nothing:

- The owner-reservation test gave the early slot's history only to its owner,
  so the second person was never a contender for it
- The "Regenerate actually varies" test matched on start time alone, and
  Monday runs TWO shifts starting 16:00 — it collected two names whatever the
  code did
- The Rebalance Day tests passed with the freeze disabled, because when every
  other day is fully locked, re-solving them changes nothing anyway

**Fix, and it is cheap: break the fix deliberately and re-run before moving
on.** `cp file /tmp/bak`, disable the branch, run the test, restore. If it
still passes, the test is decoration. This caught all three.

**I claim work is finished when it is not.** Said "everything in the queue is
done" with Phases 2–5 of the corrections work outstanding. He said *"nope,
everything in the queue is not done"*. **Before saying done, re-read the list
rather than recalling it** — the doc was right there.

**I infer intent from data when I should record it.** The setup checklist
worked out whether pay and age had been reviewed by comparing them to the
importer's defaults. It cannot tell a placeholder from somebody who genuinely
is 25 on that rate working 40 hours — their step could never be completed.
**"Has a human looked at this?" is provenance, not a property of the values.**
Same distinction as §5 of CLAUDE.md, from the other side: derive state where
you can, but a DECISION has to be recorded.

**I write a diagnosis into a comment before I have tested it.** The worst
instance this session: two people showed 60h against a 40h contract. I decided
`_apply_fixed_shifts` was placing them twice after a Rebalance Day, added a
guard, and wrote a comment stating that as the cause — then tested it and
found no duplicates at all, through the solver OR the route. The duplicates
were real in his data; my explanation was invented.

**A comment is a claim. If it says "this happens because X", X has been
demonstrated.** The guard stayed (nothing should place two shifts for one
person on one day) but its comment now says "defensive, not a fix for a
reproduced bug" — which is the truth and is still useful to the next reader.

**When the cause will not come out, move the check to the boundary.** I could
not find which pass created the duplicates. Rather than keep guessing I
asserted the invariant once at the end of `solve()` — remove the extra, undo
its accounting, and REPORT it by name. Cheaper than auditing five passes,
holds against a sixth, and the report will name the pass next time. That is a
better outcome than a lucky guess would have been.

**I keep blaming the environment before the code.** "Restart the backend",
"stale module", "warm --reload" — three times, and each time the app was
current and the cause was in the logic. He restarted everything twice on my
say-so. **Build the check instead of guessing** (`ml/check_live_code.py` now
answers it in one command).

**I check that the arithmetic is right without checking that the POPULATION
can give an honest answer.** This is the single most expensive habit I have,
and it cost most of one session in four separate forms:

- **Duplicate weeks.** Reported Teja averaging 56.6h — above his 40h cap and
  above the 48h legal limit. A week with two approved rosters had both counted.
  `demand.py`, `slot_owners.py`, `corrections.py` and `learning.py` all dedupe
  through `latest_per_week`; my diagnostic did not.
- **Leakage.** Solved an already-approved week to grade the solver against it.
  `_weighted_weeks` skips only `age < 0`, so the target week itself carries
  full weight — I asked it to reproduce something it had memorised and took
  the perfect result as evidence. *He* spotted this, not me.
- **A model I had only half read.** Reported eight shifts as stolen from their
  owners. `owner_of` returns ONE person; a shape that runs twice has two
  regulars, and `SlotHistory`'s own docstring says so in the very case he
  raised (Megan and John both on 06:00–16:00). My script had only ever met
  slots that run once a day.
- **Leavers.** "Everybody is under their hours" was six people who had left
  months earlier and were still marked active.

Every one of these produced a confident, plausible, wrong number. **Before
running a measurement, write down what a non-zero answer would look like AND
what would make the population unable to produce one.** Implausible outputs —
56.6h, a perfect score, eight simultaneous bugs — are almost always the
measurement, not the system.

**A test that a value is non-zero is not a test that it DISCRIMINATES.** I
built an hours-need ranking term, wrote nine passing tests, and it changed not
one hour of the roster. `hours_aim` was populated, `_hours_need` returned a
plausible negative number, everything was green — and it returned the SAME
number for everyone, because I had copied `_contract_need`'s `-min(shortfall,
span)` without thinking about what it needed to express. Early in a week
everybody is short by more than one shift, so everybody tied. **Anything whose
job is to ORDER things needs a test that two different inputs give two
different outputs.** A constant passes every other kind of test.

**Local rules cannot fix global properties.** The same hours term failed again
even once it discriminated, and the reason is structural: a per-slot tie-break
answers "who takes THIS shift", while "Jane should finish the week near 28.8h"
is a property of all forty slots together. No ordering rule inside a greedy
per-slot loop can express it. Ranking it higher does not fix the mismatch, it
just makes it steal settled shifts. **Before adding a term to a sort, ask
whether the thing being fixed is local to that decision.**

**I mixed two shops in one summary table and frightened him.** Listed an ILS
finding (Teja, 56.6h) in a table about Top Oil with no column for which shop
each row came from. He read it as a tenant-isolation leak, which is the most
serious class of bug this product can have. The data was fine — every query
filters on `shop_id` — but the presentation was not. **Two shops in one
session means every number carries its shop's name.**

---

## 4. What worked — keep doing

**Set the keep/delete criterion BEFORE running the measurement, then honour
it.** Twice in one session this deleted work I had just finished:

- **The swap pass** (338 lines, 26 tests, all green) — built to fill a Friday
  that came out empty. The criterion was "keep only if uncovered hours fall".
  Once a corrupt import week was unapproved, the gap disappeared and the pass
  never fired on any week. Deleted.
- **The hours-need ranking term** — built to even out hourly staff. The
  criterion was "keep only if fewer than 11 of 18 are off their aim". It
  changed not one hour, twice, for two different reasons. Deleted.

Neither deletion was a wasted session: the swap pass work found the corrupt
week, and the hours work produced four diagnostics and the structural insight
that a per-slot sort cannot fix a whole-week property. **Stating the bar first
is what makes it possible to walk away from something that already works and
looks reasonable.** Writing it down after the fact never survives contact with
having built the thing.

**Sabotage every test, including the ones that pass.** Three of four sabotages
failed correctly; the fourth — the guard against repeating the
`scheduler.py:1738` bug — stayed green when I deliberately moved the term up
the sort. It used an OWNED slot, where rank 0 wins regardless, so it could
never have caught the thing it was named after. The replacement uses a slot at
58% ownership, just under the bar, where the ordering actually decides.
**A test named after a bug is not a test for that bug until you have seen it
fail.**

**Build the diagnostic instead of theorising.** The Emma question went through
four wrong explanations from me — stale code, ownership ranking, apportionment
— before `explain_day.py` showed the actual arithmetic. Every one of those
guesses cost a round trip; the tool ended it. `ml/` now holds around nine of
them — `check_hours`, `check_contract_cost`, `check_live_code`,
`check_rest_gaps`, `diagnose`, `explain_day`, `show_roster`, `why_slot`,
`who_is_placeholder` — alongside the migrations, and they are the
highest-value thing built across these sessions. **Look for an existing one
before writing a fresh query.**

**Separate the layers before debugging.** "Emma is missing" had two completely
different possible causes that look identical on screen: the slot is not in
the day's plan at all, or it is and somebody outranked her. No amount of
tuning who-beats-whom helps with the first. Ask which layer before designing.

**A/B the rule instead of reading the symptom.** The question "did owner-first
starve a full-timer?" cannot be answered by looking at `under_contract` — a
person can be short because the trading hours are not there at all, and reading
that as proof owners caused it is how a fix gets built for a problem nobody
has. `check_contract_cost.py` solves the same week twice with
`OWNER_BEATS_CONTRACT` on and off, same seed, and diffs. Short in both runs
means the hours are missing; short only with it on is the evidence. Answer at
the reference shop: nobody short either way, and 18 placements across 12 people
would change hands if it were switched off. **Option B is not needed. Do not
build it without re-running this.**

**Ask what would make this number non-zero BEFORE running it.** Four times in
two days I measured a population that could not have produced a non-zero
answer, and reported the zero as if it settled something:

1. `under_contract` before establishing that anybody *could* be reported short
2. hour-rounding against the manager's **approved** rota — hand-built, 24h,
   continuous by construction, so no hole was possible. He spotted that one:
   *"this is the output from the last 24 weeks, which are made by my manager,
   not from the solver"*
3. the same check counting only hours where the shop is **completely empty**,
   when the actual question was headcount shortfall — a 17:30 start credited
   with 17:00 leaves nobody missing, just one fewer than needed
4. reporting "PASS — only Wednesday moved" when *nothing* had moved

Every one had the same shape and the same fix. The habit is not "check the
result", it is **state what a non-zero answer would look like, then confirm the
measurement can produce it.** A detector that has never fired is not evidence.

**Test the measurement on a case with a known answer.** After the third time,
`check_partial_hours` got 13 hand-computed cases — overnight wrap, Sunday night
into Monday, two people overlapping, leave not counting — and later a synthetic
roster with a deliberate hole, to prove the detector fires at all. That is what
made the eventual zero trustworthy.

**A second real file is worth more than another test.** He uploaded his own
month-in-one-tab spreadsheet and it broke the importer three ways at once —
weeks merged, dates lost, roles invented — none of which 60 passing tests had
caught, because every one of them was written against Top Oil's shape. His
framing is now §9b of CLAUDE.md:

> Top Oil data is not the universal data. I am just using that data to test
> and give the feedback and improve what is wrong.

The tell was that the symptom he reported ("it is using role priority, not
who works Mondays") was three layers downstream of the actual fault. When a
complaint is about the solver, check what the solver was FED before checking
what it did.

**Attribute before fixing.** Half-hour finishes had an obvious suspect and a
plausible story. Rather than edit it, `--edges` split every off-hour edge four
ways: start or finish, inherited or manufactured, salaried or hourly. It came
back 42 of 42 manufactured finishes on salaried staff — unambiguous, and worth
the extra round trip because the fix meant overturning a documented rule.

**Say how big the denominator is, or a clean result means nothing.** First
version of that script printed "nobody is below their minimum" — which is
equally true of "the solver reached everybody" and "there was nobody to reach",
and those lead opposite ways. Only salaried staff with a contract band can be
reported short at all. It now names them first: 6 of 31, five with tight bands
(40–40, 45–45, 41–42.5) and Martin on 18.5–42.5, whose floor is so low he
contributes almost nothing to the result. **Any "no problems found" needs the
count of things that could have been a problem.**

**Break only the new branch to check a new test.** Disabled the new same-start
condition with `if False` and left everything else intact: both new tests
failed, the regression guard still passed. A test that passes without its fix
protects nothing, and three of them did earlier in this project.

**With no browser, verify the logic in a scratch harness.** The swap fix was
pure frontend logic, so it went into a standalone node script — seven cases
including bystanders staying put and, the one that would actually corrupt a
roster, that no swap can put two people in the same `(person, day)` cell from
either drag direction. Not the same as seeing it work, and the commit says so.

**His bug reports are precise, and the numbers in them are the diagnosis.**
"60h but the roster shows 40" plus a dry run listing four duplicate rows was
enough to prove the bug, locate it to one roster out of sixty, and identify
which pass was involved — all before I understood the mechanism. When he
gives a number, do the arithmetic on it: Megan's six shifts of ten stopping
at exactly 60 pointed straight at `max_weekly_hours = 60` being the limiter.

**Say plainly when a refusal is correct.** Twice the app was right and he
thought it was broken — the five-day guard blocking my own test fixture, and
the checklist flagging four genuinely untouched records. Saying "no, this is
correct, and here is why" is more useful than fixing a non-bug. But both times
the MESSAGE deserved the complaint even though the LOGIC did not.

**Measure before designing.** Before making 11-hour rest a constraint, I
checked it against 2009 real shift pairs from his manager's rosters: 99.6%
compliant. That number decided the design. Had it been 70%, a hard block would
have left the solver fighting its own training data. He explicitly liked this
order of operations.

**Use his real roster as ground truth.** `new roster 26.xlsx` settled several
arguments — the familiarity question, the role mapping, the rest rule. When a
design question is really an empirical question, go to the file.

**Say when I was wrong, plainly and early.** He responds well to *"I was
wrong"* followed by the correct answer. No hedging.

**Flag consequences of his own choices.** He chose "block past weeks entirely",
which would have made imported historical rosters permanently unfixable. I
implemented his choice and named the trap; he then asked for the fix. That is
the right pattern — respect the decision, surface the cost.

**Dry-run everything that touches his data.** Every `ml/*.py` script prints
what it would change and needs `--commit`. He used these repeatedly and the
dry runs caught real problems, including a role migration that would have
ranked his most senior manager below the night staff.

**Argue against bad ideas with reasons.** Advised against replacing the solver
with an LLM, against Unlimited-OCR, against Supabase, against a software
patent. Each time with specific numbers and each time he accepted it. He does
not want a yes-man.

---

## 5. Facts about his setup

- Shop: **Top Oil South Link**, ~24 staff, Ireland, euros
- App login: **anishbond27032002@gmail.com** (not his Claude account address)
- Repo: **github.com/Aneeeesh/Roster**, private, branch `main`
- Shop id: `shop_645772aee6b5`; a second "Test Shop" also exists in the DB
- His role ladder uses abbreviations the sheets spell out — "Ass Manager" vs
  "Assistant Manager", "Shop Floor" vs "Floor Assistant". Hence `role_aliases`.
- Windows / PowerShell. Venv at `backend\venv`, activate before running scripts.
- Workbook lives at `C:\Users\anees\Downloads\new roster 26.xlsx`
- Second app login also in use: **aneeshthimmapurmath@gmail.com** (current
  shop, 25 staff, 24 approved weeks). The older `anishbond…` account is the
  earlier shop.
- **Code Runner's ▶ button uses global Python**, so anything in `ml/` fails
  with `ModuleNotFoundError: motor`. Always
  `.\venv\Scripts\python.exe ml\script.py --email …` from `backend\`.
- `craco build` takes longer than a sandbox tool call allows. Frontend changes
  can be Babel-parse-checked but NOT build-verified here — say so rather than
  implying the build passed.

---

## 6. Where the product stands

Built this session, all general behaviour with no shop-specific code:

- **Slot ownership** — 60% of the weeks a slot ran, over 4+ weeks. Owner beats
  contract need; owners are reserved from earlier slots; leavers cannot own.
- **Seeded Regenerate** — varies only unowned slots, weighted. Rebalance does
  not seed.
- **Extra staff** and **Rebalance Day**.
- **Corrections learning Phases 2–4** — the falling edit count, suggestions
  that write real settings, Rebalance made primary.

Since then: force approval with named breaches and a hard floor that no
password clears; editing warns instead of refusing; a printed rota built for a
wall rather than a screen; leave no longer counted as a contract shortfall;
recency-weighted demand with a seasonal echo, and the "Against the usual"
panel beside Advisories.

Latest additions:

- **A lengthened shift is now a suggestion.** Same start, different finish,
  three weeks running → "Make this a fixed shift" at the corrected hours,
  either direction. This was the commonest edit of all and it produced nothing,
  because the `moved` branch read only the start time.
- **Dropping a shift on an occupied cell swaps the two.** It used to refuse.
- **`OWNER_BEATS_CONTRACT`** is a named switch rather than an inline
  expression, so the decision can be turned off and measured. Production must
  never set it False.

**Option B is closed, with evidence.** `check_contract_cost.py` says nobody at
the reference shop is below their minimum with owner-first on or off, and 18
placements across 12 people would move if it were switched off. Do not build
the look-ahead. If a second shop complains, re-run that script first — the
answer is a fact about Top Oil's rota, not about the algorithm, and §10b's
constants were calibrated on the same rota.

**Hour-rounding: closed at the solver, open at the model.** The solver no
longer manufactures half-hour edges — off-hour finishes 11.2% → 1.1%,
over-counted hours 25/week → 12.75 against the manager’s own 12. Making
`hours_covered` strict (option A) is the only remaining source and would
re-base learning and solving together. See CLAUDE.md §7d.

**Two features built and deleted, on stated criteria.** `_swap_to_unlock` (fill
an empty day by freeing somebody from an earlier shift) and `_hours_need` (an
hours-distribution term in the rank tuple). Both worked, both were tested, both
changed nothing measurable. See §4. Do not rebuild either without new evidence
— and if a second shop reports "somebody could have covered that day", start by
running `find_corrupt_weeks.py`, because that is what the first report turned
out to be.

**The third attempt at hours distribution was KEPT** — see below. The pattern
across all three is the lesson: two local mechanisms aimed at a global
property did nothing at all, and the one that worked reads every person's
weekly total and moves shifts between them.

**The hours-distribution question is now ANSWERED — third attempt, kept.**
`_rebalance_hours` (CLAUDE.md §2f) runs after the fill and moves unowned
shifts from people above their usual week to people below it. Total distance
from usual 68.4h → 50.6h; worst case −15.8h → −8.8h; nobody left above their
usual. The COUNT of people more than 2h off did not move, which was the bar I
set, and I caught myself arguing past it — so the keep/delete call went to
him and he said keep.

Three things that only worked on the third try, and are the transferable part:

- **The target must be a WINDOW, not a decayed average.** An average lags
  anybody whose hours are changing, which is precisely who a fair share-out
  is for. He spotted this: *"maybe in the last few weeks jane is working 30
  to 34 hours a week."* She was, and my figure said 28.5.
- **The mechanism must be GLOBAL.** Two attempts inside the per-slot sort
  changed literally nothing. A sort answers "who takes this shift"; the
  target is a property of the whole week.
- **"Strictly fairer" is not enough on its own.** Total distance falling
  permitted stripping 16h off somebody 10h over. Roisín went +9.8 → −6.2
  before the "never push the donor below their own usual" rule existed.

His question *"will our hours be reduced and lost, or will Jane keep her
hours?"* found a guarantee nobody had written down: the pass MOVES work and
never deletes it. Now three tests.

**The earlier record of this, for context.**
On the 25-person shop, hourly staff come out spread around what they normally
work — Jane 13h against 28.8h, Roisín 31h against 21.2h — while the week is the
right size (+2%) and every displacement of an owner is lawful. Three ways to
address it, none built:

1. **Report it, do not solve it** — show "Jane 13h, usually 28.8h" beside the
   roster. No solver change, cannot produce a wrong roster.
2. **A balancing pass after the fill**, moving unowned shifts from people above
   their aim to people below. Global, so it CAN work — but it is the swap
   pass's shape, and that earned nothing.
3. **Replace greedy per-slot assignment with real matching.** Correct, and a
   rewrite of the solver's core.

**Measure whether it is a problem first.** "Aim" is a construct I invented and
never validated against what the manager actually corrects. `measure_edit_
burden.py` answers it from real corrections. If managers approve these weeks
untouched, the misallocation is mine, not theirs.

**New diagnostics, all shop-agnostic:**

- `why_empty.py` — why nobody could be placed on a day, in the solver's own
  words, including the silent rejections `_is_eligible` never states and the
  leave cases that never reach it at all
- `check_hours_vs_history.py` — recency-weighted usual hours vs generated,
  split salaried/hourly, bounded by availability and booked leave, with
  suspected leavers separated and a "is the week the right SIZE" verdict that
  distinguishes a demand problem from a distribution one
- `check_why_these_shifts.py` — owned vs tie-break hours, and whether any owner
  lost a slot without a lawful reason
- `find_corrupt_weeks.py` — approved weeks that cannot physically have
  happened; unapproves rather than deletes, dry run by default

**Two real faults found, neither fixed:**

- **Leavers stay active.** Six at Top Oil, gone 10–28 weeks, still holding
  ownership claims and still considered for every shift. `is_active` handles
  them correctly the moment somebody sets it; nothing ever prompts the manager.
  Small feature, affects every shop that has ever lost staff.
- **A corrupt import week survived in the data.** The multi-week parser was
  fixed, but the bad week it had already written stayed approved, and
  `demand.py` believed the shop ran four times the staff it does. Everything
  measured on that shop was wrong until it was unapproved. There is no guard.

Still outstanding: **Phase 5** (re-run `measure_edit_burden.py` and prove the
numbers moved). That is the only honest verdict on the whole session, and it
needs several more approved weeks before it can be run.

**Never seen in a browser, by me:** the printed rota and its page-count
chooser, force approval with red breach names, Add extra, the rebalance-day
links, the What It Learned page, the "Against the usual" panel, and the swap
drag. All are logic-verified and none is eye-verified. He has said he will look
"when everything is done" — offer to drive Chrome through them rather than
letting him find the broken one.

---

## 7. Still parked, by his choice

- **Billing / paywall** — disabled in two places that can disagree
- **Docker, CI, rate limiting, error tracking, backups, GDPR paperwork** (DPA,
  data export and delete). He will write the privacy policy himself before
  hosting.

**Resend email is DONE** — verified domain, dispatch working, roster PDF
attached, boss recipients configured. Remove it from any "parked" list.

He said "not now" to billing. On the §13 list generally: *"Leave this out."*
Do not re-raise unprompted more than once. When he asked what §13 was, the
honest answer was that it — not the solver — is what stands between this and a
paying customer, and that remains true.

**Also parked, from this session:**

- The three hours-distribution options above. He asked *"do I have to do these
  changes for my product to work?"* and the answer is no: the roster is legal,
  fully covered, respects settled shifts, honours contracts, and is within 2%
  of a normal week.
- `strict_days_off` as a per-shop setting. He chose it, I never built it. The
  field exists in `models.py` and the check at `scheduler.py:959` is already
  correct — the work is only the settings API and UI, default staying `True`.
  Worth knowing: because it defaults True everywhere, `relax_preferences`
  currently cannot reach the day-off check at all, so that branch is dead in
  practice despite the comment describing it as live.

---

## 8. The arrivals model, and two ways the measurement lied

The fix itself is in `CLAUDE.md` §7a. What belongs here is how nearly it went
wrong twice, in the same session, in the same way.

### The design mistake: a parallel fill instead of a different slot list

The first attempt wrote `_staff_by_arrivals` and `_place_one_arrival` beside
`_staff_by_slots` — a second fill path with its own ranking. It broke about
forty tests, because `_staff_by_slots` does seven things that had to be
reimplemented and were not: pins cancelling a slot, owner reservation across
the day, seeded variation (§2c), extras consuming nothing, `only_day`
narrowing, duplicate-day prevention, gap reporting.

The right change was **one line**: `_staff_by_slots` already matches pins on
START time, so arrivals only had to change where the slot list comes from.
`slots = self._slots_for_day(day)` instead of `self.demand.slots_for(day)`,
and everything downstream was already correct. Estimated at three times the
effort it needed, and the reason was not reading `_staff_by_slots` before
starting.

> **Before writing a second version of a pass, read the first one to the end.**
> Most of what looks like new behaviour is a different input to old behaviour.

### The measurement mistake, twice, both times a population that could not answer

**Once for the fixtures.** Five tests were written for the arrivals model and
all five passed with `USE_ARRIVALS = False`. Every one was vacuous: the
fixtures were small, tidy shops where the shape list happens to be right.
Reasoning about *when* it would be wrong also failed — a prediction about the
apportionment tie-break was wrong because recency weighting breaks the ties.
What worked was **searching**: 400 randomised fragmented shops, of which the
shape list gets 189 wrong, then freezing two as fixtures — one that starts
four openers where three open, one that starts **none** where two open.

**Once for a deletion.** The per-hour apportionment was measured over 120
randomised shops, changed the roster in **zero** of them, and was deleted on
that evidence, with a comment explaining why. Two existing tests failed
immediately. The 120 shops all had one structure — a pool of people who all
work all of an hour's shapes — which is precisely the case where
`_usual_finish` falls back to the shop's commonest finish and the placeholder
cannot matter. The fixture that catches it is a slot **shared by four people
who each work only that shape**, and `test_slot_scheduling` already had one.

Both are the same fault as the five before them, recorded in §2 above:
**arithmetic verified on a population incapable of giving a different answer.**
Randomising one dimension is not a general population. The question to ask is
not "did I test enough cases" but **"what structure would make this matter, and
is it in my sample at all"**.

### What the sabotage sweep is for

Every mechanism was switched off in turn and the suite re-run:

| sabotage | tests that fail |
|---|---|
| `USE_ARRIVALS = False` | 4 |
| collapse the hour onto its commonest shape | 2 (in `test_slot_scheduling`) |
| the slot's finish wins, not the person's | 2 |
| presence does not cap arrivals | 1 |
| the coverage floor obeys the cap | 1 |

Three of the five caught nothing on the first pass. A test that passes with
the fix removed is not a weak test, it is an absent one — and it is
indistinguishable from a real one until sabotaged.

### Still owed

`ml/check_arrivals_ab.py` has not been run against the real shop, because the
sandbox has no MongoDB. Until it has, the honest statement is that the model
is right in principle and green in tests, and **nobody has yet checked whether
it reproduces the manager better or worse**. The bar was fixed before the
model was built and the script applies that bar rather than a new one:

> arrivals difference falls substantially AND exact matches do not drop. If
> matches fall, revert — a model that is theoretically right and reproduces
> the manager worse is not an improvement.

Baselines to beat: arrivals difference **23.1 people-starts**, exact matches
**14** of the ~56 shifts the solver actually chooses (Megan's, John's and
Kelvin's fixed shifts excluded — the solver did not decide those).

### The verdict came back: worse, and worse in an informative way

31 approved weeks, each solved both ways and held out of its own history:

| | exact matches | arrivals distance |
|---|---|---|
| shape list | **702** | **870** |
| arrivals | 641 | 877 |

Reverted, per the bar, the same day it was measured. `USE_ARRIVALS = False`.

**The exact-match drop is not the interesting number.** The interesting one
is that the arrivals distance DID NOT FALL. That distance is the single
quantity the model exists to fit, and it is fitted *by construction* — the
day is built by asking how many people start each hour and placing that many.
It should have collapsed. It moved by 0.8%, in the wrong direction.

A model that cannot move its own objective on real data is not a model that
is merely unready. Either the fill is not placing what the profile learned,
or a later pass is undoing it. Both are bugs, not judgements about the model.

None of it is visible synthetically: 200 randomised shops agree exactly on
the day's total, and the presence cap does not fire in a reproduction of Top
Oil's own night-shift overlap. **Four weeks came out byte-identical under both
models**, which means arrivals was not active for them at all — worth
explaining before anything else.

`--explain WEEK` was added to print the chain the number travels along —
learned, placed, and what the manager wrote, hour by hour. `learned` vs
`placed` decides it: agreeing means the model genuinely suits this shop worse
and the matter is closed; disagreeing means a bug upstream of the model.

**The discipline that held:** the bar was written down before the model was
built, in the script, so the number could not be re-argued after the fact.
It said revert on exactly this result, and it was applied without
negotiation. Two days of work is not a reason to move a threshold.

### `--explain` found it, and found something else underneath

Eleven hours where the fill placed a different number from the one it
learned. Three were not losses at all — a start pulled an hour earlier, which
is the manager's own *"why can't he call somebody an hour earlier"* working
as intended. The other eight were real, about five a week, which is the ~155
shifts across 31 weeks that the A/B saw.

**The presence cap fired at five of them.** Monday 07:00, Tuesday 10:00,
Thursday 14:00, Friday 13:00, Saturday 18:00 — every one a shift he writes
every week.

The cap was `on_duty >= required`, the literal reading of his rule, and it
compared two different quantities. `required` is a rounded average of BODIES
PRESENT; `on_duty` at 07:00 includes everybody who started at 06:00 and has
not gone home. **That is the changeover double-count that killed the presence
model, reintroduced by the guard meant to protect the model that fixed it.**
Now `>`, which over 80 randomised shops falls from 331 firings in 4102 slots
to 17.

The remaining three losses are not the model's: Tuesday 13:00 was everybody
either left or already working, Saturday 08:00 an 8.5h rest gap against a 10h
rule, Sunday 16:00 seven people unfamiliar with the start. The shape list
places nothing at Friday 13:00 or Sunday 16:00 either.

**The thing worth remembering is what the wrong threshold was hiding.** A
test written the day before — "the solver does not invent a start the shop
has never used" — started failing the moment the cap was corrected. It turned
out `_close_short_hours` pulls a start back to `hour:00` to close a
changeover gap without asking whether the shop has ever started anybody then,
and **the shape list produces the identical `sun 05:00`**. A pre-existing bug
in both models, invisible because an over-eager guard was suppressing its
symptom, and credited to the guard by a test written the same day.

Two lessons, and the second is the uncomfortable one:

- a test that passes for a reason you have not verified is not a passing
  test, it is a coincidence you have not noticed yet
- **fixing a threshold can reveal bugs, and that is the fix working.** The
  temptation on seeing that test go red was to put the `>=` back. That would
  have restored a wrong threshold to keep a real bug hidden.

It is now `xfail(strict=True)`, so it fails loudly if somebody fixes
`_close_short_hours` and forgets to remove the marker. Not fixed in the same
change, deliberately: the A/B has to measure one thing at a time.

### The cap fix worked, and then the sixth measurement error appeared

After it: exact 641 → 679, arrivals distance 877 → 856. Still 23 behind the
shape list on 2175 shifts, so arrivals stays off — the bar was applied
without renegotiation for the second time.

Adding a shifts-produced column killed two live hypotheses at once. Both
models produce **exactly 2001 shifts, identical every week**, so "arrivals
builds a smaller week" was wrong. And both were 174 short of the manager.

I read that as a shared bug worth chasing — "four broken weeks, 148 shifts,
a bigger prize than arrivals" — and said so before checking. It was wrong,
and it was **the same error as the five before it: a population that could
not answer the question.**

`demand.py` line 279: `if age < 0: continue`, a week after the target is not
evidence of anything yet. So for the earliest approved week every other week
is in the future, the profile has nothing to read, it falls below
`MIN_WEEKS_FOR_DEMAND` and drops to generic block coverage. Jan 26 has one
prior week, Feb 02 two, Feb 09 three — and Feb 16, the first with four, is
**exactly** where the output jumps from 33 shifts to 70.

Nothing was broken. The solver cannot learn a shop's patterns from weeks
that have not happened, and should not pretend to.

The fault was in the A/B: the holdout guard was `len(history) >= 4`, which
counted every OTHER week including the thirty in the future. **Holding a
week out is not the same as only showing the model its past.** Fixed to
count weeks strictly before the target; the four are now skipped and named,
with the reason.

What it cost: 198 of 856 arrivals distance, 23% of the score, from weeks
where both models ran the same fallback and the comparison learned nothing.
The verdict does not change — arrivals is still 23 exact behind — which is
the only reassuring part.

Two things to carry forward:

- **A holdout has a direction.** Time-ordered data needs a past, not merely
  a gap. Any future A/B in `ml/` should be checked for this before it is
  believed; `check_arrivals_ab.py` had it wrong from the first line it ran.
- **Say "I have not checked this yet".** The 148-shift claim was stated as a
  finding and put to the shop owner as a recommendation before a single line
  of code had been read. It took four minutes to disprove afterwards.

STILL UNVERIFIED, because the sandbox lost shell access mid-change: the
holdout fix compiles-clean and the test suite passes. Both need running
before the next A/B is believed.
