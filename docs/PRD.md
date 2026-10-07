# Roster — Product Requirements

What we are building and why. *How* it works is in [ARCHITECTURE.md](ARCHITECTURE.md);
the scheduling rules themselves are in [../CLAUDE.md](../CLAUDE.md).

This replaces `memory/PRD.md`, which describes the original build (Emergent
keys, a dark glassmorphism look, a seeded demo owner) and no longer matches
the product.

---

## Problem

Shop managers build the weekly rota by hand. Every opening hour has to be
covered, every person has a contract, holidays and preferences, and
working-time law is easy to break by accident. It takes hours, and the result
is pinned to a wall or emailed around.

## Users

- **Manager / owner** — the only person who signs in. One account per shop.
- **Staff** — receive their roster by email. They never sign in, and there is
  no staff portal.

The product was built against one real shop (Top Oil South Link: about 24
staff, 30 weeks of the manager's own rosters). That shop is a **fixture, not
the specification** — nothing may be hard-wired to it
(CLAUDE.md §9b, §10b).

## Goal

A manager sets the shop up once and gets a covered, lawful week that looks
like the ones they would have built — and that gets closer to their own
pattern as their history grows.

---

## What exists today

**Setting up the shop**
- Shop settings: opening hours (including 24-hour), shift length limits,
  minimum rest, paid sick days, roles and seniority, supervisory cover,
  roster groups, who else receives the roster.
- Employees: role, rate, contracted and maximum hours, age, guaranteed days
  off, availability, student and term-time rules, per-group roles.
- Holidays and absences, fixed (pinned) shifts, and plain-English custom
  scheduling rules.

**Building a week**
- Generate a roster; edit shifts; rebalance a whole week or a single day;
  add extra staff; arrange sick cover.
- Findings: what the roster breaks, what was changed by hand, and how the
  week compares with the shop's usual.
- Approve (with force-approval and a recorded reason for rule breaks) and
  reopen; each run is a numbered version.

**Learning from history**
- Import past rosters (spreadsheet and CSV; PDF and photo when an API key is
  configured). Staffing levels, who normally works what, and manager
  corrections are learned from approved weeks.

**Getting it to people**
- Email to staff (with delivery reporting), PDF, CSV and print.

**Reporting**
- Hours and wages (approved rosters only), sick leave, holiday balances,
  past-rosters archive, and what the scheduler has learned.

**Accounts**
- Email and password, optional Google sign-in, forgot and reset password,
  "keep me signed in", light and dark themes.
- Free and Pro plans through Stripe.

**Roster groups.** One shop can run several rosters — a shop floor and a deli,
say. A group is a *workspace* with its own hours, roles, history and learning;
legal limits stay shop-wide (feedback.md §10–11).

---

## Out of scope

- A staff login or self-service portal; shift-swap requests.
- SMS or WhatsApp alerts.
- A native mobile app (the web app is responsive).
- Several employers under one account. Roster groups live inside **one**
  shop and share its employment and legal facts.
- A machine-learned scheduler in production. The offline experiment did not
  beat the baseline and stays offline (docs/WORK_QUEUE.md).
- Running payroll. The app reports hours and cost; it does not pay anyone.

## Success criteria

A manager can:

1. Create an account, set up a shop, add staff, and generate a roster for a
   week.
2. Trust that no generated roster breaks a rule that is never relaxed
   (CLAUDE.md §1): somebody is on the floor from open to close, a 24-hour shop
   is never empty, nobody exceeds their contract, weekly cap or the under-16
   curfew, and no shift runs past 12 hours.
3. Edit a roster by hand and be told — before saving — what the edit breaks.
4. Approve a week, email it, and see who could not be reached.
5. Rely on an approved week being a **record**: only a sick report changes it
   directly. Reopening is possible until the week is over, and takes the week
   back out of what the scheduler learns.
6. Read hours and wages that come from approved weeks only, so a draft never
   reaches payroll.
7. Import past weeks and see the next generated week move towards them.
8. Run a second roster group without it inheriting the first one's hours,
   roles or history.

The sign-in page says rosters take "under five minutes". That is a marketing
claim, not a measured requirement.

## Constraints

- **Jurisdiction.** Defaults follow Irish working-time law (Organisation of
  Working Time Act 1997): eleven hours' rest, the 48-hour average, the
  under-16 curfew, five paid sick days. Another jurisdiction needs rule
  changes, not just settings.
- **Honest degradation.** The app boots with three environment variables.
  Everything optional (AI, email, Google, billing) says plainly when it is
  off rather than failing when used (backend/app/config.py).
- **Never invent data.** If the solver cannot lawfully fill a gap, it reports
  the gap (CLAUDE.md §9).

## Plans and billing

- **Free** — capped at `FREE_PLAN_ROSTER_LIMIT` (4) rosters, **only when**
  `BILLING_ENFORCED=true`. It is off by default.
- **Pro** — 19 monthly or 190 yearly, in the configured currency.

Whether billing is enforced for real customers is still undecided
(CLAUDE.md §13).
