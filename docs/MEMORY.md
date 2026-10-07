# Roster — Project memory

The **current state** of the project: what is done, what is known to be wrong,
what comes next. Permanent choices live in [DECISIONS.md](DECISIONS.md); the
queue of planned scheduler work lives in [WORK_QUEUE.md](WORK_QUEUE.md).

Keep this short. When you finish something, move it out of "Known issues"; when
you find something, add it. If a line here would still be true in a year, it
belongs in DECISIONS.md instead. The last commit touching this file is its date.

---

## Where things stand

- **Backend:** mature. A pure solver, 864 test functions, learning from each
  shop's own approved weeks, roster groups as separate workspaces.
- **Frontend:** every screen has been rebuilt to its design handoff, with light
  and dark themes. Testing is almost entirely manual (TEST_PLAN.md).
- **Not yet customer-ready.** CLAUDE.md §13 lists what stands in the way:
  Docker, CI, rate limiting, error tracking, backups, GDPR paperwork, email
  setup, and the billing decision.

## Done recently

**Backend**
- Previous-week overnight coverage repaired; leave checks added to the
  contract top-up and hour-fitting passes.
- Training evidence captured at generation and approval, kept apart from
  learned preferences.
- Closing rules work end to end ("a manager or supervisor at close").
- Roster groups made into real workspaces with their own settings and learning.
- The supervisory flag is now stored per role and honoured by the solver.
- Booked leave now reduces the holiday balance before the roster is approved.
- Paid hours follow the shop's **Breaks are paid** setting on the edit,
  sick-cover and extra-staff paths, and in the roster totals.

**Frontend**
- All screens rebuilt; light (beige and burnt orange) and dark (black and
  emerald) themes with a sidebar switch.
- Sign-in, forgot and reset password on one shared frame, with a working
  **Keep me signed in**.
- Roster-group switcher in the sidebar; Shop Settings refreshes after saving
  and the sidebar updates without a page reload.
- The roster page opens the right week and version from Past Rosters.
- CSV export on Employees, Past Rosters, Hours & Wages and Sick Leave.
- A themed confirmation dialog (`useConfirm`), used on Shop Settings for
  removing a roster group, a role or a recipient.

## Known issues

Roughly in order of importance. Each says where to look.

1. **A roster group in use cannot be renamed.** The server has no rename: a new
   name reads as "remove the old group, add a new one", and removal is refused
   while anything uses it. Shop Settings offers Rename on the main group, but it
   only works while nothing belongs to it. A proper fix is a rename endpoint
   that migrates the name in all five places listed in ARCHITECTURE.md.
2. **Credentials and personal data are in the repository.** `memory/PRD.md`
   holds an owner password; `.claude/settings.local.json` is tracked. See
   SECURITY.md, gap 7. Quick to fix; should not wait.
3. **Security gaps before customers:** no rate limiting, unverified sign-up
   email, token readable by page scripts, no security headers, no data
   delete/export. See SECURITY.md.
4. **The frontend paywall is hard-disabled** (`overLimit = false` in
   `RosterView.js`) while the server can enforce a limit. With
   `BILLING_ENFORCED` on, users see a raw 402 message, not the upgrade banner.
   The billing decision itself is open (DECISIONS.md, ADR-015).
5. **`DESIGN.md` is out of date.** It describes the dark system only — Inter at
   weight 500, no gradients, nothing on the light theme. The real rules are in
   `index.css` and DECISIONS.md (ADR-016). Until it is rewritten, anything that
   reads it will pull the UI back.
6. **`AGENTS.md` and `CLAUDE.md` have drifted** by about 30 lines, in the
   section on closing behaviour. `CLAUDE.md` appears to be the newer. Make one
   canonical and the other a one-line pointer.
7. **`memory/PRD.md` is stale.** `docs/PRD.md` supersedes it; delete it or
   replace it with a pointer.
8. **Pricing and Payment Result still use dark-only colours** and are hard to
   read in Light mode. Rarely reached: the Upgrade link only appears when the
   (disabled) limit is hit, and Stripe redirects land on the result pages.
9. **Frontend test coverage is thin, and there is no CI.** Two test files — the
   roster helpers and the confirmation dialog — and no end-to-end tests.
10. **Export is built in the browser.** No server export endpoint exists, so
    large datasets and any audit-grade export are not possible yet.
11. **PDF and photo import need `ANTHROPIC_API_KEY`.** Without it, only
    spreadsheet and CSV work.
12. **`RosterView.js` is about 2,550 lines.** It is the hardest file to change
    safely; changes there deserve the full manual pass in TEST_PLAN.md.
13. **Five confirmations still use the browser's `window.confirm`:** deleting an
    employee, two on Fixed Shifts, one on AI Rules and one on Sick Report. They
    look out of place in both themes; each is a few lines to move to
    `useConfirm` (ADR-020).
14. **Toast notifications are always dark.** `App.js` renders
    `<Toaster theme="dark">`, so they stay dark in Light mode.

## Next

**Already queued** (WORK_QUEUE.md, items 4 and 5, not started):
- Design and evaluate the next learned model — it must not increase constraint
  breaches, and the first model is not a production candidate.
- Replace the fixed three-repeat suggestion trigger with contextual learning.

**Suggested, not queued**
1. Rotate the owner password; untrack `.claude/settings.local.json`; remove or
   replace `memory/PRD.md`.
2. Reconcile `AGENTS.md` with `CLAUDE.md`; rewrite `DESIGN.md`.
3. Add CI that runs the backend suite and `yarn check:css` / `yarn build`.
4. Rate limiting and email verification on sign-up.
5. A server-side group rename.
