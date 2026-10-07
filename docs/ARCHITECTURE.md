# Roster — Architecture

How the application is built. *What* it does is in [PRD.md](PRD.md); the
scheduling rules and the reasoning behind them are in
[../CLAUDE.md](../CLAUDE.md); choices and their reasons are in
[DECISIONS.md](DECISIONS.md).

---

## Overview

```
 Browser (React 19, CRA + craco, Tailwind)
   │  axios — adds Authorization: Bearer <jwt> and X-Roster-Group on every call
   ▼
 FastAPI  /api/*                                   backend/app/main.py
   │  routes/      HTTP only: auth, shop, rosters, holidays,
   │               imports, reports, ai_rules, payments
   │  tenancy.py   ShopScope — every query is bound to one shop
   ▼
 services/                                         the real work
   │  scheduler    pure solver: dicts in, dict out. No db, no network.
   │  demand · learning · corrections · slot_owners · availability
   │  compliance · roster_validation · sick_cover · rule_parser …
   ▼
 MongoDB (Motor)                                   backend/app/db.py

 Optional, each degrades honestly when its key is missing:
   Anthropic (summaries, photo/PDF reading, rule compiling) · Resend (email)
   Google sign-in · Stripe (billing)
```

The scheduler is the product. Its own docstring calls everything else
"plumbing around this module".

## Backend

### Layers

| Layer | Where | Rule |
|---|---|---|
| Routes | `app/routes/` | Receive, authorise, call services, return. |
| Scope | `app/tenancy.py` | `ShopScope` binds one `shop_id` per request and builds every filter. Routes use `scope.employees`, `scope.rosters`… and cannot express an unscoped query. |
| Services | `app/services/` | The logic. |
| Data | `app/db.py` | Named collection handles only — a typo fails at import instead of creating an empty collection. |

### Services

| Module | Answers |
|---|---|
| `scheduler` | The roster solver. Pure. |
| `demand` | Staffing demand learned from the shop's own approved rosters. |
| `learning` | Historical preference weights. Counting, **not** machine learning. |
| `corrections` | What the manager changed about a generated roster. |
| `training_evidence` | Decision-time evidence, kept apart from learned preferences. |
| `slot_owners` | Who normally works a given shift. |
| `availability` | Can this person work this shift, on this date? |
| `roster_validation` | May this hand edit be saved? (before vs after) |
| `compliance` | What does this finished roster break, and may it be overridden? |
| `sick_cover` | Finding cover when somebody calls in sick. |
| `rule_parser` | A written rule → a constraint, without an LLM. |
| `holiday_balance`, `sick_balance` | Entitlement, used, booked, left. |
| `hierarchy`, `departments` | Role ladder and supervisory cover; roster-group boundaries. |
| `payroll_report` | Hours and wages for a range. |
| `mailer`, `llm`, `google_auth` | Resend, Anthropic, Google. |
| `roster_import`, `file_import` | Parse uploaded rosters into weeks. |

### Data

| Collection | Holds |
|---|---|
| `users`, `user_sessions`, `password_resets` | Accounts. Sessions and resets expire through TTL indexes. |
| `shops` | One document per shop, including `departments` and per-group `department_settings` overlays. |
| `employees` | Staff, with `departments` and per-group `department_roles`. |
| `holidays` | Absence records: `scope` is `employee`, `shop` or `sick`. |
| `fixed_shifts`, `ai_rules` | Pinned templates; locked system rules plus custom ones. |
| `rosters` | One document per generated version, shifts embedded. |
| `activity_logs`, `payment_transactions`, `roster_imports` | Audit trail, billing, uploaded imports. |
| `correction_dismissals` | Suggestions the manager refused or applied — **stored**, because a decision cannot be derived from the data that prompted it. |

### Roster groups

A group is a **workspace**, not a dropdown filter (feedback.md §10–11).

- The browser sends the selected group as `X-Roster-Group`. With no header the
  shop's first group is used.
- `ShopScope` exposes the *effective* shop: the shop document with the group's
  `department_settings` laid over it (`services/departments.effective_shop`).
- **Group-local:** hours, shift templates, role ladder, supervisory roles,
  imported weeks, demand and shape history, ownership, preferences, versions,
  scoped AI rules.
- **Shop-wide:** weekly caps, paid hours, working days, rest, leave,
  double-booking. A shared employee's shifts in another group reach the solver
  as an *external commitment*: they spend hours and a working day, never count
  as coverage.
- A group's name is also a **key** — in `employees.departments`,
  `department_roles`, `rosters.department`, `department_settings` and AI rules.
  That is why the server cannot rename a group that is in use.

## Request flow: generating a roster

`POST /api/roster/generate` (`routes/rosters.py`)

1. Resolve the group; build the effective shop.
2. If billing is enforced and the user is not Pro, check the free-plan limit.
3. Refuse if the week is already approved — a second approved roster for one
   week would be read as two weeks of history.
4. If rebalancing, carry over the shifts the manager pinned or added as extra.
5. Load the group's approved rosters; compute preference weights and the
   demand profile from them.
6. Store a random seed on the roster, so a version can be reproduced.
7. Build the training-evidence context, then call `scheduler`.
8. Optionally ask the LLM for a summary. A failure here never fails the
   request — the roster is returned without one.
9. Insert as the next version, write an activity-log entry, return.

**Approval.** A draft is approved explicitly; rule breaks need force-approval
with a recorded reason. An approved week is a record: generate, rebalance and
manual edits are refused on it, and only a sick report changes it directly.
Unapprove reopens it and takes it back out of the learning — nothing is cached,
so clearing the flag *is* the unlearn. A week that has finished cannot be
reopened, and there is only ever one approved roster per week (CLAUDE.md §3).

## Frontend

```
frontend/src/
  pages/        one file per screen (routes below)
  components/   AppLayout (shell + sidebar), AuthShell (signed-out frame),
                RosterGroupSelect, ConfirmDialog (themed confirmations),
                modals, print sheet
  context/      AuthContext — user, login, signup, Google, session restore
  lib/api.js    axios client, token storage, shared formatters and labels
  index.css     all styling
```

**Routes** — `/login`, `/forgot-password`, `/reset-password` (signed out);
`/` dashboard, `/onboarding` shop settings, `/employees[/:id]`, `/calendar`
holidays, `/fixed-shifts`, `/rules`, `/roster`, `/past`, `/import`,
`/sick-report`, `/reports/hours`, `/reports/learning`, `/pricing`,
`/payment/*` (signed in).

**Auth.** The token lives in `localStorage` ("keep me signed in") or
`sessionStorage` (not), chosen by `setToken` in `lib/api.js`. One request
interceptor attaches it; a 401 clears it so the app falls back to sign-in.
The backend also accepts an httpOnly `session_token` cookie but never sets one,
so the Bearer token is the only live path (SECURITY.md).

**Theming.** Two themes, set by `data-theme="light"` on `<html>` (dark is the
absence of it). `index.js` applies the stored choice before first paint;
the sidebar switch writes it. A new account starts in light mode. Signed-out
pages force light through `AuthShell`.

All colour is a CSS variable, in two families:

- `--t-*` — the theme tokens used by every signed-in page: canvas and
  surfaces, hairlines, five text tones, accent, warn, danger, and translucent
  washes.
- `--si-*` — the sign-in family, scoped to `.si-page`.

Each screen's styles sit under its own class prefix — `db-` dashboard, `esp-`
employees, `wr-` roster, `ss-` shop settings, `nv-` sidebar, `si-` sign-in and
so on — and `ui-*` are shared text and surface helpers. Rules for adding
colour are in DECISIONS.md (ADR-016) and TEST_PLAN.md.

**Shell.** `AppLayout` loads `/shop` for the roster-group switcher and listens
for the `roster:shop-changed` event, which Shop Settings dispatches after a
save so the sidebar updates without a refresh. Only the primary group has a
Dashboard.

## Rules for changing the code

Each is stated in the code or in CLAUDE.md; none is a new convention.

1. **The scheduler stays pure** — no database, network or framework imports.
2. **Shop data goes through `ShopScope`.** No unscoped queries, no raw
   `db.<collection>` in a route.
3. **Derive state, never store it** (CLAUDE.md §5). The exception is a
   decision that cannot be derived — see `correction_dismissals`.
4. **Never invent data** (CLAUDE.md §9). Report a gap instead.
5. **Optional integrations degrade honestly.** The app must boot with
   `MONGO_URL`, `DB_NAME` and `JWT_SECRET` alone.
6. **Legal limits are shop-wide.** They never reset at a group boundary.
7. **Frontend colour comes from tokens.** A literal colour is correct in one
   theme and wrong in the other.
8. **Frontend API calls go through `lib/api.js`**, so credentials and the
   roster group cannot be forgotten.
9. **Confirm destructive actions with `useConfirm()`**, not `window.confirm`
   (ADR-020). Five older call sites still use the native one (MEMORY.md).

## Where to look

| To change… | Start in |
|---|---|
| How a week is built | `services/scheduler.py`, CLAUDE.md §1–2 |
| What a hand edit may do | `services/roster_validation.py` |
| What approval refuses | `services/compliance.py`, CLAUDE.md §4 |
| A group's settings | `services/departments.py`, `routes/shop.py` |
| Hours under a name, wages | `services/payroll_report.py`, `shift_paid_hours` |
| A screen's layout | its file in `pages/` plus its prefix in `index.css` |
| Colours or themes | `index.css` — the `:root` and `[data-theme="light"]` token blocks |
| Sign-in | `pages/Login.js`, `components/AuthShell.js`, `context/AuthContext.js` |
