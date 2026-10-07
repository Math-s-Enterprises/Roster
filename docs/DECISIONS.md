# Roster — Decisions

Choices that look arbitrary until you know why. Each entry says what was
decided, the reason **as the code or docs record it**, and where to read more.
Where no reason is written down, the entry says so rather than guessing.

Permanent decisions live here; the *current state* of the project lives in
[MEMORY.md](MEMORY.md). The scheduling rules themselves are in
[../CLAUDE.md](../CLAUDE.md) and are not repeated.

To add one, copy the shape below and take the next number. Never edit the
reason of an old entry to suit a new choice — add a new entry that supersedes
it and say which.

---

## Scheduling

### ADR-001 — The scheduler is a pure module
**Decision.** `services/scheduler.py` takes plain dicts and returns a plain
dict. No database, no network, no framework imports.
**Why.** So it can be tested exhaustively without a server. Everything else in
the backend is "plumbing around this module".
**Source.** `scheduler.py` module docstring.

### ADR-002 — Legal limits win over coverage
**Decision.** Under-16 curfew and weekly hour caps are never relaxed, not even
to cover the shop. The solver reports a gap it could not lawfully fill.
**Why.** "Software cannot invent a legally-eligible employee"; an unfillable
gap is a staffing problem for a human, surfaced as a critical issue.
**Source.** `scheduler.py` docstring, rule 4.

### ADR-003 — Learning is counting, not machine learning
**Decision.** Preference weights count how often things happened in approved
rosters and act as a tie-breaker between people who are all allowed to work a
slot. No model is trained.
**Why.** It is called "learning" because that is the product language; the
docstring warns that improving it means tuning frequency heuristics. An offline
ML experiment did not beat the baseline and stays outside production.
**Source.** `services/learning.py`; `docs/ML_ROLE_EXPERIMENT.md`;
`docs/WORK_QUEUE.md`.

### ADR-004 — Custom rules parse without an LLM; LLM compiles need approval
**Decision.** A deterministic parser turns common written rules ("Sarah never
works Sundays") into constraints and approves them automatically. Rules the
parser cannot read can be compiled by Anthropic, but stay unenforced until a
person approves the result.
**Why.** Before the parser, a rule saved without an API key displayed as
enabled and silently did nothing, "which is worse than not offering the
feature". A deterministic parse is "auditable and reversible"; approval stops a
model's misreading from quietly changing how people are scheduled.
**Source.** `services/rule_parser.py`; `routes/ai_rules.py`.

### ADR-005 — Row order is presentation only
**Decision.** `employee_order` sets the order of the roster grid and exports.
It never changes who gets hours first — the job ladder does.
**Why.** So grouping the night staff together cannot quietly promote them.
**Source.** `models.py`, comment on `employee_order`.

### ADR-006 — The longest shift is capped at 12 hours
**Decision.** `ABSOLUTE_MAX_SHIFT_HOURS = 12`; every use is the lower of the
shop's own `max_shift_hours` and this.
**Why.** It was 11, apparently confused with the 11-hour daily *rest*
entitlement — a different quantity. Eleven hours off in each 24 implies up to
13 worked. Set to 12 at the shop's request, which leaves the rest period intact.
**Source.** `scheduler.py`, comment on the constant. The roster page's own
check once hard-coded 11 as well; it now reads the shop setting.

### ADR-007 — Minimum rest is floored: the API at 10, the UI at 11–20
**Decision.** The API accepts 10–24 hours. Shop Settings only accepts 11–20.
**Why.** Eleven is the statutory floor and the default. The API floor exists so
a shop that must go below it reaches ten, "rather than to zero" — it was `ge=0`,
which let the rest rule be switched off by typing a number. A roster below the
statutory figure still reports every breach and needs force-approval. The UI is
stricter by product choice: 11 is the lowest a manager can set, and above 20
leaves too little of the day to roster.
**Source.** `models.py`, comment on `min_rest_hours`.

---

## State and approval

### ADR-008 — Approved weeks are locked records
**Decision.** Generate, rebalance and manual edits are refused on an approved
week. Unapprove reopens it and takes it back out of the learning. A finished
week cannot be reopened. There is one approved roster per week, ever. The one
exception is a sick call.
**Why.** Approval is when a roster becomes the schedule people work *and* joins
what the scheduler learns from. Two approved rosters would count as two worked
weeks everywhere downstream. A 6am sick call cannot wait for a reopen.
**Source.** CLAUDE.md §3; `routes/rosters.py`.

### ADR-009 — Derive state; store only decisions
**Decision.** Setup progress, preference weights, the demand curve and
familiarity are recomputed on every use, never cached.
**Why.** A stored `step_3_done` flag "starts lying the moment the data behind
it changes". The exception is `correction_dismissals`: a manager's "no" to a
suggestion cannot be derived from the data that prompted it.
**Source.** CLAUDE.md §5; `db.py`, comment on `correction_dismissals`.

---

## Multi-tenancy and groups

### ADR-010 — One scope object builds every query
**Decision.** `ShopScope` binds a `shop_id` at the start of a request and builds
every filter. Routes use `scope.employees`, `scope.rosters` and so on.
**Why.** In the prototype, isolation depended on about forty hand-written
`{"shop_id": …}` filters; one omission was a cross-tenant leak. Now an unscoped
query cannot be expressed through the scope.
**Source.** `app/tenancy.py` docstring.

### ADR-011 — Roster groups are workspaces inside one shop
**Decision.** A group owns its hours, role ladder, supervisory roles, history
and learning, stored as an overlay under `department_settings`. Employment and
legal facts stay shop-wide, and a shared employee's shifts in another group
reach the solver as an external commitment.
**Why.** A group that only filtered the list quietly taught one group from the
other and gave a shared employee a fresh hours budget in each. Separate shops
were rejected: they would split tenancy, billing, leave and employment across
one employer.
**Source.** feedback.md §10–11; `services/departments.py`.
**Consequence.** A group's name is also a key in five places, so the server
cannot rename a group that is in use.

---

## Security and accounts

### ADR-012 — Bearer tokens carry a version counter
**Decision.** Each JWT carries the user's `token_version`; changing a password
increments it.
**Why.** A bearer token cannot be revoked, so every one already issued would
keep working until it expired. A timestamp cutoff failed on sub-second
precision — "that was not the first attempt" — and a counter has no windows and
no clock in it.
**Source.** `security.py`, `create_access_token`.

### ADR-013 — Reset tokens are stored hashed
**Decision.** Only the SHA-256 of a reset token is stored.
**Why.** A database leak must not hand out anything usable to reset an account.
SHA-256 suffices because the token is already 256 bits of randomness.
**Source.** `security.py`.

### ADR-014 — Optional integrations degrade honestly
**Decision.** The app boots with `MONGO_URL`, `DB_NAME` and `JWT_SECRET` alone.
Anthropic, Resend, Google and Stripe are optional and say so when off.
**Why.** A feature that fails only when someone uses it is worse than one that
says up front it is unavailable.
**Source.** `config.py` header; `GET /imports/capabilities`.

### ADR-015 — Billing enforcement is a server switch, off by default
**Decision.** `BILLING_ENFORCED` gates generation for non-Pro users at
`FREE_PLAN_ROSTER_LIMIT`. Default off.
**Why.** So local development is unrestricted.
**Open.** Whether to enforce it for customers is undecided (CLAUDE.md §13). The
roster page hard-codes `overLimit = false`, so with enforcement on a user sees
the server's 402 message instead of the designed upgrade banner.
**Source.** `config.py`; `routes/rosters.py`.

---

## Frontend

### ADR-016 — Colour comes from theme tokens, never literals
**Decision.** Signed-in screens colour themselves from `--t-*` variables or the
shared `ui-*` classes. No hex values, no `rgba()` of a fixed colour, no Tailwind
`text-white/40`, `bg-black/30` or `text-cyan-400`.
**Why.** A literal is right in the theme it was written in and wrong in the
other. Measured on the light canvas, `cyan-400` is 1.61:1 and white-on-beige is
worse; the minimum for text is 4.5:1. This was found repeatedly by eye, which is
the argument for a rule.
**Exceptions.** Modal scrims and confetti are deliberately literal.
**Gotcha.** The global `input:focus` rule is `!important`. An input nested in a
bordered control must override it explicitly, and the control carries focus
through `:focus-within`.
**Known shortfall.** Two faint tokens measure about 4.3:1 on raised panels.
They are used for placeholders and hints, not body text.
**Source.** `index.css`, the token blocks and their comments.

### ADR-017 — Signed-out pages share one frame and are always light
**Decision.** Sign-in, forgot and reset password all render inside `AuthShell`,
which forces the light theme while it is mounted and restores the stored one on
leaving.
**Why.** A recovery link that opened onto a differently built page reads as a
phishing clone. Forcing the theme means signing out of light mode and out of
dark mode land on the same screen. The stored preference is never touched.
**Source.** `components/AuthShell.js` docstring.

### ADR-018 — "Keep me signed in" chooses where the token lives
**Decision.** Ticked: `localStorage`, surviving a closed browser. Unticked:
`sessionStorage`, cleared when it closes. Changing a password keeps whichever
store was in use.
**Why.** Email and Google sign-in authenticate only with the Bearer token — the
server reads a session cookie but never sets one — so the store genuinely
decides whether you are still signed in tomorrow. Defaulting to "keep" on a
password change would silently turn a session-only sign-in into a remembered
one.
**Source.** `lib/api.js`, `setToken`.

### ADR-019 — A new account opens in light mode
**Decision.** Creating an account sets the theme to light. Ordinary sign-in
leaves the saved theme alone.
**Why.** A product decision. It is set only after the account exists, so a
failed sign-up never changes anyone's saved preference.
**Source.** `context/AuthContext.js`, `signup`.

### ADR-020 — Confirmations use our own dialog, not `window.confirm`
**Decision.** Destructive actions ask through `useConfirm()` from
`components/ConfirmDialog.js`, which draws a themed dialog and returns the
answer as a promise. Cancel is focused first. Without a provider it falls back
to the native confirm, so it still asks.
**Why.** The browser draws its own confirm box in its own font and colours,
whatever theme the app is in. Owning the dialog means owning what the native one
gave for free: focus, Tab, Escape, and not cancelling when a text selection
drags off the dialog. Cancel is the default because for a destructive action the
safe choice is the one that does nothing.
**Consequence.** On Shop Settings a removal only edits the list on screen — it
is final on **Save changes** — so the dialog says that rather than implying it
is instant. Five older confirmations still use `window.confirm` (MEMORY.md).
**Source.** `components/ConfirmDialog.js` docstring; its tests.
