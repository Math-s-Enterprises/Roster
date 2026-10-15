"""Uploaded rosters can use a long dash, and the importer must keep reading them.

A manager typing a roster into a spreadsheet may put a long dash between the two times of a
shift ("9 to 17" written 9, a long dash, 17), or around a name. The importer has always read
those. The character is written as an escape in this file so that the file, like the rest of
the project, contains no literal long dash.
"""
import pytest

from app.services.roster_import import normalise_name, parse_shift_cell

EM = "\u2014"


class TestALongDashInAnUploadedSheet:
    @pytest.mark.parametrize("text,start,end", [
        (f"9{EM}17", "09:00", "17:00"),
        (f"09:00 {EM} 17:00", "09:00", "17:00"),
        (f"06.00{EM}16.00 (10)", "06:00", "16:00"),
        (f"6pm{EM}2am", "18:00", "02:00"),
        (f"8{EM}2pm(6)", "08:00", "14:00"),
    ])
    def test_a_shift_cell_written_with_a_long_dash_is_read(self, text, start, end):
        parsed = parse_shift_cell(text)
        assert parsed is not None, f"{text!r} was not recognised as a shift"
        assert (parsed["start"], parsed["end"]) == (start, end)

    def test_an_activity_with_times_and_a_long_dash_is_captured(self):
        parsed = parse_shift_cell(f"first aid 9{EM}17.00")
        assert parsed is not None and parsed["activity"] == "first aid"
        assert (parsed["start"], parsed["end"]) == ("09:00", "17:00")

    @pytest.mark.parametrize("dash", [EM, "-", "\u2013"])
    def test_every_kind_of_dash_reads_the_same(self, dash):
        assert parse_shift_cell(f"9{dash}17") == parse_shift_cell("9-17")

    @pytest.mark.parametrize("text,expected", [
        (f"{EM}Anna{EM}", "Anna"),
        (f"Anna {EM}", "Anna"),
        (f"{EM} Tara (part time)", "Tara"),
        (f"MEGAN {EM}", "Megan"),
    ])
    def test_a_long_dash_around_a_name_is_trimmed_like_any_other_separator(self, text, expected):
        assert normalise_name(text) == expected
