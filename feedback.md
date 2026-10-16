# Working with Aneesh on Roster - feedback for future sessions

Compiled at the end of a long build. Everything here is a correction he made,
a preference he stated, or a mistake I made and should not repeat.

Read this alongside `CLAUDE.md`. That file is about the *product*; this one is
about *how to work*.

---

## 1. How he wants to work

**Plan before coding. Always.** Stated early and repeated: *"Never jump
directly into coding"*, *"Before we start coding, we will go step by step."*
Explain the approach, get agreement, then build. He will say "yes please" when
ready - that is the signal, not silence.

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
something broke - the mechanism, not the symptom - the conversation moved
faster. When I gave a conclusion without the chain, he asked for it.

**Currency is euros.** He corrected a `$` in the UI. Irish shop.

**Every requested product change updates this file.** Record the reported
behaviour, the diagnostic evidence, the agreed rule, the implementation and
the regression/sabotage result. Do not leave the next session to reconstruct
why a guard or threshold exists from code alone.

---

## 2. Corrections he made - and what I had wrong

**Overnight hours belong to the day the shift starts.**
I proposed a "scarcest hours first" fix for uncovered Sundays. He overruled me:
the real issue was that a Sunday night shift covers into Monday. He was right
and my fix would have been wrong. *Lesson: when he contradicts a diagnosis, he
is usually reasoning from the real shop and I am reasoning from the code.*

**Familiarity must block, not warn.**
I had it as a soft warning. *"These are not rules - if a person hasn't worked
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

**"Have we built this or not?" - check the code, because twice it was "yes".**
He asked whether the app suggests a fixed shift when he keeps making the same
edit. It does: `corrections.py` → `/reports/corrections` → the What It Learned
page, 28 tests. He then asked whether pressing Agree sets it up automatically
or sends him to the employee page. It sets it up: `apply_suggestion` writes the
fixed shift or updates the employee record itself. Answering either from memory
would have had me rebuild working code. *Read the route before answering a
"does it do X" question.* The only thing actually wrong was the wording - the
suggestion said the setting lands "on their employee record where you can
change it back", which reads as an instruction to go and do it yourself.

**He collapses my design forks by reasoning about the manager.** I split his
request into A (suggest a fixed shift) and B (fix the learned demand shape) and
asked which. *"Option A. Because if the manager decides to put that change as a
fixed shift, there is no need for option B."* He is right that A covers the
case he has; the residue B would have handled - the shape still being wrong for
whoever covers when that person is off - is real but hypothetical, and by his
own §10b rule it waits for evidence.

**When my explanation is too abstract he says so, and the fix is his own shop.**
*"I did not understand this. Can you explain it to me like a ten-year-old?"*
came after a paragraph about double-counting and demand profiles. Rewriting it
as "twenty-four weeks, twenty-four votes, your change is one vote" landed
immediately. *Explain in shifts and weeks, not in weights and windows.*

**He expects the obvious thing, not a refusal.** On dragging a shift onto an
occupied cell: *"I want those two shifts to be exchanged."* The app said "that
slot already has a shift", which is true and useless - two people trading
shifts is the commonest reason to drag at all. Same instinct as §4b: refusing
is rarely the right answer to a manager who knows what they want.

**He knows his staff, and that beats my model every time.** In one session he
corrected four of my "findings" out of existence with facts the app already
held but was not using:

| I reported | He said | Where the app already knew |
|---|---|---|
| Teja 56.6h/week | - | duplicate week; `latest_per_week` |
| Everyone under their hours | six of them left months ago | `is_active` |
| Aneesh under by 8.8h | *"he changed his availability to Saturday and Sunday only… he might end up getting 16 or 17 hours. That's okay, that's how it works."* | availability rules |
| Emma and Jamie badly under | *"Emma was on holiday and Jamie was also on holiday"* | the holidays collection |
| Megan and John stealing each other's shifts | *"both of them work 6 to 4"* | `SlotHistory`'s own docstring |
| Emma stealing John's Friday 06:00 | *"Emma usually works on Friday at 6 a.m."* | same |

**Ask him before building.** Each of those was a question he could answer in
one line and I could not answer at all. A shortfall and a resignation are
indistinguishable from inside the data.

**"Top Oil data is not the universal data" - he has now said this three
times.** Once about the importer, once mid-session unprompted, and once more
after I proposed a fix. Every time he was right and every time it was because I
had started designing from one shop's symptom. The swap pass was built from a
gap that a corrupt import invented; deleting it was the direct consequence of
taking him seriously. **Treat the reference shop as a fixture that can be
wrong, not as the specification** (CLAUDE.md §9b, §10b).

**He asks the deflating question at exactly the right moment.** *"Do I have to
do these changes for my product to work?"* after I had laid out three
increasingly large options. The answer was no, and I should have led with it.
He also asked *"do I need AI because it decides whether it can swap or no?"* -
which correctly identified that I was reaching for machinery where arithmetic
would do. **When he asks whether something is necessary, he has usually already
noticed it is not.**

---

## 3. My recurring failure modes

**I diagnose from the symptom instead of the data.**
The worst instance: 66 uncovered hours. I confidently blamed the familiarity
rule, wrote several paragraphs of mechanism, and was completely wrong - he had
two employees and needed 109 hours of cover. The diagnostic output showed
`weeks learned: 0`, which killed my theory instantly.
**Fix: ask for the diagnostic output BEFORE explaining. One command beats four
paragraphs of plausible reasoning.**

**I assume schema and API shapes instead of checking.**
- Assumed `users.shop_id`; the link is actually `shops.owner_id → users.user_id`
- Assumed `read_xlsx` takes bytes; it takes a path
- Assumed `hours_by_day` returned a tuple; it returns a dict
- Wrote a test CSV with the wrong column layout for the parser
Each cost a round trip. **Grep the definition first - it takes seconds.**

**My arithmetic in tests has been wrong more than once.**
Wrote "87h vs 85h" when the numbers gave 82.5. Chasing that error did find a
better test, but I should verify the maths before writing the assertion.

**I write ambiguous status messages.**
`"Checked 0 employee(s)"` was equally true of a healthy shop and a mistyped
shop id - exactly when you need to tell them apart. Also wrote a genuinely
garbled comment in `models.py` about `min_rest_hours` that had to be rewritten.
**Read messages back as if you did not know the answer.**

**I introduce regressions in adjacent code.**
Made the calendar icon invisible with `filter: invert(1)` plus
`color-scheme: dark` - black on black. Left dead scaffolding (`if False else
None`) in a test. **Check the thing next to what you changed.**

**A rename is not a safe refactor, and I keep treating it as one.**
Renaming `was`/`now` to `was_start`/`now_start` in `_suggest_from` broke two
things at once: the block below still referenced the old names, and the guard
`if now <= was: return None` went with them. The second was the dangerous one -
without it the availability branch would have set somebody's earliest start
EARLIER than the one they already had, which is the opposite of what that
setting means and would not have looked wrong in the UI. Caught only because a
test existed for it. **After a rename, grep the old name before running
anything.**

**I nearly overturned a decided question as a side effect of an unrelated one.**
Asked to notice shifts being lengthened, my first version answered *any*
reshape with a fixed shift - which silently reversed
`test_an_earlier_start_suggests_nothing`, where somebody had deliberately
decided that being pulled in early says a person was free all along, not that
anything needs setting. The test failing is what stopped me; without it the
behaviour would have changed with no one noticing. **When a new branch widens
a condition, list what used to fall through it and check each was not a
decision.**

**I wrote an unverified claim into a comment again.** Same failure as the
`_apply_fixed_shifts` one below, one session later. I justified keying the swap
on `(employee, day)` by writing that matching on `shift_id` "would move every
shift at once" - true of that line in isolation, but the server stamps a
`shift_id` on every path that creates a shift, so it never happens. Checked
before committing and rewrote it to give the real reason (consistency with the
validator and `diff_roster`). **A comment that explains a choice by naming a
bug is asserting the bug exists. Verify it or do not name it.**

**I have stated things about his own app that were false.**
Told him no password reset flow existed when `ForgotPasswordReq` and
`ResetPasswordReq` were right there. Described the Supabase design register as
dark when it is white - and he picked a palette based on that, then had to
reject it. **Verify before describing, especially when he will act on it.**

**I used the wrong email.** Used his Claude account address in a script
instruction when his app login is different. Small, but it wasted a run.

**I write regression tests that pass without the fix.** Three times in one
session. Each looked green and proved nothing:

- The owner-reservation test gave the early slot's history only to its owner,
  so the second person was never a contender for it
- The "Regenerate actually varies" test matched on start time alone, and
  Monday runs TWO shifts starting 16:00 - it collected two names whatever the
  code did
- The Rebalance Day tests passed with the freeze disabled, because when every
  other day is fully locked, re-solving them changes nothing anyway

**Fix, and it is cheap: break the fix deliberately and re-run before moving
on.** `cp file /tmp/bak`, disable the branch, run the test, restore. If it
still passes, the test is decoration. This caught all three.

**I claim work is finished when it is not.** Said "everything in the queue is
done" with Phases 2–5 of the corrections work outstanding. He said *"nope,
everything in the queue is not done"*. **Before saying done, re-read the list
rather than recalling it** - the doc was right there.

**I infer intent from data when I should record it.** The setup checklist
worked out whether pay and age had been reviewed by comparing them to the
importer's defaults. It cannot tell a placeholder from somebody who genuinely
is 25 on that rate working 40 hours - their step could never be completed.
**"Has a human looked at this?" is provenance, not a property of the values.**
Same distinction as §5 of CLAUDE.md, from the other side: derive state where
you can, but a DECISION has to be recorded.

**I write a diagnosis into a comment before I have tested it.** The worst
instance this session: two people showed 60h against a 40h contract. I decided
`_apply_fixed_shifts` was placing them twice after a Rebalance Day, added a
guard, and wrote a comment stating that as the cause - then tested it and
found no duplicates at all, through the solver OR the route. The duplicates
were real in his data; my explanation was invented.

**A comment is a claim. If it says "this happens because X", X has been
demonstrated.** The guard stayed (nothing should place two shifts for one
person on one day) but its comment now says "defensive, not a fix for a
reproduced bug" - which is the truth and is still useful to the next reader.

**When the cause will not come out, move the check to the boundary.** I could
not find which pass created the duplicates. Rather than keep guessing I
asserted the invariant once at the end of `solve()` - remove the extra, undo
its accounting, and REPORT it by name. Cheaper than auditing five passes,
holds against a sixth, and the report will name the pass next time. That is a
better outcome than a lucky guess would have been.

**I keep blaming the environment before the code.** "Restart the backend",
"stale module", "warm --reload" - three times, and each time the app was
current and the cause was in the logic. He restarted everything twice on my
say-so. **Build the check instead of guessing** (`ml/check_live_code.py` now
answers it in one command).

**I check that the arithmetic is right without checking that the POPULATION
can give an honest answer.** This is the single most expensive habit I have,
and it cost most of one session in four separate forms:

- **Duplicate weeks.** Reported Teja averaging 56.6h - above his 40h cap and
  above the 48h legal limit. A week with two approved rosters had both counted.
  `demand.py`, `slot_owners.py`, `corrections.py` and `learning.py` all dedupe
  through `latest_per_week`; my diagnostic did not.
- **Leakage.** Solved an already-approved week to grade the solver against it.
  `_weighted_weeks` skips only `age < 0`, so the target week itself carries
  full weight - I asked it to reproduce something it had memorised and took
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
what would make the population unable to produce one.** Implausible outputs -
56.6h, a perfect score, eight simultaneous bugs - are almost always the
measurement, not the system.

**A test that a value is non-zero is not a test that it DISCRIMINATES.** I
built an hours-need ranking term, wrote nine passing tests, and it changed not
one hour of the roster. `hours_aim` was populated, `_hours_need` returned a
plausible negative number, everything was green - and it returned the SAME
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
serious class of bug this product can have. The data was fine - every query
filters on `shop_id` - but the presentation was not. **Two shops in one
session means every number carries its shop's name.**

---

## 4. What worked - keep doing

**Set the keep/delete criterion BEFORE running the measurement, then honour
it.** Twice in one session this deleted work I had just finished:

- **The swap pass** (338 lines, 26 tests, all green) - built to fill a Friday
  that came out empty. The criterion was "keep only if uncovered hours fall".
  Once a corrupt import week was unapproved, the gap disappeared and the pass
  never fired on any week. Deleted.
- **The hours-need ranking term** - built to even out hourly staff. The
  criterion was "keep only if fewer than 11 of 18 are off their aim". It
  changed not one hour, twice, for two different reasons. Deleted.

Neither deletion was a wasted session: the swap pass work found the corrupt
week, and the hours work produced four diagnostics and the structural insight
that a per-slot sort cannot fix a whole-week property. **Stating the bar first
is what makes it possible to walk away from something that already works and
looks reasonable.** Writing it down after the fact never survives contact with
having built the thing.

**Sabotage every test, including the ones that pass.** Three of four sabotages
failed correctly; the fourth - the guard against repeating the
`scheduler.py:1738` bug - stayed green when I deliberately moved the term up
the sort. It used an OWNED slot, where rank 0 wins regardless, so it could
never have caught the thing it was named after. The replacement uses a slot at
58% ownership, just under the bar, where the ordering actually decides.
**A test named after a bug is not a test for that bug until you have seen it
fail.**

**Build the diagnostic instead of theorising.** The Emma question went through
four wrong explanations from me - stale code, ownership ranking, apportionment -
before `explain_day.py` showed the actual arithmetic. Every one of those
guesses cost a round trip; the tool ended it. `ml/` now holds around nine of
them - `check_hours`, `check_contract_cost`, `check_live_code`,
`check_rest_gaps`, `diagnose`, `explain_day`, `show_roster`, `why_slot`,
`who_is_placeholder` - alongside the migrations, and they are the
highest-value thing built across these sessions. **Look for an existing one
before writing a fresh query.**

**Separate the layers before debugging.** "Emma is missing" had two completely
different possible causes that look identical on screen: the slot is not in
the day's plan at all, or it is and somebody outranked her. No amount of
tuning who-beats-whom helps with the first. Ask which layer before designing.

**A/B the rule instead of reading the symptom.** The question "did owner-first
starve a full-timer?" cannot be answered by looking at `under_contract` - a
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
2. hour-rounding against the manager's **approved** rota - hand-built, 24h,
   continuous by construction, so no hole was possible. He spotted that one:
   *"this is the output from the last 24 weeks, which are made by my manager,
   not from the solver"*
3. the same check counting only hours where the shop is **completely empty**,
   when the actual question was headcount shortfall - a 17:30 start credited
   with 17:00 leaves nobody missing, just one fewer than needed
4. reporting "PASS - only Wednesday moved" when *nothing* had moved

Every one had the same shape and the same fix. The habit is not "check the
result", it is **state what a non-zero answer would look like, then confirm the
measurement can produce it.** A detector that has never fired is not evidence.

**Test the measurement on a case with a known answer.** After the third time,
`check_partial_hours` got 13 hand-computed cases - overnight wrap, Sunday night
into Monday, two people overlapping, leave not counting - and later a synthetic
roster with a deliberate hole, to prove the detector fires at all. That is what
made the eventual zero trustworthy.

**A second real file is worth more than another test.** He uploaded his own
month-in-one-tab spreadsheet and it broke the importer three ways at once -
weeks merged, dates lost, roles invented - none of which 60 passing tests had
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
back 42 of 42 manufactured finishes on salaried staff - unambiguous, and worth
the extra round trip because the fix meant overturning a documented rule.

**Say how big the denominator is, or a clean result means nothing.** First
version of that script printed "nobody is below their minimum" - which is
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
pure frontend logic, so it went into a standalone node script - seven cases
including bystanders staying put and, the one that would actually corrupt a
roster, that no swap can put two people in the same `(person, day)` cell from
either drag direction. Not the same as seeing it work, and the commit says so.

**His bug reports are precise, and the numbers in them are the diagnosis.**
"60h but the roster shows 40" plus a dry run listing four duplicate rows was
enough to prove the bug, locate it to one roster out of sixty, and identify
which pass was involved - all before I understood the mechanism. When he
gives a number, do the arithmetic on it: Megan's six shifts of ten stopping
at exactly 60 pointed straight at `max_weekly_hours = 60` being the limiter.

**Say plainly when a refusal is correct.** Twice the app was right and he
thought it was broken - the five-day guard blocking my own test fixture, and
the checklist flagging four genuinely untouched records. Saying "no, this is
correct, and here is why" is more useful than fixing a non-bug. But both times
the MESSAGE deserved the complaint even though the LOGIC did not.

**Measure before designing.** Before making 11-hour rest a constraint, I
checked it against 2009 real shift pairs from his manager's rosters: 99.6%
compliant. That number decided the design. Had it been 70%, a hard block would
have left the solver fighting its own training data. He explicitly liked this
order of operations.

**Use his real roster as ground truth.** `new roster 26.xlsx` settled several
arguments - the familiarity question, the role mapping, the rest rule. When a
design question is really an empirical question, go to the file.

**Say when I was wrong, plainly and early.** He responds well to *"I was
wrong"* followed by the correct answer. No hedging.

**Flag consequences of his own choices.** He chose "block past weeks entirely",
which would have made imported historical rosters permanently unfixable. I
implemented his choice and named the trap; he then asked for the fix. That is
the right pattern - respect the decision, surface the cost.

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
- His role ladder uses abbreviations the sheets spell out - "Ass Manager" vs
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
  can be Babel-parse-checked but NOT build-verified here - say so rather than
  implying the build passed.

---

## 6. Where the product stands

Built this session, all general behaviour with no shop-specific code:

- **Slot ownership** - 60% of the weeks a slot ran, over 4+ weeks. Owner beats
  contract need; owners are reserved from earlier slots; leavers cannot own.
- **Seeded Regenerate** - varies only unowned slots, weighted. Rebalance does
  not seed.
- **Extra staff** and **Rebalance Day**.
- **Corrections learning Phases 2–4** - the falling edit count, suggestions
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
the look-ahead. If a second shop complains, re-run that script first - the
answer is a fact about Top Oil's rota, not about the algorithm, and §10b's
constants were calibrated on the same rota.

**Hour-rounding: closed at the solver, open at the model.** The solver no
longer manufactures half-hour edges - off-hour finishes 11.2% → 1.1%,
over-counted hours 25/week → 12.75 against the manager’s own 12. Making
`hours_covered` strict (option A) is the only remaining source and would
re-base learning and solving together. See CLAUDE.md §7d.

**Two features built and deleted, on stated criteria.** `_swap_to_unlock` (fill
an empty day by freeing somebody from an earlier shift) and `_hours_need` (an
hours-distribution term in the rank tuple). Both worked, both were tested, both
changed nothing measurable. See §4. Do not rebuild either without new evidence -
and if a second shop reports "somebody could have covered that day", start by
running `find_corrupt_weeks.py`, because that is what the first report turned
out to be.

**The third attempt at hours distribution was KEPT** - see below. The pattern
across all three is the lesson: two local mechanisms aimed at a global
property did nothing at all, and the one that worked reads every person's
weekly total and moves shifts between them.

**The hours-distribution question is now ANSWERED - third attempt, kept.**
`_rebalance_hours` (CLAUDE.md §2f) runs after the fill and moves unowned
shifts from people above their usual week to people below it. Total distance
from usual 68.4h → 50.6h; worst case −15.8h → −8.8h; nobody left above their
usual. The COUNT of people more than 2h off did not move, which was the bar I
set, and I caught myself arguing past it - so the keep/delete call went to
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
work - Jane 13h against 28.8h, Roisín 31h against 21.2h - while the week is the
right size (+2%) and every displacement of an owner is lawful. Three ways to
address it, none built:

1. **Report it, do not solve it** - show "Jane 13h, usually 28.8h" beside the
   roster. No solver change, cannot produce a wrong roster.
2. **A balancing pass after the fill**, moving unowned shifts from people above
   their aim to people below. Global, so it CAN work - but it is the swap
   pass's shape, and that earned nothing.
3. **Replace greedy per-slot assignment with real matching.** Correct, and a
   rewrite of the solver's core.

**Measure whether it is a problem first.** "Aim" is a construct I invented and
never validated against what the manager actually corrects. `measure_edit_
burden.py` answers it from real corrections. If managers approve these weeks
untouched, the misallocation is mine, not theirs.

**New diagnostics, all shop-agnostic:**

- `why_empty.py` - why nobody could be placed on a day, in the solver's own
  words, including the silent rejections `_is_eligible` never states and the
  leave cases that never reach it at all
- `check_hours_vs_history.py` - recency-weighted usual hours vs generated,
  split salaried/hourly, bounded by availability and booked leave, with
  suspected leavers separated and a "is the week the right SIZE" verdict that
  distinguishes a demand problem from a distribution one
- `check_why_these_shifts.py` - owned vs tie-break hours, and whether any owner
  lost a slot without a lawful reason
- `find_corrupt_weeks.py` - approved weeks that cannot physically have
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
"when everything is done" - offer to drive Chrome through them rather than
letting him find the broken one.

---

## 7. Still parked, by his choice

- **Billing / paywall** - disabled in two places that can disagree
- **Docker, CI, rate limiting, error tracking, backups, GDPR paperwork** (DPA,
  data export and delete). He will write the privacy policy himself before
  hosting.

**Resend email is DONE** - verified domain, dispatch working, roster PDF
attached, boss recipients configured. Remove it from any "parked" list.

He said "not now" to billing. On the §13 list generally: *"Leave this out."*
Do not re-raise unprompted more than once. When he asked what §13 was, the
honest answer was that it - not the solver - is what stands between this and a
paying customer, and that remains true.

**Also parked, from this session:**

- The three hours-distribution options above. He asked *"do I have to do these
  changes for my product to work?"* and the answer is no: the roster is legal,
  fully covered, respects settled shifts, honours contracts, and is within 2%
  of a normal week.
- `strict_days_off` as a per-shop setting. He chose it, I never built it. The
  field exists in `models.py` and the check at `scheduler.py:959` is already
  correct - the work is only the settings API and UI, default staying `True`.
  Worth knowing: because it defaults True everywhere, `relax_preferences`
  currently cannot reach the day-off check at all, so that branch is dead in
  practice despite the comment describing it as live.

---

## 8. The arrivals model, and two ways the measurement lied

The fix itself is in `CLAUDE.md` §7a. What belongs here is how nearly it went
wrong twice, in the same session, in the same way.

### The design mistake: a parallel fill instead of a different slot list

The first attempt wrote `_staff_by_arrivals` and `_place_one_arrival` beside
`_staff_by_slots` - a second fill path with its own ranking. It broke about
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
Reasoning about *when* it would be wrong also failed - a prediction about the
apportionment tie-break was wrong because recency weighting breaks the ties.
What worked was **searching**: 400 randomised fragmented shops, of which the
shape list gets 189 wrong, then freezing two as fixtures - one that starts
four openers where three open, one that starts **none** where two open.

**Once for a deletion.** The per-hour apportionment was measured over 120
randomised shops, changed the roster in **zero** of them, and was deleted on
that evidence, with a comment explaining why. Two existing tests failed
immediately. The 120 shops all had one structure - a pool of people who all
work all of an hour's shapes - which is precisely the case where
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
the fix removed is not a weak test, it is an absent one - and it is
indistinguishable from a real one until sabotaged.

### Still owed

`ml/check_arrivals_ab.py` has not been run against the real shop, because the
sandbox has no MongoDB. Until it has, the honest statement is that the model
is right in principle and green in tests, and **nobody has yet checked whether
it reproduces the manager better or worse**. The bar was fixed before the
model was built and the script applies that bar rather than a new one:

> arrivals difference falls substantially AND exact matches do not drop. If
> matches fall, revert - a model that is theoretically right and reproduces
> the manager worse is not an improvement.

Baselines to beat: arrivals difference **23.1 people-starts**, exact matches
**14** of the ~56 shifts the solver actually chooses (Megan's, John's and
Kelvin's fixed shifts excluded - the solver did not decide those).

### The verdict came back: worse, and worse in an informative way

31 approved weeks, each solved both ways and held out of its own history:

| | exact matches | arrivals distance |
|---|---|---|
| shape list | **702** | **870** |
| arrivals | 641 | 877 |

Reverted, per the bar, the same day it was measured. `USE_ARRIVALS = False`.

**The exact-match drop is not the interesting number.** The interesting one
is that the arrivals distance DID NOT FALL. That distance is the single
quantity the model exists to fit, and it is fitted *by construction* - the
day is built by asking how many people start each hour and placing that many.
It should have collapsed. It moved by 0.8%, in the wrong direction.

A model that cannot move its own objective on real data is not a model that
is merely unready. Either the fill is not placing what the profile learned,
or a later pass is undoing it. Both are bugs, not judgements about the model.

None of it is visible synthetically: 200 randomised shops agree exactly on
the day's total, and the presence cap does not fire in a reproduction of Top
Oil's own night-shift overlap. **Four weeks came out byte-identical under both
models**, which means arrivals was not active for them at all - worth
explaining before anything else.

`--explain WEEK` was added to print the chain the number travels along -
learned, placed, and what the manager wrote, hour by hour. `learned` vs
`placed` decides it: agreeing means the model genuinely suits this shop worse
and the matter is closed; disagreeing means a bug upstream of the model.

**The discipline that held:** the bar was written down before the model was
built, in the script, so the number could not be re-argued after the fact.
It said revert on exactly this result, and it was applied without
negotiation. Two days of work is not a reason to move a threshold.

### `--explain` found it, and found something else underneath

Eleven hours where the fill placed a different number from the one it
learned. Three were not losses at all - a start pulled an hour earlier, which
is the manager's own *"why can't he call somebody an hour earlier"* working
as intended. The other eight were real, about five a week, which is the ~155
shifts across 31 weeks that the A/B saw.

**The presence cap fired at five of them.** Monday 07:00, Tuesday 10:00,
Thursday 14:00, Friday 13:00, Saturday 18:00 - every one a shift he writes
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
test written the day before - "the solver does not invent a start the shop
has never used" - started failing the moment the cap was corrected. It turned
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
shape list on 2175 shifts, so arrivals stays off - the bar was applied
without renegotiation for the second time.

Adding a shifts-produced column killed two live hypotheses at once. Both
models produce **exactly 2001 shifts, identical every week**, so "arrivals
builds a smaller week" was wrong. And both were 174 short of the manager.

I read that as a shared bug worth chasing - "four broken weeks, 148 shifts,
a bigger prize than arrivals" - and said so before checking. It was wrong,
and it was **the same error as the five before it: a population that could
not answer the question.**

`demand.py` line 279: `if age < 0: continue`, a week after the target is not
evidence of anything yet. So for the earliest approved week every other week
is in the future, the profile has nothing to read, it falls below
`MIN_WEEKS_FOR_DEMAND` and drops to generic block coverage. Jan 26 has one
prior week, Feb 02 two, Feb 09 three - and Feb 16, the first with four, is
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
The verdict does not change - arrivals is still 23 exact behind - which is
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

---

## 9. No-history and partial-history generation

Three reports that looked related had different causes. They were reproduced
separately before any fix was written.

**Zero history, after closing.** Plain opening-hour blocks stopped at 22:00.
Two later paths crossed it:

- `profile_from_shop_hours` accepted a configured `14:00-23:00` template with
  zero approved weeks, and `_ensure_supervisory_cover` placed it directly.
- `_fit_contract_hours` extended a generated `14:00-22:00` closing shift to
  `23:00` to put a full-timer inside their contract band. It checked the shift
  cap, curfew and rest, but never checked the shop's close.

The rule is now exact: generated work stops at close unless the same post-close
shape ran in at least four distinct prior approved weeks. This is the same
evidence bar as slot ownership. Fixed and pinned shifts remain the manager's
explicit decision. Legacy `00:00-23:59` shops remain 24-hour shops.

**Learned cleanup on arbitrary minutes.** Four weeks of `22:45-23:45` were
copied unchanged into `day_slots`. `finish_granularity` did not touch them; it
only sizes contract trims and defaults to 60 minutes under fifty shifts.
Supported post-close work is now normalised to half-hour boundaries while
preserving its duration (`22:45-23:45` becomes `22:30-23:30`). Both the current
slot path and the arrivals path consume the same clean shape.

**One prior week became three generic shifts.** The diagnostic showed
`learn_demand` correctly reading one prior Monday, a staff target of seven and
seven slots. `build_profile` then discarded the whole profile because it was
below `MIN_WEEKS_FOR_DEMAND`, returned three generic blocks, and generated
three people. A future roster included in the diagnostic was correctly
excluded, so this was not another `age < 0` fault.

One to three weeks now contribute headcount, role mix and daily staff totals,
but not exact shapes, arrivals or ownership. Generic within-hours blocks remain
the shape vocabulary until week four. This uses the only real volume signal
without treating one week as a settled habit.

**Sabotage evidence:**

| removed | regression that failed |
|---|---|
| post-close template filter | zero-history template test |
| contract-fit closing guard | zero-history contract test |
| half-hour normalisation | four-week cleanup test |
| arrivals normalisation | arrivals variant of the cleanup test |
| four-occurrence evidence bar | three-of-four cleanup test |
| partial-history merge | one-week seven-versus-three test |

After restoring every guard, the focused demand, scheduler and 24-week
reference-shop suites passed. The complete backend suite also exited zero;
the only non-pass was the existing expected xfail, with dependency deprecation
warnings unchanged.

---

## 10. Roster groups are separate learning problems, not separate employers

A client with one shop and two operating areas needed independently named
rosters: Shop Floor and Deli were the example, but the names must belong to
the shop rather than to the code. Some employees work in both areas.

The diagnostic found that `departments` already existed on shops and
employees, but it was only a partial UI filter:

- the importer wrote every employee to `Shop Floor` and treated a calendar
  week as a duplicate across the whole shop
- generation read every approved roster into one demand, ownership,
  familiarity and preference corpus
- independent solves did not know that the same employee was already working
  on the other roster

That partial boundary is worse than having none. It displays two groups while
quietly teaching one from the other and gives a shared employee a fresh hours
budget in each solve.

The rule now has two explicit halves:

- **department-local:** imported weeks, demand, arrival/shape history, slot
  ownership, familiarity, preferences, coverage, roster versions and scoped
  custom AI rules
- **shop-wide:** weekly/seasonal hour caps, paid hours, working days, rest,
  leave and double-booking

Shops create and name their own roster groups. Employees can belong to more
than one. Every import chooses exactly one group, and the same calendar week
may be imported once per group. A manually mapped existing employee gains
membership of that group instead of being duplicated.

When another group already has a shift for a shared employee, its latest
visible roster is passed to the solver as an **external commitment**. That
commitment spends hours and a working day and participates in rest checks, but
never counts as coverage or output for the roster being built. The grid and
print view show the other group's name and times as a read-only cell. A manual
edit or sick-cover choice that tries to put the person in both groups on the
same day is refused with the other group and shift named.

The boundary is also recorded in training evidence: generation stores its
group, only that group's history sources and the external commitments it had
to work around. A future model can therefore learn Deli decisions without
mistaking them for Shop Floor demand while still seeing why a shared employee
was unavailable.

**Regression and sabotage evidence:**

| removed | regression that failed |
|---|---|
| shop-wide external-hour seeding | a shared employee was scheduled in the second group after already using their weekly cap in the first |
| department filter on approved history | a Deli import appeared in Shop Floor's `training_context.history_sources` |

The import regression also proves the same week is accepted once in each
group, and the API edit regression proves an existing other-group shift is
returned to the browser and cannot be overwritten from this roster.

---

## 11. A roster group is a workspace, not a dropdown filter

The first department implementation separated roster history and employee
membership, but left one shop-wide settings document and one job title on the
employee. That still made Deli behave like Shop Floor with a filtered list:
it inherited Shop Floor's opening hours, role ladder and supervisory roles,
and the browser had no durable current-workspace context. Reports could also
mix corrections from both groups even though generation had learned them
separately.

The product boundary is now explicit:

- every request carries the selected roster group; legacy clients with no
  selection continue in the shop's primary group
- each group owns its opening hours, shift limits/templates, role ladder,
  supervisory roles, import aliases and demand settings
- an employee may hold a different role in each group, without becoming two
  employees or receiving two hour balances
- import review offers employees from every group for explicit mapping; a
  mapped person gains the new membership and that group's mapped role instead
  of being duplicated
- employees, holidays, fixed shifts, AI rules, current/past rosters, imports
  and learning reports render inside the selected workspace
- employment and legal facts stay shop-wide: weekly caps, paid hours, working
  days, rest, leave entitlement and double-booking do not reset at a group
  boundary
- only the primary workspace has a Dashboard; it deliberately fetches all
  groups, labels every recent roster with its group, and shows the combined
  shop activity feed

The storage remains one shop document. Group scheduling settings are overlays
under `department_settings`; `ShopScope` exposes the effective selected view.
That keeps tenancy, billing, leave and employment attached to one employer
instead of creating fake shops merely to obtain separate settings.

**Regression and sabotage evidence:**

| removed | regression that failed |
|---|---|
| selected group's settings overlay | Deli lost its own hours and role ladder |
| correction-report group filter | each group's learning report counted both groups' approved weeks |
| import mapping membership update | the mapped employee remained invisible in the new group |

The restored tests also prove holiday-balance lists contain only the current
group's people while the primary activity feed includes actions from both
groups. This distinction is deliberate: the list is a workspace view; the
dashboard is the owner's whole-shop view.

---

## 12. Delivery diagnostics must not repeat the message they failed to send

CodeQL found two high-severity clear-text logging paths in `_send_one`.
Failure handling logged the recipient address together with either the email
provider's raw response body or the raw network exception. A provider may
echo parts of a rejected payload, and exception text may contain request
details, so truncating either to 200 characters did not make it safe. The
disabled password-reset path also logged the account address.

Delivery failures now record only a provider status code or an exception
class. The dispatch result returned to the authenticated caller is sanitised
the same way; recipient addresses, response bodies, exception messages,
subjects, HTML and reset links never enter the diagnostic string.

Regression tests use an address and a private marker deliberately embedded in
provider and exception messages, then assert neither appears in logs or in the
returned error. The password-reset-not-configured path has the same check.
Sabotage reintroduced the recipient argument into the provider-status log and
the regression failed on the exact leaked address before the safe line was
restored.

---

## 13. A correction count is not evidence until its opportunities are counted

The fixed `MIN_REPEATS = 3` trigger in `corrections.suggestions` counted only
the weeks where a manager made a correction. It never counted the comparable
weeks where the generated proposal was accepted unchanged. That made three
corrections out of twelve opportunities look identical to three out of three,
and the UI then inferred refusal from the absence of an offer.

The correction learner now compares each pattern with its real proposal
opportunities in the last twelve approved rosters. Recent approvals receive
more weight, a Wilson lower bound keeps one-offs below the offer bar, and the
manager's applied/dismissed decisions calibrate how cautious later offers are.
Leave remains outside correction evidence. The report returns opportunity
count, correction rate, confidence and explicit applied/dismissed state; no
setting changes until the manager accepts the suggestion.

This is a small deterministic online evidence model over each shop's own
approvals, not an LLM call or a deployed cross-shop ranking model. Its later-
week predictive usefulness remains to be measured as clients create new data.

**Sabotage evidence:** replacing the confidence decision with the former
`count >= 3` rule made
`test_three_corrections_do_not_win_against_five_accepted_proposals` fail: it
offered a day-off setting despite five accepted proposals contradicting those
three corrections. Restoring the evidence decision made the focused learner
and correction-report API suites pass.

---

## 14. Test configuration must override `.env`, not politely defer to it

The backend tests promised an in-memory database and no network, but their
bootstrap used `os.environ.setdefault`. `config.py` then loaded `backend/.env`,
so a developer with real Anthropic or Resend credentials silently enabled
those integrations inside pytest. Every roster generation called Anthropic for
an optional summary. The suite became slow, network-dependent and potentially
billable even though scheduler execution itself was fast.

Profiling disproved the first theory. Replacing the solver with a minimal stub
left the five correction-report API tests at about 130 seconds. Printing only
feature booleans then showed `llm_enabled: true` and `email_enabled: true` in
the test process. The fix is at the shared bootstrap: tests now assign their
database/JWT environment explicitly and blank every external integration key
before importing the app. Production configuration is unchanged.

The health test now requires all test integration flags to be false. Sabotage
removed only the Anthropic override; the test failed with `llm: true` without
making a live request. After restoration, the correction-report class fell
from roughly 130 seconds to 10.6 seconds, and the complete backend suite ran in
about 1 minute 42 seconds instead of roughly 12 minutes in the same session.
All tests passed apart from the existing expected failure.

---

## 15. Destructive confirmations belong to the app, not the browser

Employee deletion called `window.confirm` directly in `Employees.del`, which
produced the browser-owned “localhost says” prompt and bypassed the app's
modal styling. The page already had a reusable `Modal`, so no component library
or new CSS was needed.

Delete now opens an in-app `DeleteEmployeeDialog` with the same warning about
retaining past rosters and preferring Inactive for leavers. Only its explicit
“Remove employee” action calls the existing API deletion. Buttons and backdrop
closing are disabled while removal is in progress, and the shared employee
modal now exposes dialog semantics and labelled close controls.

The regression renders the dialog and also asserts that `Employees.js` contains
no `window.confirm`. Sabotage restored a browser confirmation in `del`; the test
failed on that exact call before the app-only path was restored. Frontend tests
and the production build then passed; the existing `RosterView.js` hook warning
is unchanged.

---

## 16. Verify the served bundle, not just the edited source

The employee app-dialog fix was present locally, but the user's browser still
showed the old native confirmation. Fetching localhost:3000's actual
`/static/js/bundle.js` confirmed it contained a browser Remove confirmation
and did not contain `DeleteEmployeeDialog`. This is evidence of a stale or
different served frontend, not evidence that the local source fix is live.
The settings page also still contained three real `window.confirm` calls:
roster-group, role and recipient removal. Those were missed in the earlier fix.

Settings now uses the installed Radix alert dialog with the existing app styles,
keyboard/focus handling and explicit Cancel/Remove actions. The existing server
checks remain unchanged, and removal still requires Save changes. The regression
clicks group removal, verifies Cancel preserves it, then verifies confirmation
removes it only from the form and makes no save request. Sabotage bypassed the
dialog and removed immediately; the test failed before restoration. All six
frontend tests passed after restoration.

Docker Desktop Start/Stop does not rebuild an image. Live updates require a
source bind mount and a watching development process; code copied into an image
requires rebuilding and recreating the relevant container. No Dockerfile or
Compose configuration was found in this checkout, and Docker CLI was unavailable
in this session. Do not claim the user's containers were rebuilt or live-tested;
first locate their configuration and verify the bundle they actually serve.

---

## 17. One working checkout for VS Code, Codex and Docker

Both the Desktop folder and `C:\Users\anees\Roster` are Git repositories at
the same original commit. Folder naming was not evidence of a ZIP-only checkout.
Docker files existed on `add-docker-setup`, not on the checked-out `main` branch.
The user authorised committing all pending fixes and transferring them through
Git, preserving both copies and the MongoDB backup. The fixes were committed in
Desktop, then cherry-picked onto `working-fixes-docker`, based on the existing
Docker branch, in `C:\Users\anees\Roster`. Nothing was pushed.

**Use `C:\Users\anees\Roster` for subsequent work.** Open that folder in VS Code
and Codex. Do not keep editing Desktop and assume Docker sees it. Docker inspect
confirmed both running services mount this working checkout into `/app`; the
existing frontend polling and backend reload are already configured correctly.
Fetching the served frontend bundle after transfer confirmed both app dialogs
were present, and all six frontend tests passed inside the running container.

The first container backend test failed at setup because `mongomock_motor` was
missing. The API tests already require it and the Desktop venv already had it;
it was absent from requirements. It is now declared alongside pytest so a clean
Docker build can run the same isolated tests. No database migration, backup
deletion, environment-secret copying or new Docker volume is required.

After rebuilding only the backend service, the full backend suite completed
successfully inside Docker with the existing expected failure. Backend health
returned `ok`, both source mounts still pointed at the working checkout, and
MongoDB stayed healthy on its original volume. VS Code was opened on this folder.
The earlier Docker-unavailable finding applied to the sandbox's PATH; the normal
host environment exposes Docker Desktop's CLI. Check the actual host before
concluding the user's installation is missing.

---

## 18. Leavers need an action, not advice buried in a removal prompt

The user wanted the employee removal dialog to match the smaller shop-settings
card in their second screenshot, not the rounded employee-edit modal. They also
wanted a visible inactive action, a separate inactive list and blurred backgrounds
for all delete confirmations. Employee deletion reused its page-specific edit
modal while settings used Radix; other pages still called native confirmations.

The shared `ConfirmDialog` reuses installed Radix and the existing `card elevated`
colours/layout, with a blurred backdrop, focus handling, Cancel and an explicit
destructive action. Employees, settings, AI rules, fixed templates, illness and
imported-history removal now use it. Holiday deletion keeps its existing per-day
controls and matching card while gaining the same blurred backdrop; its backdrop
cannot dismiss while deleting. The shared dialog disables cancellation and repeat
submissions while saving and stays open when a caught API failure returns false.

The employee detail now offers Mark inactive/Reactivate; the removal dialog also
offers Mark inactive instead. These persist the existing shop-wide `is_active`
field, preserving employee details rather than deleting the person. Active filters
exclude leavers and the Inactive section lists them separately. Scheduler guards
already exclude inactive employees; no new scheduler ranking or rule was added.
Already-created rosters remain unchanged, and reactivation makes the employee
eligible again. The change applies across shops and roster groups.

Frontend regressions exercise the inactive update, list separation, reactivation,
alternative removal action, shared card, blur, safe cancellation and duplicate
submit prevention. Sabotage removed the inactive filter and blur: both regressions
failed, then all eight frontend tests passed after restoration. The new isolated
API regression verifies stored inactivity, exclusion from new generated rosters,
retention of old shifts and reactivation; it and the existing availability suite
passed (62 tests). Frontend production compilation passed with only the existing
RosterView effect-dependency warning. Changes are in the Docker-mounted working
checkout, `C:\Users\anees\Roster`, not the Desktop copy.

---

## 19. New employee actions must reuse the existing action typography

The user reported that Mark inactive looked different from Edit, Adjust holiday
and Delete, and asked to maintain the existing style/theme. Its button had only
`esp-act`, which inherits the font family but does not specify the neighbouring
actions' size, weight or colour. Adding the existing `esp-act-2` class applies
the same 14.5px size, 600 weight, theme colour and hover styling to both Mark
inactive and Reactivate. No new CSS, palette or behaviour was introduced.

The employee workflow regression now checks the shared action classes in both
states. It failed before the fix with `esp-act` instead of `esp-act esp-act-2`,
providing the same negative control as removing the fix. All frontend tests
passed after applying the class. Keep new actions in the page's established
style instead of introducing another typography variant.

---

## 20. A shared cloud database requires a verified copy and an explicit Docker switch

The user requested database-only cloud migration, leaving frontend/backend hosting
for later, and authorised pausing Docker writes and copying existing data. Atlas
authentication was verified privately, then the empty target and source population
were checked: 3 accounts, 33 employees, 112 rosters and 458 total documents across
13 collections. Keep existing IDs, password hashes and tenant relationships; do not
re-register accounts or transfer only employee records.

Base Compose hardcodes `MONGO_URL=mongodb://mongo:27017`, overriding backend `.env`.
The opt-in `docker-compose.atlas.yml` resolves `ATLAS_MONGO_URL` from the explicitly
supplied private env file, fails when missing, and disables development reset/seed
routes for shared data. Default local Compose and the original MongoDB volume stay
unchanged. Start/recreate with both files; Desktop stop/start keeps current container
configuration, while a plain Compose recreation can switch back to the old local DB.
The two databases do not synchronise themselves.

Backend writes were paused for the native backup/restore. Docker's restore process
could not access its private credential config even when explicitly run as root;
the installed Windows tool passed a no-write dry run and performed the restore.
The local backend was restarted while diagnosing failed attempts. No local data
was deleted, and Atlas was confirmed empty before retrying. Raw credential-bearing
tool output was suppressed/redacted; the temporary credential config was removed.

Before switching, every copied document/ID and index was checked against the frozen
source manifest, not merely collection counts. A negative control changed only an
in-memory expected account count and correctly failed verification, without altering
either database. The running backend then confirmed Atlas connection, matching core
counts, disabled development reset routes and HTTP 200 health. This is migration
verification, not a claim that the full scheduler suite or a browser login was run.

The sensitive archive remains under ignored `mongo-backup/atlas-transfer/` as a
fallback. Cloud backup scheduling and app hosting are still separate work. Keep
teammate secrets private and isolate experiments from the shared customer database.

---

## 21. Pending roster data is not an empty shop; avoid per-version cloud reads

After the Atlas migration, the roster page said "No employees yet" while the
sidebar showed 25. The diagnostic returned all 25 employees in 0.20s, but the
parallel roster request took 3.95s and transferred 84 complete versions (2.9MB).
`RosterView` initialised employees to an empty array, rendered the empty state
before `Promise.all` completed, and did not catch load failures. Setting its
department after loading also triggered a redundant fetch. This was not lost data.

The page now distinguishes loading, failed/retry, and successfully empty states.
It requests only the selected week; explicit archived-version links still fetch
their named roster directly. A stable load callback avoids the department-triggered
duplicate request, and a request counter prevents older responses from overwriting
new navigation. Existing page styling is reused, with status/alert semantics.

`list_rosters` now accepts an optional week filter, preserving the unfiltered API
for other callers. Its cross-group cover previously queried MongoDB once for each
version. It now reads the relevant weeks once through the tenant-scoped collection,
then reuses those candidates in the existing cover helper. No persistent cache,
scheduler ranking change, or loss of current cross-group commitments was introduced.
The previous per-week 500-candidate ceiling and latest-visible-version ordering
remain intact; the batched query itself is not globally truncated.

The regression checks week filtering, tenant isolation, latest Deli coverage for
both Shop Floor versions, and exactly two roster reads. Frontend tests check a
pending populated list, caught failures/retry, a genuinely empty response, no second
department-triggered load, and direct archived-version fetching. Sabotage restored
per-version reads: the backend failed with four queries instead of two. Disabling
the loading/error UI made both frontend state tests fail. All fixes were restored;
the API and roster-group suites, all 11 frontend tests and production build passed.

Measured against Atlas afterwards: employees 0.184s, selected-week roster request
0.219s (that week has no saved versions), and shop 0.178s. The unfiltered historical
request fell from 3.95s to 1.65s but still transfers 2.9MB; this is not a claim that
every page now loads in 0.22s. Do not hide that denominator or equate API timing with
a browser-render benchmark. Data, credentials and original migration backups remain
unchanged. Product changes are in the Docker-mounted working checkout.

---

## 22. Loading screens must use the page's typography, not the legacy global heading

The user reported another font mismatch after the roster-loading fix. The new
early return used a generic card and `h2` outside `.wr-page`: that bypassed the
roster's Plus Jakarta Sans font and selected the global Inter heading instead.
Loading and error states now reuse `.wr-page`/`.wr-empty`, and the error title
and retry button use existing roster classes. No new fonts, CSS or palette were
added; fetch/error behaviour is unchanged. The regression asserts the roster
font wrapper and existing retry classes and rejects the generic loading heading.
Both state tests failed before the styling change, then passed after it. Keep
transient states inside the same page theme as loaded content.

---

## 23. Launch safeguards must hold at authentication and upload boundaries

The user authorised four fixes after the launch review: authentication rate limits,
safe Google linking, removing Emergent scripts/analytics, and bounded upload reads.
Diagnostics found no rate limiter; Google sign-in matched email and overwrote
`google_sub`, including its concurrent-signup fallback; public HTML loaded Emergent
and initialised PostHog against its endpoint; both roster and contact uploads read
the entire file before checking size. Google clock tolerance and Stripe billing
were deliberately outside this requested patch.

Authentication now uses shared atomic MongoDB fixed-window counters, hashed client
addresses, expiring indexes, HTTP 429 with Retry-After, and fail-closed database
errors. Never substitute per-process counters that reset with workers/restarts.
Deployment must validate the trusted proxy/client address; arbitrary forwarded
headers must not become a bypass. Shared office IPs share limits, and application
limits do not replace ingress DDoS/body-size/timeout controls.

Google sign-in looks up the verified stable subject first. A conflicting subject
cannot replace an existing link; unlinked local accounts may link automatically
only when Google is authoritative for the email (Gmail or Workspace). Other existing
accounts use password sign-in. The signup-race fallback applies the same checks,
and linking uses compare-and-set plus a unique partial subject index. Do not delete
accounts to make an index build over conflicting historical identities.

Roster/contact handlers read only their existing size allowance plus one byte and
return 413 before parsing oversized input. Multipart disk spooling and compressed
spreadsheet expansion still need separate deployment protection. Emergent scripting,
analytics and its error-suppression hook were removed; existing fonts/styles remain.

Twenty focused backend security regressions passed. Disabling limits, bypassing
link validation and restoring unbounded reads only inside an isolated test process
made all nine targeted negative controls fail. The wider API/security run passed
203 tests before three additional focused concurrency/index tests were added (those
also passed). The frontend script-removal regression passed. The full frontend run
found three existing RosterLoading failures; strict CI compilation stopped on the
existing RosterView useEffect/load dependency warning. A normal production build
passed with that warning. Neither page was changed by this patch. Do not report
the whole application green or launch-ready.

The complete backend suite subsequently passed (937 passed, one existing expected
failure). The original committed HTML also failed the script-removal guard, while
the generated production HTML passed it. No code was committed or pushed.

---

## 24. Restore lost loading safeguards without undoing newer approval behaviour

Step one of the launch preparation was to fix three RosterLoading test failures
and the Google timestamp rejection. Git history identified commit `5b542ad` as
removing the previously working load/error state, selected-week query, direct
archived-version read and stale-response guard from `9c51bd3`. Restore only those
parts, not the whole page: the newer approved-only export/print behaviour remains.
The original three tests failed before restoration and passed afterwards. Two new
tests also verify that older successful or failed requests cannot replace a newer
week. Loading and retry reuse the existing roster typography and theme.

Google's token was one second ahead of backend time, and the verifier defaulted
to zero skew. The shared verifier now passes a bounded five-second tolerance;
this also allows five seconds past expiry, so never describe it as an unlimited
clock workaround. Tests use genuinely signed RSA tokens, Google's real verifier
and local certificates: one/five seconds pass, six/sixty seconds in the future
or past expiry fail, and bad audiences, issuers, signatures and unverified email
remain rejected. Disabling tolerance only in an isolated process made the one-
and five-second tests fail, then the unchanged on-disk source passed.

The issuer regression exposed another boundary issue: GoogleAuthError was not
caught by the old ValueError-only handler. It now becomes the app's credential
error; transport failures instead become temporary unavailability. Raw library
timestamps/provider details no longer reach sign-in errors. Do not relax signature
checks or tell a customer that restarting their browser fixes backend clock skew.

All 14 frontend tests and the strict CI production build passed without the previous
hook-dependency warning. Google/launch-security tests passed with external services
disabled and a fake database; no live Google account login or production proxy
verification was performed. Billing and deployment are still separate next steps.

---

## 25. CI must test the real app, not hide imports that stop its tests loading

After step one's fixes were merged, PR #31 added an `@/styles/roster-weeknav.css`
import. The stylesheet existed and the production build worked, but Jest could
not resolve that alias and the roster-loading suite stopped at collection. CRACO
configured the alias only for Webpack. Its Jest configuration now resolves the
same `@/` root, preserving CRA's existing module mappings and stylesheet handling.
Do not mask this with a virtual CSS mock: NotificationsDrawer uses the same alias
and another page would simply hit the problem again.

The user authorised CI before the Railway-first deployment. The workflow runs two
independent checks on main-targeting PRs, main pushes and manual runs: full backend
tests and frontend tests plus strict production compilation. It uses the existing
Python 3.11/Node 20 runtimes, frozen frontend lockfile, cached dependency downloads,
read-only permissions, commit-pinned Actions, no persisted checkout credentials,
cancellation of superseded runs and bounded job duration. No deployment credentials
or automation was added; initial production releases remain manual.

Fresh installations also need JWT's cryptography extra and Google auth's requests
extra. Both are now explicit requirements; the existing signed-token regressions
must not depend on whichever libraries happen to remain in a developer's Docker
image. CI uses test-only environment values and the existing MongoDB mock fixtures,
never Atlas or live API keys. No MongoDB service is needed just to run these tests.

The alias regression failed before the shared mapping and all 14 frontend tests
passed afterwards; strict compilation also passed. Workflow YAML was parsed and
asserted to contain the intended triggers, two checks, pinned actions, read-only
permissions, test/build commands and no secret references. GitHub-hosted execution
and required-check enforcement are not claimed: after the first successful PR run,
the existing main ruleset must explicitly require both checks. Keep all pre-existing
branch protections and do not bypass checks merely to meet a launch date.

The complete backend run passed: 951 passed, one skipped and one existing expected
failure in 96 seconds. Updated dependency extras also passed pip's no-install
resolution check. These are local Docker results, not a claim that GitHub Actions
has already run or that production deployments are gated.

## 26. Empty supervisory selections do not require closing cover

The staging shop had only Night Shift staff and no supervisory role selected,
but approval demanded a manager at 23:00 on every day. Both the solver and
compliance treated the presence of supervisory_roles (even []) as a closing
requirement. The first fix wrongly made all closing requirements depend on AI
Rules, contradicting the user's intended Supervisory switch. The user clarified:
selecting ANY supervisory role requires one of those roles at every close;
selecting NONE must not create that requirement. Both solver and compliance now
test the list's contents rather than the field's presence. Do not redesign a
documented product setting while fixing its empty-list bug. Explicit AI closing
rules remain an independent requirement through closing_supervisor_rules and report
missing cover, including when no qualifying role exists; 24-hour exemptions
and learned soft supervisory targets are unchanged. Shop Settings no longer
claims this rule is universal or that supervisory selections are not saved, and
explains the selected-versus-empty behaviour instead.

The page also said ready to approve while its approval dialog listed breaches.
Needs attention omitted the live audit's breaches. It now displays those same
breaches and explains the override boundary. A missing/pending audit cannot
produce an all-clear, and a previous roster's audit cannot replace a newer one.
Existing edits remain visible in their separate historical panel; no roster,
role, or stored warning is deleted. Tests cover empty/populated role selections,
explicit missing/covered closes, scheduler behaviour, hard/overridable warnings,
and an unavailable audit. Changes must reach both backend and frontend before
the deployed site can be claimed fixed.

Verification: all 18 frontend tests passed using existing dependencies from the
Desktop checkout, while testing the working C:/Users/anees/Roster source. The full
backend run had no assertion failures and one Windows temporary-directory setup
error; that test passed when rerun with a fresh task-specific directory alongside
all 29 focused closing/compliance tests. One existing expected failure remains.
After the user's clarification, the corrected selected-versus-empty behaviour
passed the full backend suite: 961 passed, one existing expected failure. All 19
frontend tests passed. Removing a role now removes its supervisory selection too;
loading/saving settings excludes supervisory roles no longer on the ladder, so a
deleted role cannot remain as a hidden closing requirement. The regression saves
settings after removing the final selected role and checks supervisory_roles=[].
No production build, remote deployment, or live account test was performed here.

## 27. Merge the shared roles table without losing the supervisory fix

Main's PR #34 extracted RolesTable for both settings and first-run setup, while
ci-launch-checks fixed the old inline tables. Their two Onboarding conflicts must
keep the shared component, not restore duplicated markup or accept both sides.
The corrected selected-versus-empty explanation belongs in RolesTable now.
Preserve hydration filtering, saved selections, removal cleanup, and the live
approval-breach panel. A wizard regression toggles the shared supervisory switch
off and confirms the next save sends an empty list. Merge main into the published
branch without rebasing or force-pushing; do not push or deploy for the user.

Merged-source verification: all 20 frontend tests and 205 backend tests for
compliance, low-history scheduling, learned slots and contract pay passed. The
production build and full merged backend suite were not rerun; GitHub CI must
finish before merging the updated PR. No remote writes or deployments performed.

## 28. Fix diagnostic privacy at the output, not in the scheduling inputs

PR #37's logging autofix inserted a top-level helper in the middle of the async
staff-email importer. Its remaining body, including an await, ended up inside
the synchronous helper and the script could not compile. Masking two diagnostic
lines also left names exposed in other staff tables, lookup errors and free-text
notes. Repair the importer and remove identities from these output paths without
changing the records used for matching or solving.

diagnose.py now uses report-local Employee labels consistently; who_owns.py
reports the selected employee without echoing their name or listing other staff.
set_emails.py reports CSV line numbers and reasons instead of names and addresses.
It still defaults to a dry run, rejects ambiguous matches and shared addresses,
and requires --replace before overwriting an existing address. Diagnostic reports
retain scheduling details and are not a guarantee of complete anonymisation.

The user explicitly chose to restore the generic login error. Unknown addresses
and wrong passwords return the same 401 response, and the frontend no longer
renders the old email_not_found message. Successful sign-in and account
restoration are unchanged; the deletion regression expects the generic error too.

Regression evidence: the new CLI tests initially had 11 failures, including the
syntax error and identity leaks; all 13 passed after the fix. Reintroducing the
raw employee name in an isolated, in-memory mutation made its privacy test fail,
without changing a source file. The updated login tests had four failures before
the backend response was repaired. Final verification passed 1,221 backend tests
with one existing expected failure, and all 22 frontend tests. Tests used mock
data, not live Atlas records. Production build and GitHub CodeQL were not run
locally; remote required checks and review must finish before merging. The
account-deletion loop only runs while the backend is awake; hosting was not
changed as part of these fixes.
