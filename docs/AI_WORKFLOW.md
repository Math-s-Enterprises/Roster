# Working with an AI assistant on Roster

How to give an AI the context it needs, and how to keep that context true.
Written for this repository: the files named here exist, and the commands run.

The principle: **the AI knows only what it is shown.** A model that has not
read these files will happily "fix" the design system, re-derive a rule that was
settled for a reason, or store something the project chose to derive.

---

## What to read, and in what order

| Order | File | Gives the AI |
|---|---|---|
| 1 | [CLAUDE.md](../CLAUDE.md) | The rules that are never relaxed, and the traps that have bitten before |
| 2 | [feedback.md](../feedback.md) | How you like to work, and mistakes already made |
| 3 | [PRD.md](PRD.md) | What is being built, for whom, and what is out of scope |
| 4 | [ARCHITECTURE.md](ARCHITECTURE.md) | How it is built, and the rules for changing it |
| 5 | [DECISIONS.md](DECISIONS.md) | Why it is built that way |
| 6 | [MEMORY.md](MEMORY.md) | What is true right now, and what is known to be broken |
| as needed | [TEST_PLAN.md](TEST_PLAN.md), [SECURITY.md](SECURITY.md), [WORK_QUEUE.md](WORK_QUEUE.md) | Verification, safety, planned work |

`DESIGN.md` is **not** on the list until it is rewritten — it describes only the
original dark system (MEMORY.md, known issue 5).

## What each tool reads on its own

- **Claude Code** reads `CLAUDE.md` automatically at the start of a session.
- **Other coding agents** generally read `AGENTS.md`. Keep it a pointer to
  `CLAUDE.md`; two full copies drift (MEMORY.md, known issue 6).
- **A chat window** reads nothing automatically. Attach the project, or paste
  the files, and say so in the first message.

---

## Start of a session

```
Read these before doing anything:
CLAUDE.md, feedback.md, docs/PRD.md, docs/ARCHITECTURE.md,
docs/DECISIONS.md, docs/MEMORY.md

Change nothing yet. Then tell me:
1. What you understand the product to be, in three sentences.
2. Anything in those files that contradicts the code or each other.
3. Your plan for: <the task>.
```

Point 2 is the valuable one. The project's own docs have disagreed with each
other and with the code before, and an AI that has just read all of them is the
cheapest way to find out.

## Asking for a change

Plan first, then build — `feedback.md` records that you want agreement before
code, and "yes please" is the signal to start.

```
CONTEXT   One line on what this touches. Which of the files above apply.
TASK      One thing. Not "build rename" — "add the rename endpoint".
FILES     The files it is likely to touch. Say what NOT to touch.
RULES     The ones that apply: ShopScope for every query, scheduler stays
          pure, colour from tokens, no new dependency without asking.
DONE WHEN Observable results, one per line.
CHECKS    python -m pytest · yarn check:css · yarn build · the manual items
          in TEST_PLAN.md that match.
```

A worked example:

```
CONTEXT   Roster groups. A group's name is a key in five places (see
          ARCHITECTURE.md). Read ADR-011.
TASK      Add POST /shop/departments/rename { from, to }.
FILES     backend/app/routes/shop.py, services/departments.py, tests.
          Do not change the frontend.
RULES     Go through ShopScope. One atomic step. Keep the group's position —
          the first group is the primary one.
DONE WHEN - Renaming a group in use succeeds and nothing is orphaned.
          - A blank or duplicate name is refused, case-insensitively.
          - Employees, rosters, settings and AI rules all show the new name.
CHECKS    python -m pytest, with new tests for each line above.
```

Small tasks beat large ones. "Build the whole thing" gives the AI room to
misunderstand; "add one endpoint, with tests" does not.

## Reviewing what it did

```
Review the change against CLAUDE.md, ARCHITECTURE.md and DECISIONS.md.
Check correctness, tenancy (every query scoped), the theme rules, error
and empty states, and the Light and Dark themes.
Do not modify anything. List every issue first.
```

Then fix the issues one at a time.

## When something breaks

```
ERROR     <paste it exactly>
EXPECTED  What should happen.
ACTUAL    What happens instead.
STEPS     1. … 2. … 3. …
LIMIT     Do not change <what must stay>.

Do not edit code yet. Find the root cause:
what is failing, why, which file, the smallest fix, how we will test it.
```

`feedback.md` records that explaining the *mechanism* — not the symptom — moves
things faster.

---

## The loop, for every change

1. **Read** the files above.
2. **Plan** — the approach, in a few lines.
3. **Wait** for your yes.
4. **Build** the smallest slice that works end to end.
5. **Check** — the commands, then the manual pass for what you touched.
6. **Review** against the docs.
7. **Commit** — small, with a message that says why.
8. **Update the docs** — see below.

## What to update, and where

| If the change… | Update |
|---|---|
| alters a product rule | `CLAUDE.md`, and a dated entry in `feedback.md` |
| makes a lasting choice | `DECISIONS.md` — a new entry, never an edit of an old one |
| fixes or finds a problem | `MEMORY.md` |
| touches auth, uploads, email or personal data | `SECURITY.md` |
| adds a screen or behaviour | `TEST_PLAN.md` |
| changes the structure | `ARCHITECTURE.md` |

When a doc and the code disagree, **the code wins** — fix the doc in the same
change. A document that describes an application that no longer exists is worse
than none, because the AI will believe it.
