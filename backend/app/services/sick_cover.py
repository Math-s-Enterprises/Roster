"""Finding cover when somebody calls in sick.

WHY THIS IS NOT THE SOLVER
--------------------------
The solver refuses to break a rule. That is correct when it is building a
week from nothing — there is always another arrangement to try. It is wrong
at 6am when one person has phoned in and the shop opens in an hour: the
manager's real choice is not "cover it legally or leave it empty", it is
"which rule do I bend, and who do I ask".

So this ranks EVERYBODY and says plainly what each would cost. The list is
never empty while anyone could physically do it. The manager decides, and
their decision is recorded against the roster.

THE HARD FLOOR
--------------
Four things are never offered, however short the shop is:

    under-16 curfew        law, not policy — overriding exposes the owner
    over 12 hours          the maximum shift length
    overlapping hours      nobody can be in two places
    booked annual leave    somebody's holiday is not the manager's to take

Everything else — over contract, a sixth day, an unfamiliar start, a
requested day off — is offered with the cost stated.

Note that "already working that day" is NOT a block. Somebody on 14:00-22:00
can take a 06:00-14:00 shift; that is a long day, not an impossibility, and
the 12-hour ceiling catches it if it goes too far.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.services import availability as avail
from app.services import hierarchy
from app.services.scheduler import (
    ABSOLUTE_MAX_SHIFT_HOURS,
    DAYS,
    MIN_REST_HOURS,
    MAX_WORKING_DAYS,
    paid_hours,
    shift_duration_minutes,
    shift_paid_hours,
    shop_breaks_paid,
    to_minutes,
    violates_minor_curfew,
)


# Below this, two shifts on one day are really one long stint rather than a
# split shift somebody went home in the middle of.
MIN_SPLIT_GAP_MINUTES = 60


def _overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Do two shifts on the same day share any minute?

    Overnight shifts are extended past midnight so a 23:00-07:00 and an
    06:00-14:00 on the same day are correctly seen to clash.
    """
    a0, a1 = to_minutes(a_start), to_minutes(a_end)
    b0, b1 = to_minutes(b_start), to_minutes(b_end)
    if a1 <= a0:
        a1 += 24 * 60
    if b1 <= b0:
        b1 += 24 * 60
    return a0 < b1 and b0 < a1


def _adjacent(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Do two shifts run into each other with no real break between?

    A few minutes is not a break — somebody handed a 06:00-14:00 and a
    14:05-22:00 has worked sixteen hours, whatever the paperwork says.
    """
    a0, a1 = to_minutes(a_start), to_minutes(a_end)
    b0, b1 = to_minutes(b_start), to_minutes(b_end)
    if a1 <= a0:
        a1 += 24 * 60
    if b1 <= b0:
        b1 += 24 * 60
    gap = max(b0 - a1, a0 - b1)
    return gap < MIN_SPLIT_GAP_MINUTES


def rank_cover(
    *,
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    roster: Dict[str, Any],
    absent_id: str,
    day: str,
    start: str,
    end: str,
    week_start: str,
    history_rosters: Optional[List[Dict[str, Any]]] = None,
    leave_dates: Optional[Dict[str, Set[str]]] = None,
    date_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Everybody who could take this shift, best first, with the cost of each."""
    shifts = roster.get("shifts", [])
    absent = next((e for e in employees if e["employee_id"] == absent_id), {})
    history = avail.build_shift_history(history_rosters or [])
    breaks_paid = shop_breaks_paid(shop)
    span = shift_duration_minutes(start, end) / 60
    ranks = hierarchy.rank_map(shop)
    absent_rank = hierarchy.rank_of(absent.get("role"), ranks)

    # What everyone is already doing this week, minus the shift being covered.
    worked: Dict[str, float] = {}
    spanned: Dict[str, float] = {}
    days_on: Dict[str, Set[str]] = {}
    same_day: Dict[str, List[Dict[str, Any]]] = {}

    for shift in shifts:
        eid = shift.get("employee_id")
        if eid == absent_id and shift.get("day") == day:
            continue
        if shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick"):
            continue
        if not (shift.get("start") and shift.get("end")):
            continue
        worked[eid] = worked.get(eid, 0.0) + shift_paid_hours(shift)
        spanned[eid] = spanned.get(eid, 0.0) + (
            shift_duration_minutes(shift["start"], shift["end"]) / 60
        )
        days_on.setdefault(eid, set()).add(shift.get("day"))
        if shift.get("day") == day:
            same_day.setdefault(eid, []).append(shift)

    candidates: List[Dict[str, Any]] = []
    for employee in employees:
        eid = employee["employee_id"]
        if eid == absent_id or employee.get("past_staff"):
            continue

        blocked = _hard_block(
            employee, day, start, end, span,
            same_day.get(eid, []), leave_dates or {}, date_iso,
        )
        if blocked:
            continue

        breaks = _what_breaks(
            employee, day, start, end,
            worked.get(eid, 0.0), spanned.get(eid, 0.0),
            days_on.get(eid, set()), history, week_start, breaks_paid, shop,
            shifts,
        )
        candidates.append({
            "employee_id": eid,
            "name": employee.get("name", ""),
            "role": employee.get("role", ""),
            "clean": not breaks,
            "breaks": breaks,
            "why": _why(employee, day, start, end, worked.get(eid, 0.0),
                        history, week_start, same_day.get(eid, [])),
            "_sort": _sort_key(
                employee, absent, absent_rank, ranks, start, end,
                worked.get(eid, 0.0), history, week_start, days_on.get(eid, set()),
                len(breaks),
            ),
        })

    candidates.sort(key=lambda c: c.pop("_sort"))
    return {
        "day": day, "start": start, "end": end,
        "absent": absent.get("name", ""),
        "candidates": candidates,
        "clean": [c for c in candidates if c["clean"]],
    }


def _hard_block(
    employee: Dict[str, Any],
    day: str,
    start: str,
    end: str,
    span: float,
    their_shifts_today: List[Dict[str, Any]],
    leave_dates: Dict[str, Set[str]],
    date_iso: Optional[str],
) -> Optional[str]:
    """The four things never offered. Returns a reason, or None to allow."""
    if not avail.is_active(employee):
        return "no longer working here"

    if violates_minor_curfew(employee, start, end):
        return "under-16 curfew"

    if span > ABSOLUTE_MAX_SHIFT_HOURS:
        return "longer than the maximum shift"

    if date_iso and date_iso in leave_dates.get(employee["employee_id"], set()):
        return "on booked leave"

    for shift in their_shifts_today:
        if _overlaps(start, end, shift["start"], shift["end"]):
            return "already working those hours"

        # Two shifts that touch are one long stint, and the ceiling applies
        # to the whole of it: 06:00-14:00 followed by 14:00-22:00 is sixteen
        # hours on the floor however it is written down.
        #
        # Two shifts with a real gap are a split shift, which is ordinary in
        # retail — somebody doing the morning and then coming back for the
        # evening rush has been home in between. Summing those would refuse
        # cover that is perfectly reasonable.
        if _adjacent(start, end, shift["start"], shift["end"]):
            combined = (
                shift_duration_minutes(shift["start"], shift["end"]) / 60 + span
            )
            if combined > ABSOLUTE_MAX_SHIFT_HOURS:
                return f"would run {combined:.1f}h straight through"

    return None


def _what_breaks(
    employee: Dict[str, Any],
    day: str,
    start: str,
    end: str,
    worked: float,
    spanned: float,
    days_on: Set[str],
    history: Dict[str, Dict[str, Set[str]]],
    week_start: str,
    breaks_paid: bool,
    shop: Dict[str, Any],
    all_shifts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """What it would cost to give this person the shift. Empty means nothing."""
    out: List[Dict[str, Any]] = []
    adding = paid_hours(start, end, breaks_paid=breaks_paid)
    span = shift_duration_minutes(start, end) / 60

    band = avail.contract_span_band(employee)
    if band:
        _, target = band
        if spanned + span > target:
            out.append({
                "rule": "contract",
                "detail": f"{spanned + span - target:.1f}h over their "
                          f"{target:.1f}h contract",
            })
    else:
        cap = avail.weekly_hour_cap(employee, week_start)
        if worked + adding > cap:
            out.append({
                "rule": "weekly_hours",
                "detail": f"{worked + adding - cap:.1f}h over their {cap:.0f}h limit",
            })

    max_days = int((shop or {}).get("max_working_days") or MAX_WORKING_DAYS)
    if day not in days_on and len(days_on) >= max_days:
        out.append({
            "rule": "days",
            "detail": f"would be day {len(days_on) + 1} of their week",
        })

    if day in (employee.get("preferred_days_off") or []):
        out.append({"rule": "day_off", "detail": "asked for this day off"})

    # Offered rather than blocked, and only for a sick call. Eleven hours is
    # health and safety, so it sits high in the list — but at 6am with the
    # shop opening in an hour, a manager who has to choose between a short
    # turnaround and an unattended shop should be shown the choice rather
    # than told nobody is available.
    rest = _rest_gap(employee["employee_id"], day, start, end, all_shifts)
    if rest is not None:
        out.append({
            "rule": "rest",
            "detail": f"only {rest:.1f}h rest since their last shift "
                      f"({MIN_REST_HOURS:g}h required)",
        })

    if avail.check_familiarity(employee, start, end, history).warning:
        out.append({
            "rule": "unfamiliar",
            "detail": "has never worked a shift starting near this time",
        })

    window = avail.check_availability(employee, day, start, end)
    if not window.allowed:
        out.append({"rule": "availability", "detail": window.reason})

    return out


def _why(
    employee: Dict[str, Any],
    day: str,
    start: str,
    end: str,
    worked: float,
    history: Dict[str, Dict[str, Set[str]]],
    week_start: str,
    their_shifts_today: List[Dict[str, Any]],
) -> str:
    """One line saying why this person is being suggested.

    A bare name tells the manager nothing; they then have to open three other
    screens to decide. This is the difference between a list and an answer.
    """
    bits = []
    entry = history.get(employee["employee_id"]) or {}
    times = (entry.get("patterns") or set())
    exact = sum(1 for p in times if p == f"{start}-{end}")
    if exact:
        bits.append(f"has worked this exact shift before")
    elif any(abs(to_minutes(s) - to_minutes(start)) <= 60 for s in entry.get("starts", ())):
        bits.append("works this sort of start")

    cap = avail.weekly_hour_cap(employee, week_start)
    headroom = cap - worked
    if headroom > 0:
        bits.append(f"{headroom:.0f}h under their limit")

    if their_shifts_today:
        bits.append("already in that day")
    elif day not in (employee.get("preferred_days_off") or []):
        bits.append("free that day")

    return ", ".join(bits) or "available"


def _sort_key(
    employee: Dict[str, Any],
    absent: Dict[str, Any],
    absent_rank: int,
    ranks: Dict[str, int],
    start: str,
    end: str,
    worked: float,
    history: Dict[str, Dict[str, Set[str]]],
    week_start: str,
    days_on: Set[str],
    break_count: int,
) -> Tuple:
    """Clean candidates first, then by fit.

    Order within a tier, most to least important:
      1. how close their role is to the absent person's
      2. how often they have worked this exact shift
      3. how much room they have left in the week
      4. how few days they are already working
    """
    entry = history.get(employee["employee_id"]) or {}
    pattern = f"{start}-{end}"
    familiar = 1 if pattern in (entry.get("patterns") or set()) else 0
    near = 1 if any(
        abs(to_minutes(s) - to_minutes(start)) <= 60 for s in entry.get("starts", ())
    ) else 0

    role_gap = abs(hierarchy.rank_of(employee.get("role"), ranks) - absent_rank)
    headroom = avail.weekly_hour_cap(employee, week_start) - worked

    return (
        break_count,          # nothing broken first
        role_gap,             # closest role to the person off sick
        -familiar,            # has done this exact shift
        -near,                # or one like it
        -headroom,            # most room left in their week
        len(days_on),         # fewest days already worked
        employee.get("name", ""),
    )


def _week_span(day: str, start: str, end: str) -> Optional[Tuple[int, int]]:
    """A shift as minutes from Monday 00:00, so days compare correctly."""
    if day not in DAYS or not (start and end):
        return None
    base = DAYS.index(day) * 24 * 60
    first = base + to_minutes(start)
    last = base + to_minutes(end)
    if last <= first:
        last += 24 * 60
    return first, last


def _rest_gap(
    employee_id: str,
    day: str,
    start: str,
    end: str,
    all_shifts: List[Dict[str, Any]],
) -> Optional[float]:
    """Rest around this shift, if a neighbouring one leaves too little."""
    mine = _week_span(day, start, end)
    if not mine:
        return None
    required = MIN_REST_HOURS * 60

    for shift in all_shifts:
        if shift.get("employee_id") != employee_id:
            continue
        if shift.get("day") == day:
            continue
        if shift.get("sick") or shift.get("paid_holiday") or shift.get("unpaid_holiday"):
            continue
        theirs = _week_span(shift.get("day"), shift.get("start"), shift.get("end"))
        if not theirs:
            continue
        if mine[0] >= theirs[1]:
            gap = mine[0] - theirs[1]
        elif theirs[0] >= mine[1]:
            gap = theirs[0] - mine[1]
        else:
            continue
        if gap < required:
            return gap / 60
    return None
