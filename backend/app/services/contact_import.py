"""Read staff names and email addresses out of a spreadsheet they filled in.

WHY THIS SHAPE
--------------
The workflow this serves: a manager shares a sheet, the staff type their own
name and email into it, the manager uploads the result. That means the file is
NOT written by a developer. It will have a title row above the headers, a
"Notes" column somebody added, blank rows where people were deleted, headers
reading "Email address" or "E-mail" or nothing at all, and names in whichever
column felt natural.

So the columns are not located by header. Every row is scanned for a cell that
LOOKS like an email address, and the name is taken from the same row. A header
row contains no email address and is skipped without needing to be recognised;
so is the title, the blank rows, and the notes column.

That also means the parser never has to be told which file format it is
looking at beyond xlsx versus text.

MATCHING IS THE DANGEROUS PART
------------------------------
Getting this wrong sends one person's working pattern to another, which is a
data-protection incident rather than a bug. So a row is applied only when it
matches EXACTLY ONE active employee. Ambiguity is reported for a human to
resolve — never guessed, never "closest match".
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# Loose on purpose. Rejecting a real address is worse than accepting a wrong
# one: the wrong one is visible in the preview and reported by dispatch, the
# rejected one just silently never arrives.
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

MAX_ROWS = 2000


class UnreadableFile(Exception):
    """The file could not be opened at all."""


@dataclass
class ContactRow:
    """One line of the uploaded file, and what we could make of it."""

    row: int
    name: str
    email: str
    employee_id: Optional[str] = None
    employee_name: str = ""
    current_email: str = ""
    status: str = "ready"       # ready | conflict | ambiguous | unknown | duplicate
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row": self.row, "name": self.name, "email": self.email,
            "employee_id": self.employee_id, "employee_name": self.employee_name,
            "current_email": self.current_email, "status": self.status,
            "note": self.note,
        }


@dataclass
class ContactImport:
    rows: List[ContactRow] = field(default_factory=list)
    unmatched_staff: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return {
            "rows": [r.to_dict() for r in self.rows],
            "counts": counts,
            "unmatched_staff": self.unmatched_staff,
        }


def fold(name: str) -> str:
    """Compare names without being defeated by an accent or a capital.

    Roisín and Roisin are one person, and the sheet will be typed on whatever
    keyboard was to hand. Decomposing to NFKD and dropping combining marks
    makes both spellings land on the same key.
    """
    stripped = unicodedata.normalize("NFKD", (name or "").strip())
    return " ".join(
        "".join(c for c in stripped if not unicodedata.combining(c)).lower().split()
    )


def _decode(data: bytes) -> str:
    # Sheets saved from Excel on Windows are routinely not UTF-8. latin-1
    # never raises, which is exactly why it is last rather than absent.
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnreadableFile("Could not read that file as text.")


def read_rows(data: bytes, filename: str) -> List[List[Any]]:
    """Every cell of the upload, as rows. xlsx or any delimited text."""
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm", ".xltx")):
        try:
            import openpyxl
        except ImportError:  # pragma: no cover
            raise UnreadableFile("Spreadsheet support is not installed.")
        try:
            workbook = openpyxl.load_workbook(
                io.BytesIO(data), data_only=True, read_only=True)
        except Exception as exc:
            raise UnreadableFile(f"That spreadsheet could not be opened: {exc}")
        rows: List[List[Any]] = []
        # Every sheet, because a shared file often has one tab per department
        # and nobody thinks to mention it.
        for name in workbook.sheetnames:
            for row in workbook[name].iter_rows(values_only=True):
                rows.append(list(row))
                if len(rows) >= MAX_ROWS:
                    break
        workbook.close()
        return rows

    text = _decode(data)
    delimiter = "\t" if lower.endswith(".tsv") else ","
    # A one-column paste has no delimiter at all; csv handles that fine.
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)][:MAX_ROWS]


def _name_and_email(cells: Sequence[Any]) -> Optional[tuple]:
    """The email in this row, and the likeliest name beside it.

    Returns None for any row without an address — which silently disposes of
    the title row, the header row, blank rows and separator rows without
    having to recognise any of them.
    """
    values = [str(c).strip() for c in cells if c is not None and str(c).strip()]
    email = next((v for v in values if EMAIL.match(v)), None)
    if not email:
        return None
    # The name is the first cell that is not an address and not a bare number
    # (staff numbers and row counters live in these sheets too).
    name = next(
        (v for v in values
         if v != email and not EMAIL.match(v)
         and not v.replace(".", "", 1).isdigit()),
        "",
    )
    return name, email


def parse(data: bytes, filename: str) -> List[ContactRow]:
    """Name/email pairs found anywhere in the file, in order."""
    found: List[ContactRow] = []
    for index, cells in enumerate(read_rows(data, filename), start=1):
        pair = _name_and_email(cells)
        if pair:
            found.append(ContactRow(row=index, name=pair[0], email=pair[1]))
    return found


def match(
    rows: List[ContactRow],
    employees: List[Dict[str, Any]],
    *,
    allow_replace: bool = False,
) -> ContactImport:
    """Resolve each row against the shop's staff.

    `employees` should already be filtered to the active ones: an address
    belonging to somebody who has left is not a match, it is a mistake.
    """
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for employee in employees:
        full = fold(employee.get("name", ""))
        if not full:
            continue
        by_name.setdefault(full, []).append(employee)
        first = full.split()[0] if full.split() else ""
        if first and first != full:
            by_name.setdefault(first, []).append(employee)

    claimed: Dict[str, ContactRow] = {}
    for row in rows:
        candidates = by_name.get(fold(row.name), [])

        if not row.name:
            row.status = "unknown"
            row.note = "No name in that row — cannot tell who it belongs to."
            continue
        if not candidates:
            row.status = "unknown"
            row.note = f"No active employee called “{row.name}”."
            continue
        if len(candidates) > 1:
            row.status = "ambiguous"
            row.note = (
                f"{len(candidates)} people answer to “{row.name}” "
                f"({', '.join(c.get('name', '?') for c in candidates)}). "
                f"Use the full name."
            )
            continue

        employee = candidates[0]
        row.employee_id = employee.get("employee_id")
        row.employee_name = employee.get("name", "")
        row.current_email = (employee.get("email") or "").strip()

        # One address, one person. Two rows sharing an inbox is far more
        # likely a copy-paste slip than a real arrangement, and the cost of
        # being wrong is one person reading another's hours.
        previous = claimed.get(row.email.lower())
        if previous:
            row.status = "duplicate"
            row.note = (
                f"That address is already on row {previous.row} for "
                f"{previous.employee_name or previous.name}."
            )
            continue
        claimed[row.email.lower()] = row

        if row.current_email and row.current_email.lower() != row.email.lower():
            row.status = "ready" if allow_replace else "conflict"
            row.note = (
                f"Currently {row.current_email}."
                + ("" if allow_replace else " Tick “replace existing” to change it.")
            )
        elif row.current_email:
            row.status = "conflict"
            row.note = "Already set to that address."

    matched = {r.employee_id for r in rows if r.employee_id}
    unmatched = [
        e.get("name", "?") for e in employees
        if e.get("employee_id") not in matched
        and not (e.get("email") or "").strip()
    ]
    return ContactImport(rows=rows, unmatched_staff=sorted(unmatched))
