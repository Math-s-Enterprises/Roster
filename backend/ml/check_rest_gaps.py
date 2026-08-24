"""Did the manager actually leave 11 hours between shifts?

WHY ASK BEFORE BUILDING
-----------------------
The rest rule is about to become a constraint on roster generation. If the
real rosters break it, making it a hard block would leave the app unable to
reproduce the very schedules it learns from — every generated week would
fight the history. So the honest order is: measure first, then decide whether
to refuse or to warn.

WHAT IT MEASURES
----------------
For each person, every consecutive pair of shifts across the whole workbook,
in real chronological order. The gap is from the end of one to the start of
the next.

Overnight shifts are handled properly: 23:30-07:00 on Monday ends at 07:00 on
TUESDAY, so a 17:00 start on Tuesday is a 10-hour gap, not a 34-hour one.
Getting that wrong would be the difference between "always followed" and
"routinely broken", which is the whole question.

USAGE
-----
    python ml/check_rest_gaps.py "C:\\path\\to\\new roster 26.xlsx"
    python ml/check_rest_gaps.py "...xlsx" --hours 11 --show 40
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.roster_import import (           # noqa: E402
    DAYS, parse_workbook_rows, read_xlsx,
)

MIN_REST_HOURS = 11.0


def _at(week_start: str, day: str, clock: str) -> datetime:
    base = datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=DAYS.index(day))
    hh, mm = (int(x) for x in clock.split(":"))
    return base + timedelta(hours=hh, minutes=mm)


def main(path: Path, minimum: float, show: int) -> int:
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    weeks = [w for w in parse_workbook_rows(read_xlsx(str(path))) if w.week_start]
    print(f"Read {len(weeks)} dated week(s) from {path.name}\n")

    # employee -> [(start, end)] in real time, so overnight shifts land on the
    # right calendar day before anything is compared.
    spans: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for week in weeks:
        for shift in week.shifts:
            if not (shift.start and shift.end):
                continue
            start = _at(week.week_start, shift.day, shift.start)
            end = _at(week.week_start, shift.day, shift.end)
            if end <= start:                      # finishes after midnight
                end += timedelta(days=1)
            spans[shift.employee_name].append((start, end))

    total_pairs = 0
    breaches: list[tuple[float, str, datetime, datetime]] = []

    for name, shifts in spans.items():
        shifts.sort()
        for (_, previous_end), (next_start, _) in zip(shifts, shifts[1:]):
            # Overlapping or same-shift duplicates are a parse artefact, not
            # a rest question.
            if next_start < previous_end:
                continue
            total_pairs += 1
            gap = (next_start - previous_end).total_seconds() / 3600
            if gap < minimum:
                breaches.append((gap, name, previous_end, next_start))

    if not total_pairs:
        print("No consecutive shifts found to compare.")
        return 0

    breaches.sort()
    rate = 100 * (1 - len(breaches) / total_pairs)

    print(f"Rest rule: at least {minimum:g} hours between finishing and starting again")
    print(f"Consecutive shift pairs checked: {total_pairs}")
    print(f"Pairs under {minimum:g}h: {len(breaches)}")
    print(f"Compliance: {rate:.1f}%\n")

    if not breaches:
        print("Every pair leaves the full rest period. The rule was followed.")
        return 0

    by_person: dict[str, int] = defaultdict(int)
    for _, name, _, _ in breaches:
        by_person[name] += 1

    print(f"Shortest {min(show, len(breaches))}:\n")
    width = max(len(b[1]) for b in breaches[:show])
    for gap, name, ended, started in breaches[:show]:
        print(f"    {name:{width}}  {gap:5.1f}h   "
              f"off {ended:%a %d %b %H:%M}  ->  back {started:%a %d %b %H:%M}")

    print(f"\nPeople affected: {len(by_person)}")
    for name, count in sorted(by_person.items(), key=lambda kv: -kv[1])[:12]:
        print(f"    {name:{width}}  {count} time(s)")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--hours", type=float, default=MIN_REST_HOURS,
                        help="minimum rest between shifts (default 11)")
    parser.add_argument("--show", type=int, default=25,
                        help="how many of the worst to list")
    args = parser.parse_args()

    raise SystemExit(main(args.workbook, args.hours, args.show))
