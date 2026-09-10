# Learned rostering — implementation plan

This is the earlier proposal. See [the current work queue](WORK_QUEUE.md) for completed repairs, local work awaiting review and the next steps. The status and experiment figures below describe the original proposal, not current readiness.

Status: **proposed**, not built. Written after the feasibility experiment in
`backend/ml/experiment_baseline.py`, which reached AUC 0.869 on attendance and
76.8% top-3 on shift patterns using 30 weeks of one shop's real history.

---

## 1. What we are building, and what we are not

**Building:** a learned scoring function that ranks *already-legal* candidates
for each shift slot, so generated rosters increasingly resemble what this shop's
manager would have chosen anyway.

**Not building:**

- A model that decides legality. Curfews, hour caps and coverage stay in
  `services/scheduler.py` as hard filters. A model that has learned badly must
  only ever produce a *suboptimal* roster, never an *unlawful* one.
- An LLM that writes rosters. The solver is deterministic and auditable; that
  is a feature, particularly when an employment dispute asks why someone was
  scheduled.
- Full autonomy. A human approves every roster. Target is "manager edits less",
  not "manager disappears".

**Definition of success:** the proportion of AI-generated shifts that survive
to approval without being edited goes up. That single metric is the whole
point, and Stage 5 exists to measure it.

---

## 2. Where the model sits

```
      shop settings, employees, holidays, fixed shifts, rules
                              │
                              ▼
              ┌───────────────────────────────┐
              │  HARD CONSTRAINT FILTER        │   scheduler.py — unchanged
              │  curfew · hour caps · leave    │   never learned
              │  coverage floor · custom rules │
              └───────────────┬───────────────┘
                              │  legally-eligible candidates
                              ▼
              ┌───────────────────────────────┐
              │  SCORING                       │   ← the new part
              │  blend( learned model,         │
              │         frequency heuristic )  │
              └───────────────┬───────────────┘
                              │  ranked shortlist
                              ▼
              ┌───────────────────────────────┐
              │  GREEDY ASSIGNMENT             │   scheduler.py — unchanged
              └───────────────┬───────────────┘
                              ▼
                       draft roster
                              │
                    manager edits + approves
                              │
                              ▼
              ┌───────────────────────────────┐
              │  TRAINING SIGNAL CAPTURE       │   ← the new part
              │  what we proposed vs           │
              │  what they approved            │
              └───────────────────────────────┘
                              │
                     nightly retrain job
```

The loop closes at the bottom: edits are the strongest signal available, and
today they are discarded.

---

## 3. Staged delivery

Each stage leaves the app working and is independently useful. Do not start a
stage before the one above it, since each depends on data the previous produces.

### Stage A — Excel import (unblocks everything)

Without history there is nothing to train on, so this comes first. It also
solves cold start for every future customer, which is user-visible value on its
own.

| Work | Files |
|---|---|
| Upload endpoint accepting `.xlsx`/`.csv`, returning a parsed **preview** — never importing straight away | `app/routes/imports.py` *(new)* |
| Name reconciliation: match sheet names to existing employees, propose creating unknowns | `app/services/roster_import.py` *(extend)* |
| Commit endpoint: writes reviewed rosters as `historical: true, approved: true` | `app/routes/imports.py` |
| Upload → review → confirm UI, showing unparsed cells and hour-mismatch warnings for manual resolution | `frontend/src/pages/ImportRosters.js` *(new)* |
| Store the raw file for reprocessing when the parser improves | GridFS |

**Design note.** Import is deliberately two-phase (preview, then commit). The
parser already reports what it could not read; silently importing an
approximation of a shop's history would poison training data in a way that is
very hard to detect later.

**Done when:** the 30-week workbook imports end-to-end through the UI, with the
10 ambiguous cells surfaced for a human decision.

---

### Stage B — Training-signal capture

| Work | Files |
|---|---|
| On generate: persist the proposed assignment set with the roster | `app/routes/rosters.py` |
| On approve: diff proposed vs final, write `training_examples` rows | `app/services/training_capture.py` *(new)* |
| Backfill from imported history (positives, and `OFF` as available-but-not-chosen) | `app/services/training_capture.py` |
| Index: `{shop_id, week_start}` | `app/db.py` |

**Label semantics** — this is the part that is easy to get subtly wrong:

| Situation | Label | Why |
|---|---|---|
| Proposed and approved unchanged | strong positive | the model was right |
| Proposed, then removed by the manager | **strong negative** | the model was wrong; the most valuable row we have |
| Not proposed, manager added them | **strong positive** | a preference the model missed |
| `OFF` — available, not chosen | weak negative | genuine choice, but low-information |
| `HOL` / `N/A` / sick | **excluded entirely** | they *could not* be chosen; treating this as a preference teaches the model that people on holiday are unpopular |

That last row is the classic mistake in this kind of problem. Availability is
not preference.

---

### Stage C — Feature store and training pipeline

| Work | Files |
|---|---|
| Materialised per-shop features, updated on approval instead of recomputed per request | `app/services/features.py` *(new)* |
| Training entry point, callable from CLI and scheduler | `ml/train.py` *(new)* |
| Model registry: artifact + metrics + feature-schema version | `app/services/model_registry.py` *(new)* |
| Nightly job, gated on "≥N new approvals since last train" | `ml/scheduler_job.py` *(new)* |

**Why materialised features.** `compute_weights()` currently rescans every
approved roster on every generate. At today's volume that is milliseconds, but
it grows linearly with a shop's history forever. Updating counts on approval
turns an O(history) read into O(1).

**Retraining cadence.** Retraining on every approval sounds like "learns every
time" but produces unstable models that swing on single examples. Append
immediately, retrain nightly, and only when enough new data has accumulated to
matter. The user-visible behaviour is the same; the model is far steadier.

**Model artifacts live in GridFS.** No new infrastructure, transactional with
the metadata, and works across multiple app instances — unlike the filesystem.
Put it behind a `ModelStore` interface so moving to S3 later is a one-file
change.

---

### Stage D — Inference in the solver

| Work | Files |
|---|---|
| `Scorer` protocol: heuristic and learned implementations behind one interface | `app/services/scoring.py` *(new)* |
| `_RosterBuilder._rank()` calls the injected scorer | `app/services/scheduler.py` |
| Lazy model load + in-process cache, refreshed when the registry version changes | `app/services/model_registry.py` |
| Blend factor, per shop, ramping with data volume | `app/services/scoring.py` |

**Blending, not switching.** Score as
`α · model + (1 − α) · heuristic`, with α rising from 0 toward ~0.8 as a shop
accumulates approved weeks. A shop with three weeks of history gets the
heuristic; a shop with a year gets mostly the model. This avoids the cliff
where a new customer receives predictions from a model trained on almost
nothing.

**The scheduler must stay pure.** It currently has no I/O, which is why it is
exhaustively testable. The scorer is *injected*, not imported — otherwise
`scheduler.py` acquires a database dependency and the 29 fast unit tests
become slow integration tests.

---

### Stage E — Shadow mode and monitoring

Ship the model switched **off** first.

| Work | Files |
|---|---|
| Log what the model *would* have chosen, without acting on it | `app/services/scoring.py` |
| Compare shadow predictions against manager-approved outcomes | `ml/evaluate.py` *(new)* |
| Per-shop edit-rate trend | `app/routes/reports.py` |
| Kill switch: env flag + per-shop opt-out | `app/config.py` |

Run shadow mode for a few weeks. Only enable a shop once its shadow
predictions are demonstrably beating the heuristic **on that shop's data**.
Aggregate accuracy is not sufficient evidence for any individual shop.

---

## 4. Decisions worth making explicitly

### Per-shop models, not one global model (recommended for now)

|  | Per-shop | Global |
|---|---|---|
| Cold start | poor — needs history | good |
| Learns local quirks | yes | diluted |
| Cross-tenant privacy | **no issue** | must be disclosed |
| Ops burden | one artifact per shop | one artifact |

With one live shop these are equivalent in practice, but per-shop avoids the
disclosure that one customer's patterns influence another's schedules — a
promise that is much easier to make now than to retract later. Revisit at
roughly 20+ shops, when a global base model with per-shop features starts to
pay for itself on cold start.

### Two models, not one

Attendance ("does this person work Tuesday?") and pattern ("which shift?") have
different label spaces and very different accuracy. Keeping them separate lets
each be evaluated and improved on its own, and lets the pattern model be
skipped entirely for shops that use fixed templates.

### Feature schema is versioned

A model trained on features v3 must refuse to run against features v4. Store
the schema version with the artifact and check it at load. Silent feature drift
is the most common way production ML models rot without anyone noticing.

---

## 5. Features to add beyond the experiment

The baseline used six features. These are the cheap wins, roughly in order of
expected value:

- **Coworker affinity** — who is usually rostered alongside whom
- **Previous-week shift** — rotation patterns (earlies one week, lates the next)
- **Days since last shift** — spacing and fairness
- **Hours already assigned this week** — proximity to their cap
- **Cover history** — who steps in when a specific person is away
- **Seasonality** — month, proximity to a bank holiday
- **Contract hours** — full vs part time (you already collect this)

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Model entrenches an unfair pattern (always the same person on Sundays) | Fairness check in `ml/evaluate.py`: distribution of unsociable hours per person, tracked over time |
| Feedback loop — model proposes, manager accepts out of convenience, model concludes it was right | Track edit rate; a *falling* edit rate with *rising* complaints is the warning sign |
| Retrain silently degrades quality | Registry keeps the previous artifact; promote only if offline metrics beat the incumbent |
| Sparse shops get nonsense predictions | Blend factor α tied to data volume; heuristic below threshold |
| Feature/serving skew | One shared feature-building module used by both training and inference — never two implementations |

---

## 7. Effort

| Stage | Rough size |
|---|---|
| A — import + UI | largest single chunk; the UI is most of it |
| B — capture | small, mostly schema plus a diff |
| C — features, training, registry | medium |
| D — inference wiring | small if the scorer interface is right |
| E — shadow + monitoring | medium, but mostly reporting |

Stage A alone is worth shipping on its own merits, even if the model never
follows.
