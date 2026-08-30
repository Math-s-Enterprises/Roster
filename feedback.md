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

---

## 4. What worked — keep doing

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

- **Resend email setup** — `RESEND_API_KEY` empty; password reset and dispatch
  silently do nothing
- **Billing / paywall** — disabled in two places that can disagree
- **Docker, CI, rate limiting, error tracking, backups, GDPR paperwork**

He said "not now" to billing and "we will work on this later" for email. Do not
re-raise unprompted more than once.
