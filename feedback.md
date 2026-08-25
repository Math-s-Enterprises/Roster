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

**I have stated things about his own app that were false.**
Told him no password reset flow existed when `ForgotPasswordReq` and
`ResetPasswordReq` were right there. Described the Supabase design register as
dark when it is white — and he picked a palette based on that, then had to
reject it. **Verify before describing, especially when he will act on it.**

**I used the wrong email.** Used his Claude account address in a script
instruction when his app login is different. Small, but it wasted a run.

---

## 4. What worked — keep doing

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

---

## 6. Still parked, by his choice

- **Resend email setup** — `RESEND_API_KEY` empty; password reset and dispatch
  silently do nothing
- **Billing / paywall** — disabled in two places that can disagree
- **Docker, CI, rate limiting, error tracking, backups, GDPR paperwork**

He said "not now" to billing and "we will work on this later" for email. Do not
re-raise unprompted more than once.
