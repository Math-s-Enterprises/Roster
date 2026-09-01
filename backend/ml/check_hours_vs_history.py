"""Does the solver give people the hours they normally work?

    python ml/check_hours_vs_history.py --email you@example.com --week 2026-08-31

THE CLAIM BEING TESTED
----------------------
That the solver fills the first-ranked person up to their CONTRACT CAP and
only then moves on, rather than to the hours that person normally works. If
true, somebody who averages 16.5h a week gets 26h, and somebody who averages
33h gets pushed to 38 — nobody is over their limit, and the roster is still
wrong, because the limit was never the target.

WHAT A NON-ZERO ANSWER LOOKS LIKE, STATED BEFORE RUNNING
--------------------------------------------------------
The `drift` column is materially non-zero and SIGNED CONSISTENTLY: the people
ranked first are above their historical average, the people ranked last are
below it. That is the front-loading pattern.

If drift is small, or scattered in both directions with no relation to rank,
the claim is wrong and the front-loading theory should be dropped rather than
built on. A measurement that cannot come back negative is not a measurement —
this one can, and if it does, say so.

WEEKS SOMEBODY WAS ABSENT ARE EXCLUDED
--------------------------------------
A fortnight's leave in a 24-week window drags an average down by about 8%,
and that is not what they normally work — it is what they worked while away.
So a person's average is taken over the weeks they actually appear, not over
every week in the window. Reported as `weeks` so a thin average is visible
rather than quietly trusted.

A STUDENT'S AVERAGE IS TWO AVERAGES
-----------------------------------
Term time and summer break are different regimes, and mixing them produces a
number that describes neither — too high to be a term-time target and too low
to be a summer one. Where `weekly_hour_cap` differs between the historical
week and the target week, the two are split and reported separately.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services import hours_target                       # noqa: E402
from app.services.demand import (                           # noqa: E402
    RECENCY_HALF_LIFE_WEEKS, _week_start_date, build_profile,
)
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import compute_weights, latest_per_week  # noqa: E402
from app.services import scheduler as sched                 # noqa: E402
from app.services.scheduler import paid_hours, solve_roster  # noqa: E402

ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def run(email: str, week: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    names = {e["employee_id"]: e.get("name") or e["employee_id"] for e in employees}
    holidays = await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)
    approved = await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500)

    if not approved:
        sys.exit("No approved rosters — there is no history to compare against.")

    # The target week is held out for the same reason as in
    # `check_swap_value.py`: it carries full weight in the profile
    # (`age == 0`), so generating it grades the solver on a week it learned
    # from. It would also put the same week on both sides of the drift
    # comparison, which cannot help but agree with itself.
    if any(r.get("week_start") == week for r in approved):
        print(f"\n  NOTE: {week} is already approved — held out of the "
              f"history so the comparison is not self-fulfilling.")
        approved = [r for r in approved if r.get("week_start") != week]
    if not approved:
        sys.exit("No history left once the target week is held out.")

    breaks_paid = bool(shop.get("breaks_are_paid"))

    # ONE roster per week, exactly as every learning path does it.
    #
    # Skipping this is how the first run of this script reported Teja
    # averaging 56.6h — above his 40h cap and above the EU 48h limit. A week
    # with two approved rosters had both counted, and summing them into the
    # same week entry doubled it. `demand.py`, `slot_owners.py`,
    # `corrections.py` and `learning.py` all dedupe; a diagnostic that does
    # not is measuring a shop that does not exist.
    deduped = latest_per_week(list(approved))
    if len(deduped) < len(approved):
        print(f"\n  NOTE: {len(approved) - len(deduped)} duplicate week(s) "
              f"dropped — {len(approved)} rosters cover {len(deduped)} weeks.")

    # Historical hours per person per week, keyed by week so a person who
    # was absent simply has no entry for it rather than a zero.
    per_week: Dict[str, Dict[str, float]] = defaultdict(dict)
    for roster in deduped:
        week_start = roster.get("week_start")
        for shift in roster.get("shifts") or []:
            if shift.get("paid_holiday") or shift.get("unpaid_holiday"):
                continue
            if not (shift.get("start") and shift.get("end")):
                continue
            per_week[shift["employee_id"]][week_start] = (
                per_week[shift["employee_id"]].get(week_start, 0.0)
                + paid_hours(shift["start"], shift["end"],
                             breaks_paid=breaks_paid)
            )

    profile = build_profile(
        shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week,
    )
    ordered = sort_employees(employees, shop)
    roster = solve_roster(
        shop, ordered, holidays, fixed, rules, week,
        compute_weights(approved), profile, history_rosters=approved,
    )
    generated: Dict[str, float] = defaultdict(float)
    for shift in roster.get("shifts") or []:
        if shift.get("paid_holiday") or shift.get("unpaid_holiday"):
            continue
        generated[shift["employee_id"]] += paid_hours(
            shift["start"], shift["end"], breaks_paid=breaks_paid)

    rank = {e["employee_id"]: i for i, e in enumerate(ordered)}

    # A FLAT AVERAGE OVER 30 WEEKS DESCRIBES NOBODY.
    #
    # Two ways it lies, both visible in the reference shop's own data:
    #
    #   * somebody who left in February still has a 30-week "usual" of 26h
    #     and correctly gets 0 now, which reads as a 26-hour shortfall
    #   * somebody who has cut back to two days a week still carries the
    #     average of the six months before they cut back
    #
    # The second is the case the manager described: "he used to work any of
    # the seven days, but from now on he might have decided to work only on
    # two days." So hours decay exactly as the demand curve does (§7b) —
    # reusing RECENCY_HALF_LIFE_WEEKS rather than inventing a second number
    # for the same idea.
    target = _week_start_date(week)

    # THE SAME FUNCTION THE SOLVER USES, not a second opinion.
    #
    # This script used to compute its own decayed average over all history
    # while the solver aimed at the median of the last TREND_WEEKS. The two
    # disagreed by about 3 hours on anybody whose hours were changing — so
    # the diagnostic was marking the solver down for missing a target it was
    # never aiming at. A measurement that does not use the same definition as
    # the thing it measures is measuring something else.
    solver_usual = hours_target.usual_hours(
        deduped, week, breaks_paid=breaks_paid)

    def weighted_usual(weeks: Dict[str, float]) -> float:
        total = weight_sum = 0.0
        for week_start, worked in weeks.items():
            started = _week_start_date(week_start)
            if started is None:
                continue
            age = max(0.0, (target - started).days / 7.0)
            weight = 0.5 ** (age / RECENCY_HALF_LIFE_WEEKS)
            total += worked * weight
            weight_sum += weight
        # Divided by the SUM OF WEIGHTS, not the count — dividing weighted
        # hours by a plain count reports everybody as working less than they
        # do (§7b).
        return total / weight_sum if weight_sum else 0.0

    # HISTORY IS NOT A TARGET ON ITS OWN — AVAILABILITY BOUNDS IT.
    #
    # Somebody who worked 26h a week for six months and has since dropped to
    # Saturdays and Sundays cannot be given 26h, and reporting the shortfall
    # as a scheduling failure is wrong: two weekend shifts is what they are
    # available for, so ~16h IS their correct week. Recency weighting alone
    # is too slow here — an 8-week half-life still carries most of the old
    # average — but their availability says it immediately and exactly.
    #
    # So the ceiling is: the longest slot they could work on each day they
    # are available for, best days first, capped at the working-day limit.
    max_days = int(shop.get("max_working_days") or sched.MAX_WORKING_DAYS)

    # LEAVE BOOKED IN THE WEEK BEING GENERATED ALSO BOUNDS IT.
    #
    # Somebody with three days booked off cannot reach a full week's hours,
    # and scoring them against one reports a shortfall for a holiday the
    # manager approved. Emma and Jamie both showed as badly under-rostered
    # on the reference shop for exactly this reason.
    #
    # Note this is leave in the TARGET week, not leave in the history —
    # history is already handled, because a holiday shift is skipped when
    # the per-week hours are counted.
    off_dates: Dict[str, set] = defaultdict(set)
    for holiday in holidays:
        if holiday.get("scope") not in ("employee", "unavailable", "sick"):
            continue
        employee_id = holiday.get("employee_id")
        start = holiday.get("date")
        if not (employee_id and start):
            continue
        end = holiday.get("end_date") or start
        for offset in range(7):
            date_iso = (target + timedelta(days=offset)).isoformat()
            if start <= date_iso <= end:
                off_dates[employee_id].add(ORDER[offset])

    def availability_ceiling(employee: Dict[str, Any]) -> Tuple[float, int]:
        """Hours they could physically be given, and days lost to leave."""
        employee_id = employee["employee_id"]
        booked_off = off_dates.get(employee_id, set())
        best = []
        for day in ORDER:
            if day in booked_off:
                continue            # they are not there to be rostered
            options = [
                paid_hours(start, end, breaks_paid=breaks_paid)
                for start, end in (profile.slots_for(day) or [])
                if avail.check_availability(employee, day, start, end).allowed
                and not sched.violates_minor_curfew(employee, start, end)
            ]
            best.append(max(options) if options else 0.0)
        return sum(sorted(best, reverse=True)[:max_days]), len(booked_off)

    # MEASURED FROM THE NEWEST ROSTER, NOT THE TARGET WEEK.
    #
    # Measuring from the target week reported everybody as "last seen 3w ago"
    # on this shop, because the newest approved roster was three weeks before
    # the week being generated. That is the gap to the target, which is the
    # same for everyone and says nothing about anybody. What matters is
    # whether they stopped appearing BEFORE the others did.
    newest = max(
        (d for d in (_week_start_date(w) for w in
                     {w for weeks in per_week.values() for w in weeks})
         if d), default=target,
    )

    def weeks_since_last_seen(weeks: Dict[str, float]) -> float:
        seen = [_week_start_date(w) for w in weeks]
        latest = max((d for d in seen if d), default=None)
        return (newest - latest).days / 7.0 if latest else 999.0

    print(f"\n{shop.get('name', '?')} — generated week of {week}")
    print(f"{len(approved)} approved weeks of history, newest {newest}\n")
    print(f"  {'#':>2} {'who':20}{'role':20}{'cap':>6}{'aim':>7}"
          f"{'weeks':>6}{'got':>7}{'drift':>8}")
    print("  " + "-" * 74)

    # A NAMED RECORD, NOT A 12-FIELD TUPLE.
    #
    # The tuple version crashed on its second read: a field was added at one
    # unpacking site and not the others, and Python only complained at the
    # third one, several screens away from the change.
    class Row(NamedTuple):
        rank: int
        employee_id: str
        aim: float
        weeks: int
        got: float
        drift: float
        cap: float
        role: str
        gap: float
        salaried: bool
        usual: float
        ceiling: float
        days_off: int

    rows: List[Row] = []
    dormant: List[Row] = []
    for employee in ordered:
        employee_id = employee["employee_id"]
        weeks = per_week.get(employee_id) or {}
        if not weeks:
            continue
        usual = solver_usual.get(employee_id, weighted_usual(weeks))
        cap = avail.weekly_hour_cap(employee, week)
        ceiling, days_off = availability_ceiling(employee)
        got = generated.get(employee_id, 0.0)
        # The smallest of the three is what they can actually be given.
        aim = min(usual, ceiling, cap)
        row = Row(
            rank=rank[employee_id], employee_id=employee_id, aim=aim,
            weeks=len(weeks), got=got, drift=got - aim, cap=cap,
            role=employee.get("role") or "?",
            gap=weeks_since_last_seen(weeks),
            salaried=avail.is_full_time_contract(employee),
            usual=usual, ceiling=ceiling, days_off=days_off,
        )
        # Somebody who stopped appearing well before everybody else has
        # almost certainly left. Their shortfall is not a scheduling failure
        # and counting it as one drowns the shop's real drift.
        (dormant if row.gap > RECENCY_HALF_LIFE_WEEKS else rows).append(row)

    for row in rows:
        flag = "  <<" if abs(row.drift) >= 5 else ""
        at_cap = " =CONTRACT" if row.salaried else (
            " =CAP" if abs(row.got - row.cap) < 0.01 and row.got > 0 else "")
        why = ""
        if row.days_off:
            why = f"  {row.days_off}d booked off"
        elif row.ceiling < row.usual - 0.5:
            why = f"  only free for {row.ceiling:.0f}h"
        elif row.gap >= 2:
            why = f"  LAST ROSTERED {row.gap:.0f}w BEFORE THE OTHERS"
        print(f"  {row.rank:>2} {names[row.employee_id][:19]:20}"
              f"{row.role[:19]:20}{row.cap:6.0f}{row.aim:7.1f}{row.weeks:6}"
              f"{row.got:7.1f}{row.drift:+8.1f}{flag}{at_cap}{why}")

    if dormant:
        print(f"\n  Excluded — stopped appearing over "
              f"{RECENCY_HALF_LIFE_WEEKS:g} weeks before the newest roster,")
        print("  so probably leavers still marked active. Their 'shortfall'")
        print("  is not a scheduling fault:")
        for row in sorted(dormant, key=lambda r: -r.gap):
            print(f"    {names[row.employee_id][:19]:20}last rostered "
                  f"{row.gap:.0f} weeks before the others, "
                  f"used to work {row.usual:.1f}h")

    print()
    print("=" * 78)
    print("IS IT FRONT-LOADING?")
    print("=" * 78)
    if len(rows) < 2:
        print("  Not enough people with history to tell.")
        return

    # SALARIED AND HOURLY ARE JUDGED SEPARATELY, BECAUSE THEY ARE OWED
    # DIFFERENT THINGS.
    #
    # A salaried full-timer is paid for their contract whether or not the
    # rota uses it, so landing on that figure is CORRECT and reading it as
    # over-scheduling would be wrong. Somebody paid by the hour is owed no
    # particular number, so the hours they actually work are the only
    # available statement of what is normal for them.
    #
    # Lumping the two together is what produced "UNCLEAR" on the reference
    # shop: six salaried people correctly at their contract cancelled out
    # eleven hourly people wrongly under their usual.
    salaried = [r for r in rows if r.salaried]
    hourly = [r for r in rows if not r.salaried]

    print(f"  SALARIED ({len(salaried)}) — owed their contract, so landing")
    print("  on it is right:")
    off_contract = [r for r in salaried if abs(r.got - r.cap) >= 0.01]
    if not off_contract:
        print("      all on their contracted hours. Correct.")
    for row in off_contract:
        print(f"      {names[row.employee_id][:19]:20}{row.got:5.1f}h against "
              f"a {row.cap:g}h contract")

    print(f"\n  HOURLY ({len(hourly)}) — owed nothing in particular, so their")
    print("  own recent hours bounded by their availability is the only")
    print("  statement of what is normal:")
    over = [r for r in hourly if r.drift > 2]
    under = [r for r in hourly if r.drift < -2]
    print(f"      more than 2h above their aim: {len(over)}")
    print(f"      more than 2h below their aim: {len(under)}")
    print()

    # Anybody who stopped appearing before the others is a suspected leaver,
    # and a suspected leaver is not evidence of misallocation. Separated
    # rather than silently dropped, because the manager is the only one who
    # knows which it is.
    suspected_leavers = [r for r in under + over if r.gap >= 2]
    genuine = [r for r in under + over if r.gap < 2]

    if not hourly:
        print("  Nobody is paid hourly here; there is nothing to distribute.")
    elif genuine and len(genuine) > len(hourly) / 4:
        print(f"  MISALLOCATED — {len(genuine)} of {len(hourly)} hourly staff "
              f"are more than 2h off what they")
        print("  could be given, and are still being rostered, so this is not")
        print("  explained by anybody leaving:")
        for row in sorted(genuine, key=lambda r: r.drift)[:8]:
            print(f"      {names[row.employee_id][:19]:20}aim "
                  f"{row.aim:5.1f}h -> {row.got:5.1f}h  ({row.drift:+.1f})")
    else:
        print("  NOT MISALLOCATED — what is left after excluding suspected")
        print("  leavers is within normal variation. Do not build a")
        print("  distribution rule on this.")

    if suspected_leavers:
        print(f"\n  CHECK THESE FIRST — off their aim, but they also stopped")
        print("  being rostered before everybody else. Resigned, or a real")
        print("  shortfall? The app cannot tell; you can:")
        for row in sorted(suspected_leavers, key=lambda r: -r.gap):
            print(f"      {names[row.employee_id][:19]:20}"
                  f"{row.got:5.1f}h vs aim {row.aim:5.1f}h, last rostered "
                  f"{row.gap:.0f}w before the others")

    # IS THE WEEK THE RIGHT SIZE AT ALL?
    #
    # "Everybody is short" has two completely different causes and they need
    # opposite fixes:
    #
    #   * the week is the right size and the hours go to the wrong people —
    #     a distribution problem, fixed by changing who is picked
    #   * the week is SMALLER than a week this shop actually runs — a demand
    #     problem, fixed in demand.py, and no distribution rule touches it
    #
    # Reading the second as the first would produce a rule that shuffles a
    # shortfall around instead of removing it. So the totals are compared
    # before anything is concluded about allocation.
    weekly_totals: Dict[str, float] = defaultdict(float)
    for weeks in per_week.values():
        for week_start, worked in weeks.items():
            weekly_totals[week_start] += worked

    total_weight = total_hours = 0.0
    for week_start, worked in weekly_totals.items():
        started = _week_start_date(week_start)
        if started is None:
            continue
        age = max(0.0, (target - started).days / 7.0)
        weight = 0.5 ** (age / RECENCY_HALF_LIFE_WEEKS)
        total_hours += worked * weight
        total_weight += weight
    usual_week = total_hours / total_weight if total_weight else 0.0
    generated_total = sum(generated.values())

    print(f"\n{'=' * 78}\nIS THE WEEK THE RIGHT SIZE?\n{'=' * 78}")
    print(f"  a normal week here:  {usual_week:7.1f}h")
    print(f"  this week generated: {generated_total:7.1f}h")
    short = usual_week - generated_total
    print(f"  difference:          {-short:+7.1f}h "
          f"({-short / usual_week * 100:+.0f}%)" if usual_week else "")
    print()
    if abs(short) < usual_week * 0.05:
        print("  RIGHT SIZE — the week has the hours it should. Anybody")
        print("  short is short because somebody else got their hours, so")
        print("  this IS a distribution problem.")
    elif short > 0:
        print("  TOO SMALL — the week is missing hours this shop normally")
        print("  works, so people are short of them no matter who gets")
        print("  picked. Fix the demand profile first; a distribution rule")
        print("  would only move the shortfall around.")
        print("  Check `why_empty.py` on the thinnest day before assuming")
        print("  the allocation is at fault.")
    else:
        print("  TOO BIG — the week has more hours than normal, which costs")
        print("  money. Distribution is not the issue.")

    worst = max(rows, key=lambda r: abs(r.drift))
    print(f"\n  Largest single drift: {names[worst.employee_id]} "
          f"{worst.drift:+.1f}h (aim {worst.aim:.1f} -> got {worst.got:.1f})")

    # The average on its own hides the thing that makes it wrong. A single
    # 56-hour week among sevens is a data problem, not a pattern, and it
    # cannot be told from a genuinely long-hours employee without looking.
    print(f"\n{'=' * 78}\nWEEK BY WEEK, SO AN OUTLIER IS VISIBLE\n{'=' * 78}")
    all_weeks = sorted({w for weeks in per_week.values() for w in weeks})
    print(f"  {'who':20}" + "".join(f"{w[5:]:>7}" for w in all_weeks))
    for _, employee_id, *_ in rows:
        weeks = per_week.get(employee_id) or {}
        cells = "".join(
            f"{weeks[w]:7.1f}" if w in weeks else f"{'·':>7}"
            for w in all_weeks
        )
        print(f"  {names[employee_id][:19]:20}{cells}")
    print("\n  '·' is a week they do not appear in, which is excluded from")
    print("  their average rather than counted as a zero.")

    over_cap = [
        (names[employee_id], week, hours)
        for _, employee_id, *_ in rows
        for week, hours in (per_week.get(employee_id) or {}).items()
        if hours > 48
    ]
    if over_cap:
        print("\n  WEEKS ABOVE THE 48h WORKING TIME LIMIT — these are almost")
        print("  certainly a data problem, and they are dragging the average:")
        for who, week, hours in sorted(over_cap):
            print(f"    {who} {week}: {hours:.1f}h")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="Monday, YYYY-MM-DD")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week))


if __name__ == "__main__":
    main()
