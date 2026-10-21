"""Photo imports respect the manager's date and never hide incomplete reads."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import file_import, llm
from tests.test_api import auth, register


def roster_response(week_start="2025-01-20"):
    shifts = []
    for name, days in (("Megan", ("tue", "wed", "thu", "sun")),
                       ("John", ("wed", "thu", "fri", "sat"))):
        for day in days:
            shifts.append({
                "employee_name": name, "role": "Shop Floor", "day": day,
                "start": "06:00", "end": "12:00" if day == "sun" else "16:00",
                "note": "",
            })
    for name, day, note in (("Megan", "mon", "b/hol"), ("John", "tue", "b/hol"),
                            ("Megan", "fri", "off"), ("Megan", "sat", "off"),
                            ("John", "mon", "off"), ("John", "sun", "off")):
        shifts.append({
            "employee_name": name, "role": "Shop Floor", "day": day,
            "start": None, "end": None, "note": note,
        })
    return {"week_start": week_start, "shifts": shifts}


def stub_anthropic(monkeypatch, payload, stop_reason="end_turn"):
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="text", text=payload)],
        )

    monkeypatch.setattr(llm, "_get_client", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=create),
    ))
    return requests


def test_selected_week_overrides_an_image_date_through_preview_and_commit(client, monkeypatch):
    stub_anthropic(monkeypatch, json.dumps(roster_response()))
    headers = auth(register(client))
    response = client.post("/api/imports", headers=headers,
                           files={"file": ("roster.png", b"\x89PNGtest", "image/png")},
                           data={"week_start": "2026-10-26"})
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["summary"]["date_range"] == ["2026-10-26", "2026-10-26"]
    assert preview["summary"]["shifts"] == 8
    assert preview["summary"]["unreadable_cells"] == 0
    assert preview["weeks"][0]["week_start"] == "2026-10-26"
    assert preview["needs_review"] is True
    response = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
                           json={"week_starts": ["2026-10-26"],
                                 "employee_map": {"Megan": "", "John": ""}})
    assert response.status_code == 200, response.text
    history = client.get("/api/imports/history", headers=headers).json()
    assert [(w["week_start"], w["shifts"]) for w in history] == [("2026-10-26", 8)]


@pytest.mark.parametrize("image_date", [None, "2025-01-20"])
def test_a_selected_day_is_normalised_to_monday_without_an_undated_warning(monkeypatch, image_date):
    stub_anthropic(monkeypatch, json.dumps(roster_response(image_date)))
    result = asyncio.run(file_import.parse_upload(
        "roster.jpg", b"test", week_start="2026-10-28",
    ))
    assert result.weeks[0].week_start == "2026-10-26"
    assert not any("could not determine" in w for w in result.weeks[0].warnings)


@pytest.mark.parametrize("pages,expected", [
    (1, ["2026-10-26"]), (2, ["2025-01-20", "2025-01-20"]),
])
def test_single_page_pdf_uses_the_selected_week_but_multi_page_dates_are_preserved(monkeypatch, pages, expected):
    stub_anthropic(monkeypatch, json.dumps(roster_response()))
    monkeypatch.setattr(file_import, "_pdf_to_images", lambda _: [b"test"] * pages)
    result = asyncio.run(file_import.parse_upload(
        "roster.pdf", b"test", week_start="2026-10-26",
    ))
    assert [w.week_start for w in result.weeks] == expected


def test_a_photo_without_a_selected_week_keeps_its_read_date(monkeypatch):
    stub_anthropic(monkeypatch, json.dumps(roster_response("2026-10-26")))
    result = asyncio.run(file_import.parse_upload("roster.png", b"test"))
    assert result.weeks[0].week_start == "2026-10-26"


def test_dated_spreadsheet_weeks_are_not_overwritten(monkeypatch):
    weeks = [file_import._week_from_ocr(roster_response(date), "sheet", 2026)
             for date in ("2026-10-05", "2026-10-12")]
    monkeypatch.setattr(file_import, "_read_spreadsheet", lambda *_: (weeks, 2))
    result = asyncio.run(file_import.parse_upload(
        "history.xlsx", b"test", week_start="2026-10-26",
    ))
    assert [w.week_start for w in result.weeks] == ["2026-10-05", "2026-10-12"]


def test_image_reading_requests_a_schema_and_preserves_all_shift_times(monkeypatch):
    requests = stub_anthropic(monkeypatch, json.dumps(roster_response()))
    parsed = asyncio.run(llm.ocr_roster_bytes(b"test", ["Megan", "John"]))
    schema = requests[0]["output_config"]["format"]["schema"]
    assert set(schema["required"]) == {"week_start", "shifts"}
    assert schema["additionalProperties"] is False
    week = file_import._week_from_ocr(parsed, "image", 2026)
    assert [(s.employee_name, s.day, s.start, s.end) for s in week.shifts] == [
        ("Megan", "tue", "06:00", "16:00"), ("Megan", "wed", "06:00", "16:00"),
        ("Megan", "thu", "06:00", "16:00"), ("Megan", "sun", "06:00", "12:00"),
        ("John", "wed", "06:00", "16:00"), ("John", "thu", "06:00", "16:00"),
        ("John", "fri", "06:00", "16:00"), ("John", "sat", "06:00", "16:00"),
    ]
    assert [(a.employee_name, a.day, a.kind) for a in week.absences] == [
        ("Megan", "mon", "bank_holiday"), ("John", "tue", "bank_holiday"),
        ("Megan", "fri", "off"), ("Megan", "sat", "off"),
        ("John", "mon", "off"), ("John", "sun", "off"),
    ]
    assert week.unparsed_cells == []


@pytest.mark.parametrize("payload,stop_reason,reason", [
    ('{"week_start": null, "shifts": [', "max_tokens", "cut short"),
    (json.dumps(roster_response()), "max_tokens", "cut short"),
    ('{"week_start": null, "shifts": [', "end_turn", "valid roster"),
    ('{"week_start": null, "shifts": "invalid"}', "end_turn", "valid roster"),
    ('{"week_start": null, "shifts": []}', "refusal", "declined"),
])
def test_invalid_or_incomplete_model_output_is_not_imported_or_exposed(monkeypatch, payload, stop_reason, reason):
    stub_anthropic(monkeypatch, payload, stop_reason)
    result = asyncio.run(file_import.parse_upload("roster.png", b"test"))
    assert result.weeks == []
    assert reason in result.notes[0]
    assert "Expecting" not in result.notes[0]
    assert payload not in result.notes[0]


def test_missing_times_are_reported_and_not_invented():
    parsed = roster_response()
    parsed["shifts"][0]["end"] = None
    week = file_import._week_from_ocr(parsed, "image", 2026)
    assert len(week.shifts) == 7
    assert [(c["employee_name"], c["day"]) for c in week.unparsed_cells] == [("Megan", "tue")]


def test_invalid_selected_date_is_rejected_before_calling_the_model(monkeypatch):
    requests = stub_anthropic(monkeypatch, json.dumps(roster_response()))
    with pytest.raises(file_import.UnsupportedFile, match="valid week"):
        asyncio.run(file_import.parse_upload("roster.png", b"test", week_start="2026-02-30"))
    assert requests == []


def test_an_undated_photo_asks_for_a_week_instead_of_inventing_one(client, monkeypatch):
    stub_anthropic(monkeypatch, json.dumps(roster_response(None)))
    response = client.post(
        "/api/imports", headers=auth(register(client)),
        files={"file": ("roster.png", b"test", "image/png")},
    )
    assert response.status_code == 422
    assert "set the week" in response.json()["detail"]


def test_one_unreadable_pdf_page_does_not_lose_other_dated_weeks(monkeypatch):
    async def read(image, _):
        if image == b"bad":
            raise ValueError("AI did not return a valid roster.")
        return roster_response("2026-10-12")

    monkeypatch.setattr(llm, "ocr_roster_bytes", read)
    monkeypatch.setattr(file_import, "_pdf_to_images", lambda _: [b"bad", b"good"])
    result = asyncio.run(file_import.parse_upload(
        "roster.pdf", b"test", week_start="2026-10-26",
    ))
    assert [w.week_start for w in result.weeks] == ["2026-10-12"]
    assert len(result.weeks[0].shifts) == 8
    assert result.notes == ["page 1: could not be read (AI did not return a valid roster.)"]
