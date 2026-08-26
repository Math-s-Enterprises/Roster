# Learning from corrections — plan

**Goal, in the owner's words:** after a month of use, the manager should
believe the roster it produces is better than one they would write themselves.

**Measured as two numbers that must fall:**

1. **Edits per approved roster** — how wrong the first draft was
2. **Generations per approved week** — should trend to 1. One week recently
   took 16.

Everything below serves those two numbers. If a phase does not move them, it
does not belong.

---

## The idea in one paragraph

The scheduler currently learns from **approved rosters** — weeks that worked.
But the highest-signal data is the **correction**: the manager looked at what
the solver proposed and changed it. That is the manager saying "you got this
wrong, here is right". Today that signal is destroyed, because editing
overwrites the generated roster in place. Phase 1 stops the loss; Phase 2
reads it; Phase 3 acts on it.

---

## Phase 0 — Measure the baseline

**Why first:** we cannot claim an improvement without knowing where we
started, and the measurement needs no code changes. Same discipline as the
11-hour rest check, which was verified against 2009 real shift pairs before
becoming a constraint.

**Build:** `ml/measure_edit_burden.py` — reads existing rosters and reports:

- generations per approved week, median and worst
- how that trends over time
- which weeks were regenerated most

**Note on honesty:** your early history is polluted. Those 16 generations
happened while the solver was genuinely bad and we were changing it weekly.
The script will report from a cut-off date so the baseline reflects the
current solver, not its ancestors.

**Done when:** we have a number to beat. No app code touched.

---

## Phase 1 — Capture the signal

**The problem:** `PUT /rosters/{id}` overwrites `shifts`. What the solver
originally proposed is gone the moment you edit. Corrections are currently
unrecoverable.

**Build:**

- On generate, store `generated_shifts` — a frozen copy of the solver's
  output — plus `generated_at`. Never touched by edits.
- On approve, diff `generated_shifts` against the final `shifts` and store the
  result as `corrections` on the roster, along with `edit_count`.

**Four kinds of correction:**

| Kind | Meaning |
|---|---|
| `swap` | solver put Kelvin on Wed 06:00–14:00; manager used Jane |
| `moved` | manager changed Megan's Tuesday from 09:00 to 10:00 |
| `removed` | manager took Andi off Thursday entirely |
| `added` | manager put Kyle on Saturday |

**Files:** `routes/rosters.py`, new `services/corrections.py` (diff only).

**Existing rosters:** they have no snapshot, so they contribute nothing. They
are excluded rather than guessed at — consistent with §9 of `CLAUDE.md`.

**Tests:** each correction kind detected correctly; the snapshot survives
repeated edits unchanged; a roster approved with no edits records zero.

**Done when:** approving a roster you edited stores an accurate list of what
you changed. Nothing else behaves differently.

**This is the urgent phase.** Every week that passes without it is signal
permanently lost.

---

## Phase 2 — Read it and show it

**Build:**

- Aggregation in `corrections.py`: across approved rosters, tally corrections
  by kind, by person, by day and slot.
- `GET /reports/corrections` — what the scheduler has learned so far.
- A panel showing **"Your last five rosters needed 6, 4, 3, 1, 1 edits."**
- A list of learned preferences with their counts, each dismissible.

**Why the panel is not decoration:** that falling number is the product
proving its worth to the customer every week. It is the dependency the owner
is aiming for, and a competitor cannot copy it — it is specific to this shop.

**Why dismissible matters:** if the scheduler has concluded something wrong,
the manager must be able to find that out from a screen rather than from a bad
roster. Learning you cannot inspect is learning you cannot trust.

**Files:** `services/corrections.py`, `routes/reports.py`, new frontend page.

**Done when:** you can look at a screen and see what it thinks it has learned,
and disagree with any line of it.

---

## Phase 3 — Turn repeated corrections into settings you can see

**The design decision that matters.** The obvious implementation is a hidden
weight in the ranking. This is not that, and the difference is the whole
reason this design is safe.

Ask what a repeating correction actually *means*. If the manager takes Kelvin
off Wednesday three weeks running, that is not really "a learned preference".
It is this:

> **Kelvin's preferred day off should be Wednesday.**

That field already exists, the solver already respects it, and the manager can
see and change it. So the scheduler should not quietly nudge a score — it
should say what it noticed and offer to write it down:

> *"You've taken Kelvin off Wednesday 3 times. Set Wednesday as his preferred
> day off?"* — **Yes** / **No, it's coincidence**

**Every correction kind maps to an existing setting:**

| Repeated correction | Suggests |
|---|---|
| removed from a day | `preferred_days_off` |
| moved to a later start, repeatedly | `availability.earliest_start` |
| added to the same slot | a fixed shift |
| swapped A out for B on a slot | B's familiarity for that slot; A's unsuitability |

**Why this largely dissolves the one-off risk:**

- A one-off never reaches three, so it is never suggested. The manager is
  never interrupted for noise.
- A real pattern is suggested once, and **the manager decides**. Noise cannot
  become policy without somebody agreeing to it.
- The result lands in a field that can be read and reversed, not an opaque
  weight. Learning that cannot be inspected is learning that cannot be
  trusted — and the product is trying to earn exactly that trust.
- The scheduler visibly gets better at *this* shop, which is the dependency
  the owner is aiming for.

**Safeguards that still apply**, for anything that remains a weight rather
than a setting:

1. **Never a hard rule.** A correction is a preference, not a law.
2. **Three occurrences** before anything is suggested — the same threshold
   `demand.py` uses for shift patterns (`MIN_PATTERN_OCCURRENCES`).
3. **Only inside the 24-week window**, so an old habit fades as staff change.
4. **Declining is remembered.** "No, it's coincidence" must not be asked again
   next week, or the prompt becomes noise of its own.

**The failure mode this avoids:** a feedback loop. A hidden weight that stops
Jane ever being offered Sundays means the manager never gets the chance to
correct back, and the mistake becomes permanent and invisible. A suggestion
the manager declined is a decision on the record.

**Files:** `services/corrections.py`, `routes/shop.py` (applying an accepted
suggestion), frontend prompt.

**Tests:** a correction repeated three times produces a suggestion and twice
does not; accepting one writes the real setting; declining one suppresses it
permanently; no suggestion can be created that would breach any of the seven
rules.

**Done when:** the scheduler tells you what it noticed, you agree or disagree,
and the outcome is visible in the employee's record rather than hidden in a
score.

---

## Phase 4 — Stop encouraging regeneration

> **Rewritten after the seed change.** This phase was written when Regenerate
> was provably useless: deterministic solver, same inputs, sixteen identical
> weeks. That is no longer true — Regenerate now varies the shifts nobody has
> a settled claim on, so it genuinely offers a different arrangement.
>
> The nudge still stands, but the honest reason has changed. Regenerating is
> not pointless; it just starts from the same information, so it cannot fix a
> roster that is wrong for a reason the scheduler does not know yet. Editing
> is what tells it. The wording says that rather than calling regeneration a
> waste of time, which the manager would correctly recognise as false.


**The behaviour to fix:** when a roster came out wrong, the instinct was to
regenerate — 16 times in one week. But regenerating throws away both the
attempt and the reason it was wrong, then rolls the dice from the same inputs.
Editing the 10% that is wrong keeps the 90% *and* teaches the system.

The UI currently presents Generate/Regenerate as the obvious action and
Rebalance as secondary. That is backwards for the outcome we want.

**Build:**

- Make Rebalance the primary action once a roster exists.
- After the third generation of one week, say plainly: *"Editing and
  rebalancing teaches the scheduler. Regenerating starts over and teaches it
  nothing."*

**Files:** `RosterView.js`.

**Done when:** the cheap action is also the one that improves the product.

---

## Phase 5 — Prove it

Re-run Phase 0's measurement. Both numbers should have fallen. If they have
not, Phase 3's weighting is wrong and we tune it — with evidence rather than
opinion.

---

## The risk, and why the Phase 3 design mostly removes it

**The original worry:** this only works if corrections repeat. If the
manager's edits are one-offs — fine-tuning for reasons that never recur —
learning them would add noise, and the rosters would get worse.

**Why suggesting settings rather than learning weights removes most of it:**

- A one-off never reaches three occurrences, so it is never suggested.
- A pattern is suggested once and **the manager decides**. Nothing enters the
  system without a human agreeing to it, so noise cannot silently become
  policy.
- Anything accepted lands in a visible field that can be changed back.

The bad outcome — the scheduler quietly concluding something wrong and the
manager discovering it from a bad roster — is close to impossible under this
design. That was the risk actually worth eliminating.

**What remains is not damage, it is a smaller benefit.** If corrections are
mostly one-offs, few suggestions appear and the learning does little. The
product is no worse than today, and the falling edit-count panel from Phase 2
still earns its place.

**Phase 2 still comes first**, because it tells us which world we are in
before Phase 3 is built at all. If the corrections show no repetition, Phase 3
is not worth writing.

---

## Order and effort

| Phase | What | Rough size |
|---|---|---|
| 0 | Measure the baseline | small |
| 1 | Capture the signal | small — **do first** |
| 2 | Read it, show it, allow disagreement | medium |
| 3 | Suggest settings from repeated corrections | medium |
| 4 | Nudge editing over regenerating | small |
| 5 | Prove the numbers moved | small |

Phases 0 and 1 are independent of everything else and safe to do immediately.
The decision point is after Phase 2.
