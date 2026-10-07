# Roster — Security

What the application protects, how, and where it does not yet. Everything below
was checked against the code; the file or setting is named so it can be checked
again. Gaps are listed plainly — a security document that only lists strengths
is not one.

[CLAUDE.md](../CLAUDE.md) §13 already records the main gaps between this and
paying customers: Docker, CI, rate limiting, error tracking, backups, GDPR
paperwork (privacy policy, DPA, export/delete), and deciding whether billing is
enforced.

---

## What is protected

### Passwords
- bcrypt with a random salt per password; constant-time comparison.
- A Google-only account has no password and fails closed rather than crashing.
- Policy is **length only**: 8 characters minimum (`models.py`).

### Sign-in and sessions
- Email and Google sign-in issue a Bearer JWT (HS256), expiring after
  `JWT_EXPIRY_DAYS` (default 7).
- Each token carries the user's `token_version`; changing a password increments
  it, which signs the account out everywhere (ADR-012).
- A failed login always returns the same message, "Invalid email or password",
  so the response does not reveal which emails are registered.
- Google ID tokens are verified server-side, including `email_verified`.
- Server-side sessions and password resets expire through MongoDB TTL indexes.

### Password reset
- The emailed token is 256 bits of randomness; only its SHA-256 is stored
  (ADR-013).
- "Forgot password" gives the same answer whether or not the address exists.

### Authorisation and tenancy
- Every shop-data query is built by `ShopScope`, so a route cannot express an
  unscoped one (ADR-007). Unpaginated reads are capped at 1000 documents.
- Rule breaks on approval need force-approval with a recorded reason, written to
  the activity log.

### Secrets and configuration
- `JWT_SECRET` is **required** in production. In development a random one is
  generated per run, which invalidates tokens on restart.
- `.env` files are gitignored; `.env.example` is tracked.
- `/dev/reset` and `/seed-demo` are hard-disabled in production whatever
  `DEV_ROUTES_ENABLED` says.
- CORS is an explicit origin allowlist (`CORS_ORIGINS`), not a wildcard.

### Input and third parties
- Uploads are limited to 25 MB, checked on the server.
- The Stripe webhook is authenticated by its signature; without a configured
  secret it refuses.
- The frontend renders no raw HTML — no `dangerouslySetInnerHTML`.

---

## Known gaps

Ordered roughly by how much they matter before real customers.

1. **No rate limiting or lockout.** Login can be guessed at, sign-up and
   forgot-password can be used to flood an inbox, and import and rule-compile
   calls can run up Anthropic cost. Nothing in the application slows any of it.
2. **Email addresses are not verified on email/password sign-up.** Anyone can
   register an address they do not own. (Google sign-in does verify.)
3. **The Bearer token is readable by page scripts.** It lives in
   `localStorage` or `sessionStorage`, so any injected script could take it.
   The backend accepts an httpOnly `session_token` cookie, which would not have
   this weakness, but nothing ever sets one.
4. **No security headers.** The application sets no CSP, HSTS,
   `X-Frame-Options` or `nosniff`. They need to come from the host or proxy.
5. **Personal data without data-subject tools.** The app stores staff names,
   ages (including under-16s), email addresses, wages, and **sick-leave
   records, which are health data**. There is no endpoint to delete a shop or
   account or to export its data, and no privacy policy or data-processing
   agreement.
6. **Data leaves for a third party.** Photo and PDF imports send page images to
   Anthropic. The roster summary sends the week, shift count, score, cost and up
   to five finding messages — and those messages can name employees.
7. **Credentials and personal data in the repository.**
   - `memory/PRD.md` contains an owner email and the password `demo1234`. The
     code no longer seeds that account; if it exists anywhere, change its
     password.
   - `.claude/settings.local.json` is tracked. It holds one person's local file
     paths and tool history, unrelated to Roster, and should be untracked.
   - An owner email also appears in `docs/vscode/launch.json` and `feedback.md`.

   Removing a line does not remove it from git history.
8. **Dependencies are untriaged.** GitHub reported 19 vulnerabilities on the
   default branch at a recent push (13 high, 6 moderate). Check the current
   number under the repository's Dependabot alerts.
9. **No CI.** Nothing runs the backend suite on a pull request, so a security
   regression is caught only if someone runs it.

## Before real customers

Close gaps 1, 2, 4 and 5 at minimum. Gap 3 is a larger change — set the cookie
on login, then stop returning the token to JavaScript. Gap 7 is quick and
should not wait.

## When you change something

- Any new route reads shop data through `ShopScope`.
- Any new endpoint that accepts a file, sends email or calls the LLM is a
  rate-limiting candidate.
- Any new log line must not contain a password, token or reset link.
- Update this file in the same change.
