# Running Roster locally

Two programs plus a database, all running at once:

```
  Terminal 1                    Terminal 2                Background
  ──────────                    ──────────                ──────────
  backend  (FastAPI/Python)     frontend (React)          MongoDB
  http://localhost:8001    ←→   http://localhost:3000  →  localhost:27017
```

You open `http://localhost:3000`. That page calls the backend on `:8001`,
which reads and writes MongoDB.

**Only MongoDB is required to run the app.** Anthropic, Resend, Google and
Stripe are all optional — leave their keys blank and those features report
themselves unavailable while everything else works. `GET /api/health` shows
you exactly what is live.

---

## Step 1 — Prerequisites

```powershell
python --version    # 3.10+
node --version      # 18+
yarn --version      # npm install -g yarn  (if missing)
```

- **Python** — https://www.python.org/downloads/ (tick "Add Python to PATH")
- **Node.js** — https://nodejs.org (LTS)

**MongoDB** — pick one:
- *Docker (easiest):* `docker run -d -p 27017:27017 --name roster-mongo mongo:7`
- *Atlas (no install):* free tier at https://www.mongodb.com/cloud/atlas
- *Local install:* https://www.mongodb.com/try/download/community

---

## Step 2 — Configuration

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

Open `backend\.env` and set:

- `MONGO_URL` — your Atlas string, or `mongodb://localhost:27017`
- `JWT_SECRET` — generate one:
  `python -c "import secrets; print(secrets.token_hex(32))"`

Everything else can stay blank for now. `frontend\.env` usually needs no edits.

---

## Step 3 — Install

**Terminal 1 (backend):**

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1        # prompt should show (venv)
pip install -r requirements.txt
```

> If PowerShell blocks the activate script, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

> A **virtual environment** keeps this project's packages separate from other
> Python projects, so version conflicts can't happen. Activate it in every new
> terminal before running the backend.

**Terminal 2 (frontend)** — split the terminal with the `+` icon:

```powershell
cd frontend
yarn install
```

---

## Step 4 — Run

**Terminal 1:**

```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8001
```

The startup log tells you which integrations are active:

```
Roster API starting (env=development)
  AI features:   DISABLED (set ANTHROPIC_API_KEY)
  Email:         DISABLED (set RESEND_API_KEY)
  Google login:  DISABLED (set GOOGLE_CLIENT_ID)
  Billing:       DISABLED (set STRIPE_SECRET_KEY)
```

**Terminal 2:**

```powershell
cd frontend
yarn start
```

Then open http://localhost:3000 and **create an account** via the Sign up tab.
(There is no seeded demo login any more — a hardcoded password in source was a
security problem.)

Interactive API docs: http://localhost:8001/docs

---

## Step 5 — Run the tests

```powershell
cd backend
.\venv\Scripts\Activate.ps1
pip install mongomock_motor          # test-only dependency
pytest
```

61 tests, no database or network needed. `tests/test_scheduler.py` pins the
four non-negotiable scheduling rules; `tests/test_api.py` covers auth, tenant
isolation and validation end-to-end.

---

## Optional integrations

Add any of these to `backend\.env` and restart the backend.

### AI features — summaries, roster-photo OCR, rule compiling
1. Get a key at https://console.anthropic.com
2. `ANTHROPIC_API_KEY=sk-ant-...`

### Emailing rosters to staff
1. Sign up at https://resend.com and create an API key
2. `RESEND_API_KEY=re_...`
3. To email anyone other than yourself, verify a domain and set
   `EMAIL_FROM=Roster <roster@yourdomain.com>`

### Google sign-in
1. Google Cloud Console → APIs & Services → Credentials → **Create OAuth client ID**
2. Application type **Web application**; add `http://localhost:3000` under
   *Authorised JavaScript origins*
3. `GOOGLE_CLIENT_ID=...apps.googleusercontent.com`

No client secret is needed — the browser gets an ID token and the backend
verifies its signature. The button only appears once this is configured.

### Billing
1. `STRIPE_SECRET_KEY=sk_test_...`
2. `python setup_stripe.py` to create the products and prices
3. For webhooks locally: `stripe listen --forward-to localhost:8001/api/stripe/webhook`,
   then put the printed `whsec_...` in `STRIPE_WEBHOOK_SECRET`
4. Set `BILLING_ENFORCED=true` only when you actually want to gate access

---

## Verifying the scheduling rules

1. **AI Rules page** — six rules show a 🔒 *System rule* badge with the toggle
   disabled and no delete button. They cannot be changed via the API either.
2. **Full-day coverage** — set hours longer than your max shift (e.g. 09:00–21:00
   with a 9h max), add 4+ employees, generate. Each day should be covered by
   back-to-back shifts (09:00–15:00, 15:00–21:00) with no gap and no shift over
   the cap.
3. **Unfillable gaps** — put everyone on leave for a day and generate. You should
   get a red *Uncovered shifts* panel, not a silently empty day.

---

## Troubleshooting

**`RuntimeError: Required environment variable 'MONGO_URL' is not set`**
→ `backend\.env` is missing or misplaced. It must sit beside `requirements.txt`.

**`ServerSelectionTimeoutError`, or requests hang**
→ MongoDB isn't running, or `MONGO_URL` is wrong. On Atlas, check your current
IP is allowlisted under Network Access.

**CORS errors in the browser console**
→ `CORS_ORIGINS` in `backend\.env` must include `http://localhost:3000`.

**Frontend can't reach the backend**
→ Check `REACT_APP_BACKEND_URL` in `frontend\.env`. Create React App bakes env
vars in at build time, so **restart `yarn start`** after changing it — hot
reload won't pick it up.

**`Port 8001 is already in use`**
→ `netstat -ano | findstr :8001`, then `taskkill /PID <number> /F`

**Backend changes don't apply**
→ Confirm `--reload` is set, and check Terminal 1 for a syntax error that
stopped the reload.

---

## Project layout

```
backend/
  app/
    config.py          every environment variable, documented in one place
    db.py              Mongo client, collection handles, index setup
    models.py          request/response schemas (Pydantic)
    security.py        password hashing, JWTs, auth dependency
    tenancy.py         shop scoping — makes cross-tenant queries impossible
    main.py            app assembly, middleware, startup
    services/
      scheduler.py     THE SOLVER — pure, no I/O, fully unit-tested
      learning.py      historical preference counts
      llm.py           Anthropic: summaries, OCR, rule compiling
      mailer.py        Resend
      google_auth.py   Google ID token verification
      shop_service.py  shop defaults + the locked system rules
    routes/            one module per resource
  tests/
    test_scheduler.py  the four non-negotiable rules
    test_api.py        end-to-end HTTP, auth, tenant isolation
  server.py            compatibility shim for `uvicorn server:app`

frontend/src/
  lib/api.js           the one configured axios client
  context/AuthContext  who is signed in
  components/          AppLayout, GoogleSignInButton, ui/ (shadcn)
  pages/               one per route
```
