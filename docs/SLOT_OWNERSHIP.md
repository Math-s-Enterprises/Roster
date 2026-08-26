# Slot ownership, rebalance fixes, and day rebalance — plan

Three changes, from watching the roster behave on real data.

---

## 1. The shift belongs to the person who usually works it

**Today:** slots are filled by role priority — most senior role first, with
learned affinity only as a late tie-breaker. So Martin (Ambient Manager) can
be handed Monday 06:00 ahead of Emma, who has opened that shift for months.

**Wanted:** if Emma usually works Monday 06:00, it is Emma's shift. Nobody
else is offered it while she is available.

**Why familiarity does not already do this:** familiarity only asks *"has this
person ever worked a shift starting near this time?"* Martin has — the
imported sheet shows him on Sunday 06:00. So he passes the check and then wins
on role seniority. The question here is not who *can* work it but who
*normally does*.

### The rule

A slot has an **established owner** when, across the learned window, one
person worked it at least **60%** of the times it ran, over at least **4**
occurrences. Both thresholds matter: 3 of 4 is a habit, 1 of 1 is an accident.

Ownership is per **(day, slot)**. Emma may own Monday 06:00–16:00 without
owning Saturday 06:00–16:00; they are different shifts in the manager's head
and should be here too.

When filling a slot:

1. **Established owner, available** → theirs. Normal ranking is skipped.
2. **Owner unavailable** → next most frequent person for that same slot, by
   history.
3. **Nobody has history for it** → role priority, exactly as today.

### What this does to rule 3

Rule 3 — *hours go to the most senior role first* — still governs every slot
without an established owner, and still governs how many hours each person
gets overall. What changes is that a slot with a settled owner is no longer
put out to seniority.

This is a deliberate narrowing and `CLAUDE.md` must be updated to say so.
The justification: the manager's own rosters are the evidence, and they
already give Emma that shift. A rule that overrides the shop's actual practice
is not encoding seniority, it is ignoring the data.

### What it does not do

Ownership never beats a hard constraint. An owner who is on leave, curfewed,
at their hour cap, inside the 11-hour rest window, or already on a five-day
week does not get the slot — the fallback applies.

---

## 2. Rebalance leaves too many people on

**Observed:** roster generated without Emma. Emma added by hand to Monday
06:00 and pinned. Rebalance. Result — Emma, Megan *and* Martin all on Monday
morning, where the shop runs two.

**Cause,** in `_staff_by_slots`:

```python
already = Counter(
    (s["start"], s["end"]) for s in self.result.shifts ...
)
```

A shift already on the day only cancels a demand slot when its times match
**exactly**. Monday's slot list holds `06:00–16:00` twice. Megan's fixed shift
is `06:00–16:00` and consumes one. Emma's pinned `06:00–14:00` matches
nothing, so the second slot still reads as unfilled and Martin is sent to it.

The manager is left deleting the person the solver added *because of* their
own pin.

**Fix:** a body already on the floor at that opening consumes the slot, even
if the finish differs. Match on start time within a tolerance, then take the
closest end time. Each placed shift may cancel at most one slot, so a genuine
double-up still gets filled.

**Test that must pass:** pinned 06:00–14:00 plus fixed 06:00–16:00 against a
two-slot Monday leaves exactly two people at 06:00, and the third is not
placed.

---

## 3. Rebalance one day only

**Wanted:** the week is right except Wednesday. Somebody asks for two more
hours. Add them, press **Rebalance Day** on Wednesday, and let the rest of the
week alone.

**Approach** — reuses machinery that already exists rather than adding a
second solver path. Every shift on the other six days is treated as locked, so
it cannot move. Only the target day is re-solved.

- Pinned and fixed shifts on the target day are respected as now.
- Manually added hours on the target day are respected, because editing pins.
- Weekly hour caps still count the locked days, so giving somebody two extra
  hours on Wednesday correctly reduces what they can take elsewhere *that
  day* — it cannot silently push them over their week.
- Nothing on another day changes. That is the guarantee being sold.

**UI:** two distinct actions.

| | Does |
|---|---|
| **Rebalance** | the whole week, keeping pins |
| **Rebalance Day** | one day, everything else frozen |

`Rebalance Day` belongs on the day column header, where the day is already the
subject.

---

## 4. Extra staff — deliberately above the requirement

**Wanted:** a renovation, a delivery, a busy Saturday. The manager picks a
person, a day and a time, and adds them **as extra** — on top of normal
staffing, not instead of it.

### Extra is the inverse of pinned, and that is the whole design

The two features are one idea seen from opposite sides:

| | Means | Consumes a demand slot? |
|---|---|---|
| **pinned** | "*this* person fills this slot" | **yes** |
| **extra** | "this person *as well as* the slots" | **no** |

That single bit decides everything else, and it is why the manager's two
examples give different answers with no special-casing:

- Emma **pinned** at Monday 06:00 → she fills one of the two slots, Megan's
  fixed shift fills the other, **Martin is not placed**. (Issue #2.)
- Emma **extra** at Monday 06:00 → both slots still need filling, so Megan and
  Martin take them and **Emma is on top**. Three people, deliberately.

Both are correct. The difference is entirely whether the shift counts toward
the requirement, which is exactly what the manager is expressing when they
choose "pin" versus "add extra".

### Rules for an extra shift

- **Never removed by rebalance.** It is a decision, like a pin.
- **Never counted as overstaffing.** The whole point is to exceed the normal
  level, so it must not generate an issue saying so.
- **Hours still count.** They are really working: it draws on their weekly
  cap, their contracted hours and their five-day limit. An extra shift that
  quietly created a sixth working day would be a trap.
- **Legal limits still apply.** Curfew, the 12-hour ceiling, the 11-hour rest
  gap and booked leave are not the manager's to override here — that is what
  the sick-cover flow is for, with its explicit recorded overrides.
- **Marked in the grid and in reports**, so a week that cost more than usual
  says why.

### Priority during rebalance

1. Extra shifts — kept
2. Pinned shifts — kept
3. Fixed shifts — kept
4. Established slot owners — preferred (§1)
5. Everything else — adjusted, moved or dropped first

---

## Order

1. **#2 first.** It is a bug, it is small, and it is actively costing edits
   every time rebalance is used.
2. **#1 next.** Largest change and the one that should most reduce edits.
3. **#3 last.** Additive, and easier to reason about once #2 is right —
   day rebalance leans on the same slot-consumption logic.

Re-run `ml/measure_edit_burden.py` after each. If edits per roster do not
fall, the change did not do what it was meant to.
