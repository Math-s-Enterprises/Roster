"""Reading staff emails out of a sheet the staff themselves filled in.

The file is not written by a developer. It has a title above the headers, a
Notes column somebody added, blank rows where people were deleted, and headers
reading "Email address" or "E-mail" or nothing. These tests are that file.
"""
import io

from app.services.contact_import import (
    ContactRow,
    UnreadableFile,
    fold,
    match,
    parse,
)


def csv_bytes(text):
    return text.encode("utf-8")


def staff(*names):
    return [
        {"employee_id": f"e{i}", "name": n, "is_active": True, "email": ""}
        for i, n in enumerate(names)
    ]


class TestFindingTheColumns:
    """Nothing is located by header, because the header cannot be relied on."""

    def test_a_tidy_file_works(self):
        rows = parse(csv_bytes("name,email\nEmma,emma@shop.ie\n"), "s.csv")
        assert [(r.name, r.email) for r in rows] == [("Emma", "emma@shop.ie")]

    def test_the_header_row_is_not_mistaken_for_a_person(self):
        """It contains no address, so it disappears without being recognised."""
        rows = parse(csv_bytes("Name,Email\nEmma,emma@shop.ie\n"), "s.csv")
        assert len(rows) == 1

    def test_a_title_and_blank_rows_above_the_headers_are_ignored(self):
        text = (
            "Top Oil South Link — please fill in your email\n"
            "\n"
            "Updated March 2026\n"
            "\n"
            "Name,Email address,Notes\n"
            "Emma,emma@shop.ie,\n"
            "\n"
            "Megan,megan@shop.ie,starts April\n"
        )
        rows = parse(csv_bytes(text), "s.csv")
        assert [(r.name, r.email) for r in rows] == [
            ("Emma", "emma@shop.ie"), ("Megan", "megan@shop.ie"),
        ]

    def test_the_columns_can_be_the_other_way_round(self):
        rows = parse(csv_bytes("email,name\nemma@shop.ie,Emma\n"), "s.csv")
        assert (rows[0].name, rows[0].email) == ("Emma", "emma@shop.ie")

    def test_a_staff_number_column_is_not_read_as_a_name(self):
        rows = parse(csv_bytes("id,name,email\n1042,Emma,emma@shop.ie\n"), "s.csv")
        assert rows[0].name == "Emma"

    def test_a_row_with_no_address_is_skipped(self):
        """Somebody who has not filled theirs in yet is simply absent, not an
        error — the sheet comes back half done and that is normal."""
        rows = parse(csv_bytes("Name,Email\nEmma,\nMegan,megan@shop.ie\n"), "s.csv")
        assert [r.name for r in rows] == ["Megan"]

    def test_windows_encoding_survives(self):
        """Excel on Windows does not write UTF-8, and Roisín is a real name
        on this shop's roster."""
        rows = parse("Name,Email\nRoisín,roisin@shop.ie\n".encode("cp1252"), "s.csv")
        assert rows[0].name == "Roisín"

    def test_a_tsv_works_too(self):
        rows = parse(csv_bytes("Name\tEmail\nEmma\temma@shop.ie\n"), "s.tsv")
        assert rows[0].email == "emma@shop.ie"

    def test_rubbish_in_the_address_column_is_not_an_address(self):
        rows = parse(csv_bytes("Name,Email\nEmma,ask me\nMegan,m@shop.ie\n"), "s.csv")
        assert [r.name for r in rows] == ["Megan"]


class TestMatchingPeople:
    """The dangerous half. A wrong match emails one person's hours to
    another, which is a data-protection incident, not a bug."""

    def test_a_first_name_is_enough_when_it_is_unique(self):
        rows = match(parse(csv_bytes("n,e\nEmma,emma@shop.ie\n"), "s.csv"),
                     staff("Emma Doyle", "Megan Byrne"))
        assert rows.rows[0].status == "ready"
        assert rows.rows[0].employee_name == "Emma Doyle"

    def test_two_people_of_the_same_name_are_refused_not_guessed(self):
        """The test this whole module exists for."""
        result = match(parse(csv_bytes("n,e\nEmma,emma@shop.ie\n"), "s.csv"),
                       staff("Emma Doyle", "Emma Byrne"))
        row = result.rows[0]
        assert row.status == "ambiguous"
        assert row.employee_id is None, "it must not pick one of them"
        assert "Emma Doyle" in row.note and "Emma Byrne" in row.note

    def test_the_full_name_resolves_that_ambiguity(self):
        result = match(parse(csv_bytes("n,e\nEmma Byrne,emma@shop.ie\n"), "s.csv"),
                       staff("Emma Doyle", "Emma Byrne"))
        assert result.rows[0].status == "ready"
        assert result.rows[0].employee_name == "Emma Byrne"

    def test_an_accent_does_not_stop_a_match(self):
        result = match(parse(csv_bytes("n,e\nRoisin,r@shop.ie\n"), "s.csv"),
                       staff("Roisín Kelly"))
        assert result.rows[0].status == "ready"

    def test_case_does_not_stop_a_match(self):
        result = match(parse(csv_bytes("n,e\nAJ,aj@shop.ie\n"), "s.csv"), staff("Aj"))
        assert result.rows[0].status == "ready"

    def test_somebody_who_does_not_work_here_is_reported(self):
        result = match(parse(csv_bytes("n,e\nStranger,x@shop.ie\n"), "s.csv"),
                       staff("Emma Doyle"))
        assert result.rows[0].status == "unknown"
        assert result.rows[0].employee_id is None

    def test_one_address_cannot_belong_to_two_people(self):
        text = "n,e\nEmma,shared@shop.ie\nMegan,shared@shop.ie\n"
        result = match(parse(csv_bytes(text), "s.csv"), staff("Emma", "Megan"))
        assert result.rows[0].status == "ready"
        assert result.rows[1].status == "duplicate"
        assert "row 2" in result.rows[1].note

    def test_an_existing_address_is_not_overwritten_silently(self):
        team = staff("Emma")
        team[0]["email"] = "old@shop.ie"
        result = match(parse(csv_bytes("n,e\nEmma,new@shop.ie\n"), "s.csv"), team)
        assert result.rows[0].status == "conflict"
        assert "old@shop.ie" in result.rows[0].note

    def test_replace_makes_it_ready(self):
        team = staff("Emma")
        team[0]["email"] = "old@shop.ie"
        result = match(parse(csv_bytes("n,e\nEmma,new@shop.ie\n"), "s.csv"),
                       team, allow_replace=True)
        assert result.rows[0].status == "ready"

    def test_whoever_the_sheet_forgot_is_named(self):
        """The manager needs to know who is still unreachable, and counting
        them is not the same as naming them."""
        result = match(parse(csv_bytes("n,e\nEmma,emma@shop.ie\n"), "s.csv"),
                       staff("Emma", "Megan", "Martin"))
        assert result.unmatched_staff == ["Martin", "Megan"]


class TestBadFiles:
    def test_a_file_that_is_not_a_spreadsheet_says_so(self):
        try:
            parse(b"not a spreadsheet at all", "staff.xlsx")
            assert False, "should have raised"
        except UnreadableFile as exc:
            assert "could not be opened" in str(exc)

    def test_an_empty_file_yields_nothing_rather_than_failing(self):
        assert parse(b"", "s.csv") == []


class TestFold:
    def test_accents_and_case_and_spacing(self):
        assert fold("  Roisín   Kelly ") == fold("roisin kelly")
        assert fold("AJ") == fold("Aj")
        assert fold("Emma") != fold("Emmanuel")
