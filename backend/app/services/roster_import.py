"""Parse legacy roster spreadsheets into structured shift data.

Real shops keep rosters in Excel, formatted for humans rather than machines.
This module turns that into records the app can store and learn from.

The reference file this was written against is a 29-week retail roster, and
it exhibits everything that makes these files hard:

  * times written with dots, not colons        06.00-16.00
  * a bracketed hour count, spaced any which way  (10) / (8.5) / 10)
  * annotations that carry no scheduling meaning   07.00-15.00(8)*
  * free-text entries that are not shifts          "first aid 9-17.00"
  * absence codes in mixed case                    OFF / off / HOL / N/A
  * a role written once per section, inherited by the rows beneath it
  * summary rows, blank spacer rows, and staff with no shifts at all

The parser is deliberately forgiving: anything it cannot confidently read is
reported rather than guessed at, so a human reviews the ambiguous 2% instead
of silently importing bad data.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# ---------------------------------------------------------------------------
# Absence codes
# ---------------------------------------------------------------------------
# Distinguished because they mean different things for pay and for learning:
#   OFF  — the manager rostered someone else; the person was available.
#          A genuine negative example: "available, not chosen."
#   HOL  — booked, paid holiday. The person was unavailable, so this is NOT
#          evidence about scheduling preference and must not train as one.
#   N/A  — the person marked themselves unavailable (unpaid). Also not a
#          preference signal, but it does say something about availability.
ABSENCE_OFF = "off"
ABSENCE_HOLIDAY = "holiday"
ABSENCE_UNAVAILABLE = "unavailable"

ABSENCE_BANK_HOLIDAY = "bank_holiday"
ABSENCE_SICK = "sick"
ABSENCE_BEREAVEMENT = "bereavement"

_ABSENCE_CODES = {
    "off": ABSENCE_OFF,
    "o": ABSENCE_OFF,
    "hol": ABSENCE_HOLIDAY,
    "hols": ABSENCE_HOLIDAY,
    "holiday": ABSENCE_HOLIDAY,
    "holidays": ABSENCE_HOLIDAY,
    "a/l": ABSENCE_HOLIDAY,
    "annual leave": ABSENCE_HOLIDAY,
    # Bank holidays are paid but not deducted from entitlement, so they are
    # tracked separately from booked holiday.
    "b/hol": ABSENCE_BANK_HOLIDAY,
    "b/hols": ABSENCE_BANK_HOLIDAY,
    "bhol": ABSENCE_BANK_HOLIDAY,
    "b hol": ABSENCE_BANK_HOLIDAY,
    "bank hol": ABSENCE_BANK_HOLIDAY,
    "bank holiday": ABSENCE_BANK_HOLIDAY,
    "n/a": ABSENCE_UNAVAILABLE,
    "na": ABSENCE_UNAVAILABLE,
    "not available": ABSENCE_UNAVAILABLE,
    "unavailable": ABSENCE_UNAVAILABLE,
    "sick": ABSENCE_SICK,
    "s/l": ABSENCE_SICK,
    "sick leave": ABSENCE_SICK,
    "bereavement": ABSENCE_BEREAVEMENT,
    "compassionate": ABSENCE_BEREAVEMENT,
}

# Section headings that describe a group rather than a job title.
_SECTION_ALIASES = {
    "supervisors": "Supervisor",
    "supervisor": "Supervisor",
    "shopfloor": "Shop Floor",
    "shop floor": "Shop Floor",
    "nightshift": "Night Shift",
    "night shift": "Night Shift",
    "nights": "Night Shift",
}

# Rows that are totals/notes rather than people.
_NON_STAFF_TOKENS = {
    "", "hols", "holidays", "training", "total", "totals", "signature",
    "notes", "staff", "name", "names",
}

# 06.00-16.00 (10)   06.00-16.00(10)   6:00-16:00   06.00-16.00 10)   ...(8)*
# Minutes are optional so "8-2pm(6)" and "9-17.00" also parse.
_SHIFT_RE = re.compile(
    r"""^\s*
    (?P<sh>\d{1,2})(?:\s*[.:h]\s*(?P<sm>\d{2}))?   # start  06.00 / 6:00 / 8
    \s*(?P<sap>am|pm)?\s*
    (?:-|–|—|to)\s*                                 # separator
    (?P<eh>\d{1,2})(?:\s*[.:h]\s*(?P<em>\d{2}))?   # end
    \s*(?P<eap>am|pm)?\s*
    (?:\(?\s*(?P<hours>\d{1,2}(?:\.\d+)?)\s*[\)\(]?)?  # (10) / (8.5) / 10) / (9(
    \s*[\)\(\*†‡]*\s*$                              # tolerate trailing typos
    """,
    re.VERBOSE | re.IGNORECASE,
)

# "first aid 9-17.00" — an activity, with times in a looser format.
_ACTIVITY_RE = re.compile(
    r"""^\s*(?P<label>[A-Za-z][A-Za-z\s/&-]{2,}?)\s+
    (?P<sh>\d{1,2})(?:\s*[.:h]\s*(?P<sm>\d{2}))?
    \s*(?:-|–|—|to)\s*
    (?P<eh>\d{1,2})(?:\s*[.:h]\s*(?P<em>\d{2}))?
    \s*\)?\s*$""",
    re.VERBOSE,
)

_WEEK_ENDING_RE = re.compile(
    r"""(?P<day>\d{1,2})\s*(?:st|nd|rd|th)?\s*
        (?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*
        \s*'?(?P<year>\d{2,4})?""",
    re.IGNORECASE | re.VERBOSE,
)
_WEEK_ENDING_RE_ALT = re.compile(
    r"""(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*
        (?P<day>\d{1,2})\s*(?:st|nd|rd|th)?
        \s*'?(?P<year>\d{2,4})?""",
    re.IGNORECASE | re.VERBOSE,
)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class ParsedShift:
    employee_name: str
    role: Optional[str]
    day: str
    start: str
    end: str
    hours: float
    stated_hours: Optional[float] = None   # what the sheet claimed, if given
    activity: Optional[str] = None         # e.g. "first aid"
    overnight: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "employee_name": self.employee_name,
            "role": self.role,
            "day": self.day,
            "start": self.start,
            "end": self.end,
            "hours": round(self.hours, 2),
            "overnight": self.overnight,
        }
        if self.activity:
            data["activity"] = self.activity
        return data


@dataclass
class ParsedAbsence:
    employee_name: str
    role: Optional[str]
    day: str
    kind: str          # off | holiday | unavailable | sick

    def to_dict(self) -> Dict[str, Any]:
        return {
            "employee_name": self.employee_name,
            "role": self.role,
            "day": self.day,
            "kind": self.kind,
        }


@dataclass
class ParsedWeek:
    sheet_name: str
    week_start: Optional[str]              # Monday, ISO
    week_ending_label: Optional[str]
    shifts: List[ParsedShift] = field(default_factory=list)
    absences: List[ParsedAbsence] = field(default_factory=list)
    employees: Dict[str, Optional[str]] = field(default_factory=dict)  # name -> role
    events: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unparsed_cells: List[Dict[str, str]] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return bool(self.week_start and self.shifts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "week_start": self.week_start,
            "shifts": [s.to_dict() for s in self.shifts],
            "absences": [a.to_dict() for a in self.absences],
            "employees": [{"name": n, "role": r} for n, r in self.employees.items()],
            "events": self.events,
            "warnings": self.warnings,
            "unparsed_cells": self.unparsed_cells,
        }


# ---------------------------------------------------------------------------
# Cell-level parsing
# ---------------------------------------------------------------------------
def clean_text(value: Any) -> str:
    """Normalise a raw cell to comparable text.

    NFKC folds look-alike Unicode (non-breaking spaces, full-width digits) that
    spreadsheets accumulate through copy-paste, so 'OFF' and 'OFF ' compare
    equal instead of mysteriously differing.
    """
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def normalise_name(value: Any) -> str:
    """Title-case a person's name for stable matching across sheets.

    Sheets contain 'MEGAN', 'Megan', ' AARON' and 'EMMA ' for the same people;
    without this they would import as separate employees.

    Trailing annotation marks are also stripped — 'TARA *' and 'TARA*' are the
    same Tara with a note beside her name, not two extra staff members. The
    caller is told when this happens (see ParsedWeek.warnings) so a human can
    confirm rather than the merge happening silently.
    """
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(r"[\s*†‡~^]+$", "", text)          # trailing note markers
    text = re.sub(r"\s*\((?:[^)]*)\)\s*$", "", text)  # trailing "(part time)"
    text = text.strip(" -–—.,")
    if not text:
        return ""
    return " ".join(part.capitalize() if part.isupper() else part
                    for part in text.split())


def parse_absence(text: str) -> Optional[str]:
    """Map an absence code, tolerating annotations and stray hour counts.

    Real sheets contain 'OFF*', 'SICK (5.5)' and 'b/HOL' alongside plain
    'OFF'. The annotation never changes what the code means, so it is
    stripped before lookup.
    """
    key = clean_text(text).lower()
    key = re.sub(r"\s*\([^)]*\)\s*$", "", key)  # "sick (5.5)" -> "sick"
    key = key.rstrip("*†‡. ").strip()
    return _ABSENCE_CODES.get(key)


def _to_hhmm(hour: int, minute: int) -> str:
    # Rosters write midnight as 00.00 at the END of a shift meaning 24:00.
    # Storing "24:00" would be invalid, so it stays "00:00" and the overnight
    # flag carries the meaning.
    return f"{hour % 24:02d}:{minute:02d}"


def _duration_hours(sh: int, sm: int, eh: int, em: int) -> Tuple[float, bool]:
    start = sh * 60 + sm
    end = eh * 60 + em
    overnight = end <= start
    if overnight:
        end += 24 * 60
    return (end - start) / 60, overnight


def parse_shift_cell(text: str) -> Optional[Dict[str, Any]]:
    """Read one timetable cell. Returns None if it is not a shift."""
    cleaned = clean_text(text)
    if not cleaned:
        return None

    match = _SHIFT_RE.match(cleaned)
    activity = None

    if not match:
        activity_match = _ACTIVITY_RE.match(cleaned)
        if not activity_match:
            return None
        activity = activity_match.group("label").strip().lower()
        sh = int(activity_match.group("sh"))
        sm = int(activity_match.group("sm") or 0)
        eh = int(activity_match.group("eh"))
        em = int(activity_match.group("em") or 0)
        stated = None
    else:
        sh, sm = int(match.group("sh")), int(match.group("sm") or 0)
        eh, em = int(match.group("eh")), int(match.group("em") or 0)
        stated = float(match.group("hours")) if match.group("hours") else None

        # "8-2pm(6)" — an explicit pm marker on the end time implies the
        # start is am, so 8 means 08:00 and 2pm means 14:00.
        if (match.group("eap") or "").lower() == "pm" and eh < 12:
            eh += 12
        if (match.group("sap") or "").lower() == "pm" and sh < 12:
            sh += 12

    if not (0 <= sh <= 24 and 0 <= eh <= 24 and 0 <= sm < 60 and 0 <= em < 60):
        return None

    hours, overnight = _duration_hours(sh, sm, eh, em)
    if hours <= 0 or hours > 16:
        return None

    return {
        "start": _to_hhmm(sh, sm),
        "end": _to_hhmm(eh, em),
        "hours": hours,
        "stated_hours": stated,
        "overnight": overnight,
        "activity": activity,
    }


def parse_week_ending(label: str, default_year: int = 2026) -> Optional[date]:
    """Turn a sheet name like 'we March 8th 26' into the week's MONDAY.

    'we' is week-ending, and the date in the label is the SUNDAY that closes
    the week — verified against the day-header rows, e.g. the sheet named
    'we Aug 23rd 26' contains 'MON 17th' through 'SUN 23rd'. The Monday is
    therefore the label date minus six days.

    Getting this wrong dates every imported week six days late, which in turn
    shifts every holiday derived from it onto the wrong days — staff show as
    on leave during weeks they actually worked.

    Subtracting six days also handles weeks that straddle a month or year
    boundary, where the Monday is in the previous month to the label.
    """
    text = clean_text(label).lower().replace("we ", " ").replace("centra", " ")
    match = _WEEK_ENDING_RE.search(text) or _WEEK_ENDING_RE_ALT.search(text)
    if not match:
        return None

    day = int(match.group("day"))
    month = _MONTHS[match.group("month").lower()[:3]]
    raw_year = match.group("year")
    if raw_year:
        year = int(raw_year)
        year += 2000 if year < 100 else 0
    else:
        year = default_year

    try:
        week_ending = date(year, month, day)
    except ValueError:
        return None

    monday = week_ending - timedelta(days=6)
    if monday.weekday() != 0:
        # The label was not the Sunday we assumed. Snap to the Monday of
        # whatever week it names rather than silently importing an offset
        # week — a wrong date is worse than an approximate one here.
        monday -= timedelta(days=monday.weekday())
    return monday


# ---------------------------------------------------------------------------
# Sheet-level parsing
# ---------------------------------------------------------------------------
_DAY_WORDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _day_columns(row: List[Any]) -> List[int]:
    """Which columns of this row hold day names."""
    columns: List[int] = []
    for col, cell in enumerate(row):
        text = clean_text(cell).lower()
        if text and any(text.startswith(word) for word in _DAY_WORDS):
            columns.append(col)
    return columns


def find_header_rows(rows: List[List[Any]]) -> List[Tuple[int, List[int]]]:
    """EVERY row that starts a week, not just the first.

    A sheet is not always one week. Managers routinely keep a month in a
    single tab, one week-block under another:

        Mon 27th  Tue 28th  ...      <- header
        Aneesh    17.30-23.00 ...
        Teja      OFF ...
                                     <- blank
        Mon 3rd   Tue 4th   ...      <- header again
        ...

    This used to scan `rows[:10]` and return one header, so every block below
    the first was read as more rows of the FIRST week. A real six-week sheet
    came in as one week holding 42 shifts across 7 days, with the same person
    on Monday three times — which then failed the duplicate check, produced
    one week of history instead of six, and left the shop below the four
    weeks the demand profile needs.
    """
    found: List[Tuple[int, List[int]]] = []
    for index, row in enumerate(rows):
        columns = _day_columns(row)
        # Seven is a full week. Fewer than four is a stray cell that happens
        # to begin "Mon" — a name like "Monica", or a "Sat" in a note.
        if len(columns) >= 4:
            found.append((index, columns))
    return found


def _find_header_row(rows: List[List[Any]]) -> Tuple[int, List[int]]:
    """The first week-block's header. Kept for callers that want one week."""
    headers = find_header_rows(rows)
    return headers[0] if headers else (-1, [])


def _looks_like_person(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if name.lower() in _NON_STAFF_TOKENS:
        return False
    # Totals rows are numeric; people are not.
    if re.fullmatch(r"[\d\s.,:/-]+", name):
        return False
    # A "name" that reads as an absence code is not a person. Vacant positions
    # get filled across the whole row — including the name cell — so without
    # this an employee called "Off" is created from rows like
    # ['Duty Mgr.', None, 'OFF', 'OFF', 'OFF', ...].
    if parse_absence(name):
        return False
    return bool(re.search(r"[A-Za-z]", name))


def _month_hint(rows: List[List[Any]], before: int) -> Optional[int]:
    """A month named anywhere above this block — "MONTH AUGUST", "August 26".

    Searched upwards from the block so a month title that sits above week
    three is not applied to week one.
    """
    for row in reversed(rows[:before]):
        for cell in row or []:
            text = clean_text(cell).lower()
            for name, number in _MONTHS.items():
                if name in text:
                    return number
    return None


def _day_of_month(text: str) -> Optional[int]:
    """27 from "Mon 27th", "MON 27", "Monday 27/08"."""
    match = re.search(r"(\d{1,2})", clean_text(text))
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 31 else None


def _week_start_from_header(
    row: List[Any],
    columns: List[int],
    month: Optional[int],
    year: int,
    previous: Optional[date],
) -> Optional[date]:
    """The Monday this block covers, from its own header row.

    The header carries the day of the month but not the month itself
    ("Mon 27th"), so it is resolved against a month named elsewhere on the
    sheet, and against the previous block — consecutive blocks are seven days
    apart, which settles a month boundary without any title at all.
    """
    if not columns:
        return None
    day_number = _day_of_month(row[columns[0]] if columns[0] < len(row) else "")
    if day_number is None:
        return None

    # A week after the previous one, if the number agrees. This carries the
    # sequence across a month end — "Mon 31st" then "Mon 7th" — with no
    # month named at all.
    if previous:
        candidate = previous + timedelta(days=7)
        if candidate.day == day_number:
            return candidate

    # Otherwise find a Monday with that date, near the month named on the
    # sheet. The window spans a month either side because a block headed
    # "Mon 31st" under a title reading AUGUST may well start in July.
    base = month or (previous.month if previous else None)
    if base is None:
        return None
    for offset in (0, -1, 1, 2):
        m = base + offset
        y = year + (1 if m > 12 else -1 if m < 1 else 0)
        m = (m - 1) % 12 + 1
        try:
            candidate = date(y, m, day_number)
        except ValueError:
            continue
        if candidate.weekday() == 0:
            return candidate
    return None


def parse_sheet_weeks(
    sheet_name: str, rows: List[List[Any]], default_year: int = 2026,
) -> List[ParsedWeek]:
    """Every week-block on one sheet.

    Usually one. A manager keeping a whole month in a single tab gets one per
    block, each dated from its own header row.
    """
    headers = find_header_rows(rows)
    if len(headers) <= 1:
        return [parse_sheet(sheet_name, rows, default_year)]

    # The sheet name dates the FIRST block when it says anything; the rest
    # follow from it. A name like "Sheet1" says nothing, and then the header
    # rows are all there is.
    from_name = parse_week_ending(sheet_name, default_year)
    weeks: List[ParsedWeek] = []
    previous = from_name

    for position, (index, columns) in enumerate(headers):
        stop = headers[position + 1][0] if position + 1 < len(headers) else len(rows)
        block = rows[index:stop]

        start = (from_name if position == 0 and from_name else
                 _week_start_from_header(
                     rows[index], columns,
                     _month_hint(rows, index), default_year, previous,
                 ))
        week = parse_sheet(sheet_name, block, default_year)
        week.week_start = start.isoformat() if start else None
        # parse_sheet warns about the sheet NAME, which is not where these
        # blocks get their dates from.
        week.warnings = [
            w for w in week.warnings if "from the sheet name" not in w
        ]
        if not start:
            week.warnings.append(
                f"Could not work out which week the block at row {index + 1} "
                f"covers. Name the sheet after the week, or put the month "
                f"above the rota."
            )
        week.week_ending_label = f"{sheet_name} (row {index + 1})"
        weeks.append(week)
        previous = start or previous

    return weeks


def parse_sheet(sheet_name: str, rows: List[List[Any]], default_year: int = 2026) -> ParsedWeek:
    week = ParsedWeek(
        sheet_name=sheet_name,
        week_ending_label=sheet_name,
        week_start=None,
    )

    monday = parse_week_ending(sheet_name, default_year)
    if monday:
        week.week_start = monday.isoformat()
    else:
        week.warnings.append(f"Could not read a date from the sheet name {sheet_name!r}.")

    header_index, day_columns = _find_header_row(rows)
    if len(day_columns) < 7:
        week.warnings.append(
            f"Expected 7 day columns, found {len(day_columns)}. Sheet skipped."
        )
        return week

    day_columns = day_columns[:7]
    name_column = _guess_name_column(rows, header_index, day_columns[0])
    current_role: Optional[str] = None

    for row in rows[header_index + 1:]:
        if not row:
            continue

        # A non-empty leftmost cell starts a new role section, and that role
        # applies to every row beneath it until the next one.
        #
        # UNLESS the leftmost cell IS the name column. A sheet with no role
        # column at all — just names down the side — was giving every person
        # their own name as their job title: {'Aneesh': 'Aneesh'}. That put
        # two unknown roles into the hierarchy, where §9 keeps an unrecognised
        # title verbatim at the bottom, so role priority became arbitrary and
        # the shop appeared to be ignoring seniority entirely.
        #
        # No role column means no role. §9 again: report it, do not invent it.
        if name_column != 0:
            section = clean_text(row[0]) if len(row) > 0 else ""
            if section and _looks_like_person(section):
                current_role = _canonical_role(section)

        name = normalise_name(row[name_column]) if len(row) > name_column else ""
        if not _looks_like_person(name):
            continue

        week.employees.setdefault(name, current_role)

        for day_index, column in enumerate(day_columns):
            if column >= len(row):
                continue
            raw = clean_text(row[column])
            if not raw:
                continue

            day = DAYS[day_index]

            absence = parse_absence(raw)
            if absence:
                week.absences.append(ParsedAbsence(name, current_role, day, absence))
                continue

            # A bare number is hours worked with no times recorded. Real
            # information, but not enough to place a shift on a timeline, so
            # it is held back for review rather than invented.
            bare_hours = re.fullmatch(r"(\d{1,2}(?:\.\d+)?)", raw)
            if bare_hours:
                week.unparsed_cells.append({
                    "employee_name": name, "day": day, "value": raw,
                    "reason": f"{bare_hours.group(1)} hours given without start/end times",
                })
                continue

            parsed = parse_shift_cell(raw)
            if parsed:
                week.shifts.append(ParsedShift(
                    employee_name=name,
                    role=current_role,
                    day=day,
                    start=parsed["start"],
                    end=parsed["end"],
                    hours=parsed["hours"],
                    stated_hours=parsed["stated_hours"],
                    activity=parsed["activity"],
                    overnight=parsed["overnight"],
                ))
                # A mismatch between our arithmetic and the sheet's own figure
                # usually means a typo in the sheet — surfaced, not corrected.
                stated = parsed["stated_hours"]
                if stated is not None and abs(stated - parsed["hours"]) > 0.26:
                    week.warnings.append(
                        f"{name} {day}: sheet says {stated}h but "
                        f"{parsed['start']}-{parsed['end']} is {parsed['hours']:.2f}h."
                    )
            elif _looks_like_event(raw):
                # Named events ("radioathon", "awards", "deli") mean the person
                # worked, but the sheet records no times. Kept as a worked day
                # with unknown hours so the record is honest.
                week.events.append({
                    "employee_name": name, "day": day, "label": raw.lower(),
                })
            else:
                week.unparsed_cells.append(
                    {"employee_name": name, "day": day, "value": raw,
                     "reason": "unrecognised format"}
                )

    return week


# Short alphabetic entries with no digits are event or location names rather
# than shifts. The digit test is what separates "deli" from "8-2pm(6)".
def _looks_like_event(text: str) -> bool:
    cleaned = clean_text(text).strip("*†‡ ")
    if not cleaned or len(cleaned) > 40:
        return False
    if any(ch.isdigit() for ch in cleaned):
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z\s/&'.-]*", cleaned))


def _guess_name_column(rows: List[List[Any]], header_index: int, first_day_column: int) -> int:
    """Pick the column holding names: the rightmost text column before day one."""
    scores: Dict[int, int] = {}
    for row in rows[header_index + 1: header_index + 25]:
        for col in range(min(first_day_column, len(row))):
            if _looks_like_person(normalise_name(row[col])):
                scores[col] = scores.get(col, 0) + 1
    if not scores:
        return max(0, first_day_column - 1)
    best = max(scores.values())
    # Ties go to the rightmost column, which is the name rather than the role.
    return max(col for col, count in scores.items() if count == best)


def _canonical_role(raw: str) -> str:
    text = clean_text(raw)
    key = text.lower().rstrip(".").strip()
    if key in _SECTION_ALIASES:
        return _SECTION_ALIASES[key]
    # "Assistant Mgr." -> "Assistant Manager"
    text = re.sub(r"\bmgr\b\.?", "Manager", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcust\b\.?", "Customer", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsupervisors\b", "Supervisor", text, flags=re.IGNORECASE)
    return text.title() if text.isupper() else text


# ---------------------------------------------------------------------------
# Workbook-level entry points
# ---------------------------------------------------------------------------
def parse_workbook_rows(
    sheets: Iterable[Tuple[str, List[List[Any]]]],
    default_year: int = 2026,
) -> List[ParsedWeek]:
    """Parse pre-read sheets. Keeps this module free of any Excel dependency."""
    return [
        week
        for name, rows in sheets
        for week in parse_sheet_weeks(name, rows, default_year)
    ]


def read_xlsx(path: str) -> List[Tuple[str, List[List[Any]]]]:
    """Read every sheet of an .xlsx into plain rows. Requires openpyxl."""
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets = []
    for name in workbook.sheetnames:
        worksheet = workbook[name]
        sheets.append((name, [list(row) for row in worksheet.iter_rows(values_only=True)]))
    workbook.close()
    return sheets


def summarise(weeks: List[ParsedWeek]) -> Dict[str, Any]:
    """Headline numbers for an import preview."""
    usable = [w for w in weeks if w.is_usable]
    employees: Dict[str, Optional[str]] = {}
    for week in usable:
        for name, role in week.employees.items():
            if employees.get(name) is None:
                employees[name] = role

    total_shifts = sum(len(w.shifts) for w in usable)
    dates = sorted(w.week_start for w in usable if w.week_start)

    return {
        "sheets_seen": len(weeks),
        "weeks_usable": len(usable),
        "weeks_skipped": len(weeks) - len(usable),
        "employees": len(employees),
        "total_shifts": total_shifts,
        "total_absences": sum(len(w.absences) for w in usable),
        "events": sum(len(w.events) for w in usable),
        "unparsed_cells": sum(len(w.unparsed_cells) for w in usable),
        "date_range": (dates[0], dates[-1]) if dates else None,
        "employee_roles": employees,
    }
