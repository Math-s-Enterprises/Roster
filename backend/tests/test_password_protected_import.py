"""Encrypted Excel uploads explain how to retry without changing shop data."""
import base64
import io
import zlib
from pathlib import Path

import pytest
from openpyxl import Workbook

from tests.test_api import auth, register


PASSWORD_MESSAGE = (
    "This Excel file is password-protected. Open it in Excel, save a copy "
    "without password protection, then upload that copy."
)


@pytest.fixture
def encrypted_workbook():
    encoded = (Path(__file__).parent / "fixtures" / "password_protected_roster.zlib.b64").read_bytes()
    return zlib.decompress(base64.b64decode(encoded))


def plain_workbook(restrict_editing=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "we November 1st 26"
    sheet.append(["Name", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    sheet.append(["Test Employee", "09:00-17:00", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF"])
    if restrict_editing:
        sheet.protection.password = "editing-only"
        sheet.protection.sheet = True
        workbook.security.workbookPassword = "editing-only"
        workbook.security.lockStructure = True
    data = io.BytesIO()
    workbook.save(data)
    workbook.close()
    return data.getvalue()


@pytest.mark.parametrize("extension", ["xlsx", "xlsm", "xltx", "xls"])
def test_an_encrypted_workbook_explains_how_to_retry_and_saves_nothing(
    client, encrypted_workbook, caplog, extension,
):
    headers = auth(register(client))
    response = client.post(
        "/api/imports", headers=headers,
        files={"file": (f"roster.{extension}", encrypted_workbook, "application/vnd.ms-excel")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == PASSWORD_MESSAGE
    assert "Import parse failed" not in caplog.text
    for path in ("/api/imports", "/api/imports/history", "/api/employees", "/api/rosters"):
        assert client.get(path, headers=headers).json() == []


@pytest.mark.parametrize("restrict_editing", [False, True])
def test_a_readable_workbook_is_previewed_even_if_editing_is_password_protected(client, restrict_editing):
    response = client.post(
        "/api/imports", headers=auth(register(client)),
        files={"file": ("roster.xlsx", plain_workbook(restrict_editing))},
    )
    assert response.status_code == 201, response.text
    assert response.json()["summary"]["shifts"] == 1
    assert response.json()["weeks"][0]["preview"][0]["start"] == "09:00"


@pytest.mark.parametrize("data", [b"not a workbook", b"PK\x03\x04truncated", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504)])
def test_a_damaged_workbook_is_not_misreported_as_password_protected(client, data):
    response = client.post(
        "/api/imports", headers=auth(register(client)),
        files={"file": ("damaged.xlsx", data)},
    )
    assert response.status_code == 400
    assert "password-protected" not in response.json()["detail"]


@pytest.mark.parametrize("missing_stream", ["EncryptionInfo", "EncryptedPackage"])
def test_encryption_requires_both_directory_streams_not_just_words_in_the_file(
    client, encrypted_workbook, missing_stream,
):
    name = missing_stream.encode("utf-16le")
    renamed = ("X" * len(missing_stream)).encode("utf-16le")
    data = encrypted_workbook.replace(name, renamed) + name
    response = client.post(
        "/api/imports", headers=auth(register(client)),
        files={"file": ("other-container.xlsx", data)},
    )
    assert response.status_code == 400
    assert "password-protected" not in response.json()["detail"]
