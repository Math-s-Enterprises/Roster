"""Tests for the legacy spreadsheet parser.

Every case here came from a real defect in a real roster file, so each test
names the situation it protects against rather than the function it calls.
"""
import pytest

from app.services.roster_import import (
    normalise_name,
    parse_absence,
    parse_sheet,
    parse_shift_cell,
    parse_week_ending,
)


# ---------------------------------------------------------------------------
# Shift cells
# ---------------------------------------------------------------------------
class TestShiftCells:
    @pytest.mark.parametrize("text,start,end,hours", [
        ("06.00-16.00 (10)", "06:00", "16:00", 10.0),   # dots, spaced bracket
        ("16.00-00.00(8)", "16:00", "00:00", 8.0),      # ends at midnight
        ("07.30-16.00(8.5)", "07:30", "16:00", 8.5),    # half hour
        ("6:00-14:00", "06:00", "14:00", 8.0),          # colons
        ("23.30-07.00 (7.5)", "23:30", "07:00", 7.5),   # overnight
        ("8-2pm(6)", "08:00", "14:00", 6.0),            # am/pm, no minutes
        ("9-17.00", "09:00", "17:00", 8.0),             # minutes only on one side
    ])
    def test_accepted_formats(self, text, start, end, hours):
        parsed = parse_shift_cell(text)
        assert parsed is not None, f"{text!r} should parse"
        assert (parsed["start"], parsed["end"]) == (start, end)
        assert parsed["hours"] == pytest.approx(hours)

    def test_missing_opening_bracket(self):
        """Real typo: '06.00-16.00 10)' — the '(' was never typed."""
        assert parse_shift_cell("06.00-16.00 10)")["start"] == "06:00"

    def test_doubled_opening_bracket(self):
        """Real typo: '10.00-19.00(9(' — the ')' came out as '('."""
        assert parse_shift_cell("10.00-19.00(9(")["end"] == "19:00"

    def test_trailing_annotation_ignored(self):
        """'*' meant 'working off-site' — a note, not scheduling data."""
        assert parse_shift_cell("07.00-15.00(8)*")["hours"] == pytest.approx(8.0)

    def test_overnight_flagged_and_measured_forwards(self):
        parsed = parse_shift_cell("23.30-07.00 (7.5)")
        assert parsed["overnight"] is True
        assert parsed["hours"] == pytest.approx(7.5)

    def test_stated_hours_kept_for_cross_checking(self):
        """The sheet's own total is retained so mismatches can be reported
        rather than silently trusted or silently overwritten."""
        parsed = parse_shift_cell("10.00-19.00(8)")   # actually 9h
        assert parsed["stated_hours"] == 8.0
        assert parsed["hours"] == pytest.approx(9.0)

    @pytest.mark.parametrize("text", ["OFF", "hol", "N/A", "deli", "", "8", "RADIOATHON"])
    def test_non_shifts_rejected(self, text):
        assert parse_shift_cell(text) is None

    def test_impossible_times_rejected(self):
        assert parse_shift_cell("99.99-88.88") is None

    def test_zero_length_rejected(self):
        """Start == end is a data-entry error, not a 24-hour shift."""
        assert parse_shift_cell("09.00-09.00") is None

    def test_activity_with_times_is_captured(self):
        parsed = parse_shift_cell("first aid 9-17.00")
        assert parsed["activity"] == "first aid"
        assert parsed["start"] == "09:00"


# ---------------------------------------------------------------------------
# Absence codes
# ---------------------------------------------------------------------------
class TestAbsenceCodes:
    @pytest.mark.parametrize("text,expected", [
        ("OFF", "off"), ("off", "off"), ("OFF*", "off"),
        ("HOL", "holiday"), ("hol", "holiday"),
        ("b/hol", "bank_holiday"), ("B/HOL", "bank_holiday"),
        ("N/A", "unavailable"), ("n/a", "unavailable"),
        ("SICK*", "sick"), ("SICK (5.5)", "sick"),
        ("BEREAVEMENT", "bereavement"),
    ])
    def test_recognised(self, text, expected):
        assert parse_absence(text) == expected

    @pytest.mark.parametrize("text", ["06.00-16.00 (10)", "deli", "Megan", ""])
    def test_not_absences(self, text):
        assert parse_absence(text) is None


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
class TestNames:
    def test_case_and_whitespace_normalised(self):
        assert normalise_name("MEGAN") == "Megan"
        assert normalise_name(" AARON") == "Aaron"
        assert normalise_name("EMMA ") == "Emma"

    def test_annotation_marker_stripped(self):
        """'TARA *' and 'TARA*' were importing as two phantom employees."""
        assert normalise_name("TARA *") == normalise_name("TARA*") == "Tara"

    def test_multi_word_name_preserved(self):
        assert normalise_name("Mark B") == "Mark B"

    def test_accented_name_preserved(self):
        assert normalise_name("ROISÍN") == "Roisín"


# ---------------------------------------------------------------------------
# Sheet names -> dates
# ---------------------------------------------------------------------------
class TestWeekEnding:
    """'we' is week-ENDING: the label names the Sunday, so the week starts
    six days earlier. Reading it as the Monday dated every import six days
    late and shifted all the derived leave records with it."""

    @pytest.mark.parametrize("label,expected", [
        ("we 25th january26", "2026-01-19"),
        ("we March 8th 26", "2026-03-02"),
        ("we 22nd feb 26", "2026-02-16"),
        ("we May 31ST 26     ", "2026-05-25"),
        ("we  June 7th 26     centra", "2026-06-01"),
        # Weeks that straddle a month boundary — the Monday is in the
        # previous month to the one the label names.
        ("we march 1st 26", "2026-02-23"),
        ("we Aug 2nd 26", "2026-07-27"),
        ("we July 5th 26", "2026-06-29"),
    ])
    def test_parsed(self, label, expected):
        assert parse_week_ending(label, 2026).isoformat() == expected

    @pytest.mark.parametrize("label", [
        "we 25th january26", "we March 8th 26", "we Aug 23rd 26", "we May 3rd 26",
    ])
    def test_always_lands_on_a_monday(self, label):
        assert parse_week_ending(label, 2026).weekday() == 0

    def test_unparseable_returns_none(self):
        assert parse_week_ending("Sheet1", 2026) is None


# ---------------------------------------------------------------------------
# Whole sheets
# ---------------------------------------------------------------------------
HEADER = ["", "", "", "MON 17th", "TUES 18th", "WED 19th", "THURS 20th",
          "FRI 21st", "SAT 22nd", "SUN 23rd"]


def sheet(*rows):
    return [HEADER, *rows]


class TestSheetParsing:
    def test_role_inherited_down_a_section(self):
        """The role is written once, on the section's first row."""
        week = parse_sheet("we 25th january26", sheet(
            ["SHOPFLOOR", "", "EMMA", "06.00-14.00 (8)", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
            ["", "", "BREDA", "OFF", "10.00-18.00 (8)", "OFF", "OFF", "OFF", "OFF", "OFF"],
        ), 2026)
        assert week.employees == {"Emma": "Shop Floor", "Breda": "Shop Floor"}

    def test_vacant_position_row_is_not_an_employee(self):
        """Four real sheets had a Duty Mgr. row filled with OFF across every
        column including the name, which created an employee called 'Off'."""
        week = parse_sheet("we May 17th 26", sheet(
            ["Duty Mgr.", "", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
            ["", "", "COREY", "06.00-16.00 (10)", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
        ), 2026)
        assert "Off" not in week.employees
        assert "Corey" in week.employees

    def test_absences_classified_not_dropped(self):
        week = parse_sheet("we 25th january26", sheet(
            ["SHOPFLOOR", "", "JANE", "OFF", "hol", "N/A", "b/hol", "SICK", "OFF", "OFF"],
        ), 2026)
        kinds = [a.kind for a in week.absences]
        assert kinds.count("off") == 3
        assert "holiday" in kinds and "unavailable" in kinds
        assert "bank_holiday" in kinds and "sick" in kinds

    def test_hour_mismatch_reported(self):
        week = parse_sheet("we 25th january26", sheet(
            ["SHOPFLOOR", "", "CONOR", "17.00-23.00(5)", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
        ), 2026)
        assert any("5.0h" in w and "6.00h" in w for w in week.warnings)

    def test_bare_number_held_for_review(self):
        """Hours with no times is real information but not placeable."""
        week = parse_sheet("we 25th january26", sheet(
            ["SHOPFLOOR", "", "EMMA", "4", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
        ), 2026)
        assert week.shifts == []
        assert week.unparsed_cells[0]["value"] == "4"

    def test_named_event_recorded_separately(self):
        week = parse_sheet("we 25th january26", sheet(
            ["SHOPFLOOR", "", "KYLE", "deli", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
        ), 2026)
        assert week.events[0]["label"] == "deli"
        assert week.unparsed_cells == []

    def test_sheet_without_day_headers_is_skipped(self):
        week = parse_sheet("Sheet1", [["", "", ""]], 2026)
        assert not week.is_usable
        assert week.warnings


# ---------------------------------------------------------------------------
# A month in one tab: several week-blocks stacked down a single sheet
# ---------------------------------------------------------------------------
class TestSeveralWeeksOnOneSheet:
    """A sheet is not always one week.

    Managers keep a month in a single tab, one block under another. This used
    to read only the first header row, so every block below it became more
    rows of the FIRST week — a six-week sheet arrived as one week holding 42
    shifts across 7 days, the same person on Monday three times. That left the
    shop on one week of history when it had six, below the four the demand
    profile needs, so ownership never formed and the roster fell back to role
    priority. Every symptom traced to this one line.
    """

    def month_sheet(self):
        """His own file's shape: a month title, then blocks with a blank row
        between, names down the leftmost column and NO role column."""
        return [
            ["", "", "MONTH AUGUST"],
            [],
            ["", "Mon 27th", "Tue 28th", "Wed 29th", "Thurs 30th",
             "Fri 31st", "Sat 1st", "Sun 2nd"],
            ["Aneesh", "17.30 - 23.00", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
            ["Teja", "OFF", "17.30 - 23.00", "OFF", "OFF", "OFF", "OFF", "OFF"],
            [],
            ["", "Mon 3rd", "Tue 4th", "Wed 5th", "Thurs 6th",
             "Fri 7th", "Sat 8th", "Sun 9th"],
            ["Aneesh", "12.00 - 23.00", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
            ["Teja", "OFF", "OFF", "17.30 - 23.00", "OFF", "OFF", "OFF", "OFF"],
            [],
            ["", "Mon 10th", "Tue 11th", "Wed 12th", "Thurs 13th",
             "Fri 14th", "Sat 15th", "Sun 16th"],
            ["Aneesh", "OFF", "OFF", "17.30 - 23.00", "OFF", "OFF", "OFF", "OFF"],
            ["Teja", "17.30 - 23.00", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"],
        ]

    def weeks(self):
        from app.services.roster_import import parse_sheet_weeks
        return parse_sheet_weeks("Sheet1", self.month_sheet(), 2026)

    def test_each_block_becomes_its_own_week(self):
        assert len(self.weeks()) == 3

    def test_the_weeks_are_dated_from_their_own_headers(self):
        """The sheet is called "Sheet1" — the dates exist only in the header
        rows and the month title above them."""
        assert [w.week_start for w in self.weeks()] == [
            "2026-07-27", "2026-08-03", "2026-08-10",
        ]

    def test_a_block_starting_in_the_previous_month_is_still_right(self):
        """"Mon 27th" under a title reading AUGUST is the 27th of JULY —
        the week that ends on 2 August."""
        assert self.weeks()[0].week_start == "2026-07-27"

    def test_shifts_land_in_the_week_they_belong_to(self):
        first, second, third = self.weeks()
        assert [(s.employee_name, s.day, s.start) for s in first.shifts] == [
            ("Aneesh", "mon", "17:30"), ("Teja", "tue", "17:30"),
        ]
        assert [(s.employee_name, s.day, s.start) for s in second.shifts] == [
            ("Aneesh", "mon", "12:00"), ("Teja", "wed", "17:30"),
        ]
        assert [(s.employee_name, s.day) for s in third.shifts] == [
            ("Aneesh", "wed"), ("Teja", "mon"),
        ]

    def test_nobody_appears_twice_on_one_day(self):
        """The failure that made this visible: 42 shifts on 7 days, Aneesh on
        Monday three times. A duplicate (person, day) corrupts the corrections
        diff, which identifies a shift by exactly that pair."""
        for week in self.weeks():
            seen = [(s.employee_name, s.day) for s in week.shifts]
            assert len(seen) == len(set(seen)), week.shifts

    def test_a_sheet_with_no_role_column_invents_no_roles(self):
        """Names down column 0 were being read as role headings, so everyone
        got their own name as a job title. §9: report it, do not guess."""
        for week in self.weeks():
            assert set(week.employees.values()) == {None}

    def test_one_week_per_sheet_still_works(self):
        """The layout that already worked must not change."""
        from app.services.roster_import import parse_sheet_weeks

        weeks = parse_sheet_weeks("we 25th january26", sheet(
            ["Duty Mgr.", "Megan", "06:00-16:00", "", "", "", "", "", ""],
        ), 2026)
        assert len(weeks) == 1
        assert weeks[0].week_start == "2026-01-19"
        assert weeks[0].employees == {"Megan": "Duty Manager"}
