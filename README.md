# Roster

Staff scheduling for shops. A manager sets up the shop, its people and its
rules once; Roster then builds a covered week that respects working-time law,
booked holidays, contracts and preferences — and emails it to the team.

Managers sign in. Staff never do: they receive their roster by email.

---

## What it does

- **Builds a week** from opening hours, staff availability, fixed shifts and
  learned history, rather than from a blank grid.
- **Refuses to break the law.** Daily rest, under-16 curfews, maximum shift
  length and the 48-hour average are constraints, not warnings.
- **Learns from your own rosters.** Import past weeks and generated weeks
  start to look like the ones you actually run.
- **Tracks holiday and sick leave**, including entitlement and what is unpaid.
- **Reports hours and wages** from approved rosters only, so a draft never
  reaches payroll.

## Stack

| | |
|---|---|
| Frontend | React 19, React Router 7, Tailwind, CRACO. Yarn, not npm. |
| Backend | FastAPI, Python 3.11+, Motor/PyMongo |
| Database | MongoDB |
| Optional | Anthropic (roster summaries, photo/PDF reading, rule compiling), Resend (email), Google sign-in, Stripe (billing) |

Everything optional degrades honestly: if a key is missing, the feature says
so in the interface rather than failing when you use it.

## Running it

Full instructions, including prerequisites and every optional integration, are
in **[SETUP.md](SETUP.md)**. The short version:

```bash
# backend — from backend/
cp .env.example .env          # set MONGO_URL, DB_NAME, JWT_SECRET
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8001

# frontend — from frontend/
cp .env.example .env          # REACT_APP_BACKEND_URL
yarn install
yarn start
```

Then open http://localhost:3000 and create an account.

**Use `yarn`, not `npm`.** The project is pinned to Yarn 1.22 and has a
`yarn.lock`; `npm install` creates a competing lockfile.

### Environment

Required: `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, and `CORS_ORIGINS` must list
your frontend's exact origin — no trailing slash, and `localhost` and
`127.0.0.1` count as different origins.

Optional: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `GOOGLE_CLIENT_ID`,
`STRIPE_SECRET_KEY`. See `backend/.env.example` for the full list and what
each one switches on.

## Layout

```
backend/
  app/routes/      HTTP endpoints — auth, shop, rosters, holidays,
                   imports, reports, ai_rules, payments
  app/services/    the real work — scheduler, compliance, holiday_balance,
                   sick_balance, learning, payroll_report, file_import…
  tests/           pytest
frontend/
  src/pages/       one file per screen
  src/components/  AppLayout (shell), AuthShell (signed-out frame), modals
  src/lib/api.js   API client, token storage, shared formatters
  src/index.css    all styling, including the light/dark theme tokens
```

### Screens

`/` dashboard · `/onboarding` shop settings and first-run setup ·
`/employees` · `/calendar` holidays · `/fixed-shifts` · `/rules` AI rules ·
`/roster` the week · `/past` archive · `/import` past rosters ·
`/sick-report` · `/reports/hours` · `/reports/learning`

## Tests and checks

```bash
cd backend && pytest                 # scheduling rules, API
cd frontend && yarn test             # component tests
cd frontend && yarn check:css        # every CSS variable used is defined
cd frontend && yarn check:runs       # leave runs render as real weeks
```

The backend tests are the ones that matter most: they encode the scheduling
rules, and a change that breaks one is a change to what the shop is allowed
to do.

## Before you change anything

Three documents are worth reading first, because they record decisions that
look arbitrary until you know why:

- **[AGENTS.md](AGENTS.md)** — the scheduling rules and the reasoning behind
  them. Which rules never bend, why an approved week is locked, why state is
  derived rather than stored.
- **[DESIGN.md](DESIGN.md)** — the visual system. Colour encodes seniority,
  not identity; the grid is data, not decoration.
- **[SETUP.md](SETUP.md)** — running it, and troubleshooting.

Two conventions that cause the most trouble when missed:

**Theme tokens, never literal colours.** All styling lives in
`frontend/src/index.css` and reads CSS variables, so both themes work. A
hardcoded hex looks right in the theme you developed in and wrong in the
other. `yarn check:css` catches undefined variables, not literal colours —
that one is on you.

**Approved rosters are records, not plans.** Reopening one starts a new
version and stops the week counting towards what the scheduler has learned.
