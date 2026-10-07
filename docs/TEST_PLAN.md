# Roster — Test plan

What "working" means, what checks it automatically, and what only a person
looking at the screen can check. The honest summary: **the backend is heavily
tested and the frontend is almost entirely checked by hand.**

---

## Automated

| Check | Command | Covers |
|---|---|---|
| Backend suite | `cd backend && python -m pytest` | The scheduler, compliance, validation, availability, learning, imports, email, and the HTTP API. **Must stay green** (CLAUDE.md §12). |
| Frontend tests | `cd frontend && yarn test` | `RosterView.test.js`: four tests of the helpers in `lib/api.js` (availability and leave conflicts, paid hours under the break setting) and a static render of the shift-warning modal. `ConfirmDialog.test.js`: sixteen tests of the confirmation dialog — answers, default focus, Escape, Tab wrapping, backdrop and drag-select, a second prompt, unmounting, scroll lock, and the native fallback. |
| CSS variables | `cd frontend && yarn check:css` | Every CSS variable used is defined. It does **not** catch literal colours. |
| Leave runs | `cd frontend && yarn check:runs` | Consecutive absence records render as one row. |
| Production build | `cd frontend && yarn build` | The frontend compiles. |

**Backend size.** 40 files and 864 test functions. `docs/WORK_QUEUE.md`
reports 873 passed and 1 expected failure when it was last updated. The largest
files are `test_api.py` (184), `test_demand.py` (64), `test_availability.py`
(61) and `test_slot_scheduling.py` (57).

**Not covered.** No end-to-end tests, no test that renders a whole screen, no
visual or contrast checks, and no CI — nothing runs any of this on a
pull request. `data-testid` hooks exist on the main controls, so end-to-end
tests are cheap to start.

## Before every commit

```
cd backend  && python -m pytest
cd frontend && yarn check:css && yarn build
```

Then the manual pass below for whatever you touched.

---

## Manual checklist

Every item here is something that was once broken and found by eye. Do the
sections that match the change; do all of A for any styling change.

### A. Both themes — every screen
Switch Light and Dark with the sidebar switch and look at each screen:
Dashboard, Shop Settings, Employees, Holidays, Fixed Shifts, AI Rules, Roster,
Past Rosters, Import, Sick Report, Hours & Wages, What It Learned.

- [ ] No text is hard to read — look hardest at placeholders, small tags,
      warnings and counts.
- [ ] Every boxed section is closed on all four sides, at any number of items.
- [ ] Nothing names a colour in its text ("bright green…") — the wording must
      be true in both themes.
- [ ] Date, time and dropdown controls look like the rest of the page.
- [ ] Clicking into a field inside a bordered control gives **one** focus
      highlight, not a box inside a box.
- [ ] Open every modal and drawer in Light mode.

### B. Sign-in and accounts
- [ ] Wrong password: "That email and password do not match", the email is
      kept, the cursor lands in the password field.
- [ ] Tick **Keep me signed in**, close the browser completely, reopen: still
      signed in. Untick, repeat: asked to sign in.
- [ ] Sign out from Light mode and from Dark mode land on the same page.
- [ ] Open `/roster` while signed out, sign in: you land on `/roster`.
- [ ] Create an account: the app opens in Light mode.
- [ ] Forgot password: the confirmation reads the same for a real and an unknown
      address. Reset with the emailed link, then sign in with the new password.
- [ ] Show/Hide on the password field — in Edge there is one control, not two.

### C. Shop Settings and roster groups
- [ ] Change a setting and save: "Unsaved changes" clears **without a refresh**.
- [ ] Add a roster group and save: it appears in the sidebar switcher without a
      refresh.
- [ ] Switcher by keyboard: Up, Down, Home, End, Enter, Space, Escape, Tab.
- [ ] Minimum rest below 11 or above 20: a message appears and Save is disabled.
- [ ] Supervisory toggle on a role: save, reload, it is still set.
- [ ] Number fields refuse negative values — all except *Adjustment in hours* on
      the holiday adjust dialog, which exists to deduct.
- [ ] Renaming a group that has employees or rosters is refused by the server,
      with the server's own message.
- [ ] Removing a roster group, a role or a recipient asks in the app's own
      dialog, never the browser's, in both themes. Keep it, Escape and a click
      outside all leave the item; Remove takes it off the list; nothing is final
      until Save changes. The first group's Remove is disabled.

### D. Roster
- [ ] Extend a shift to 11.5 h with a 12 h shop maximum: accepted. To 12.5 h:
      refused, naming the length and the limit.
- [ ] With **Breaks are paid** off, the hours under a name are lower than the
      cell hours by the break; with it on, they match.
- [ ] Approve; click a worked shift on the approved week: only a sick report is
      offered. Generate on that week is refused.
- [ ] Findings tabs (Needs attention, From your edits, Advisories, Against the
      usual): each box closed on every side.
- [ ] Print preview: no sidebar, full width, white background, the Hours column
      present, nothing clipped.
- [ ] PDF and CSV match the grid.

### E. Employees
- [ ] Scroll a long list: the selected person's details stay in view.
- [ ] Edit and Adjust Holiday modals are readable in Light mode.
- [ ] The under-16 warning is readable in both themes.

### F. Import
- [ ] Upload a spreadsheet: review shows weeks and people; warning text is
      readable in Light mode.
- [ ] With no `ANTHROPIC_API_KEY`: PDF and photo show as unavailable, with the
      reason.
- [ ] **Week beginning** dates a CSV that carries no date.

### G. Archive and reports
- [ ] Past Rosters: **Open** on a version loads *that* version, not the
      approved one.
- [ ] Hours & Wages counts approved weeks only; the total row ignores filters.
- [ ] Sick Leave: record an illness, then delete it; the allowance recalculates.

### H. Responsive
- [ ] 375, 768 and 1440 px: nothing overflows sideways; the sidebar becomes a
      drawer below 900 px.

---

## Worth automating first

If end-to-end tests are ever started, these three give the most for the least:

1. Sign in, sign out, and the redirect back to where you were going.
2. Generate a roster, edit a shift, approve it, and attempt an edit on the
   approved week.
3. Toggle the theme and confirm it survives a reload.

Tooling is not chosen; Playwright is the usual fit for a React app.
