"""The week as a one-page grid, for attaching to an email.

WHY THIS IS NOT THE FRONTEND'S PDF
----------------------------------
The browser already builds one with jsPDF, but that runs in the manager's
browser and dispatch runs on the server, so it cannot be reused. The two also
answer different questions: the browser's is a flat LIST of shifts, one row
each, which is fine to scroll. What an owner wants attached to an email is
what goes on the wall — everybody against every day, readable at a glance.

So this deliberately reproduces the PRINTED ROTA rather than the browser's
export.

WHY REPORTLAB
-------------
It draws directly and has no system dependencies. WeasyPrint would render the
existing HTML, which sounds like less duplication, but it needs Cairo and
Pango installed on the host — a deployment problem in exchange for a layout
that still would not match the print sheet's page-fitting.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from xml.sax.saxutils import escape
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_LABELS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
           "fri": "Fri", "sat": "Sat", "sun": "Sun"}

# Paper is white whatever the screen is doing — the same rule the print
# stylesheet follows. A dark rota costs a fortune in toner and reads worse.
_INK = colors.HexColor("#111111")
_MUTE = colors.HexColor("#6b7280")
_RULE = colors.HexColor("#d4d4d8")
_BAND = colors.HexColor("#f4f4f5")


def _date_for(week_start: str, day: str) -> Optional[Any]:
    try:
        monday = datetime.strptime(week_start, "%Y-%m-%d").date()
        return monday + timedelta(days=DAYS.index(day))
    except (TypeError, ValueError):
        return None


def _short(value) -> str:
    # %-d is not portable and %#d is Windows-only, so the day is built by hand.
    return f"{value.day} {value:%b}" if value else ""


def _leave_label(shift: Dict[str, Any]) -> str:
    if shift.get("paid_holiday"):
        return "Holiday"
    if shift.get("unpaid_holiday"):
        return "Unpaid"
    if shift.get("sick"):
        return "Sick"
    return ""


def build_roster_pdf(
    shop_name: str,
    week_start: str,
    people: List[Dict[str, Any]],
    breaks_are_paid: bool = False,
) -> bytes:
    """A landscape A4 grid: everybody down the side, the week across.

    `people` items need: name, role (optional), shifts.
    """
    from app.services.scheduler import paid_hours

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"{shop_name} — week of {week_start}",
        author="Roster",
    )

    monday, sunday = _date_for(week_start, "mon"), _date_for(week_start, "sun")
    span = (f"{monday:%a} {_short(monday)} – {sunday:%a} {_short(sunday)} {sunday:%Y}"
            if monday and sunday else f"Week of {week_start}")

    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15,
                           textColor=_INK, spaceAfter=1)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9.5,
                         textColor=_MUTE)
    person_style = ParagraphStyle("p", fontName="Helvetica", fontSize=9,
                                  leading=11, textColor=_INK)

    # Two header rows: the day, and the date under it. A rota that says only
    # "Wed" is the same ambiguity the email had.
    head = [""] + [
        f"{_LABELS[d]}\n{_short(_date_for(week_start, d))}" for d in DAYS
    ] + ["Total"]

    rows, grand = [head], 0.0
    for person in people:
        by_day: Dict[str, List[Dict[str, Any]]] = {}
        for shift in person.get("shifts", []):
            by_day.setdefault(shift.get("day"), []).append(shift)

        hours, cells = 0.0, []
        for day in DAYS:
            entries = sorted(by_day.get(day, []),
                             key=lambda s: s.get("start") or "")
            if not entries:
                cells.append("")
                continue
            parts = []
            for shift in entries:
                leave = _leave_label(shift)
                start, end = shift.get("start"), shift.get("end")
                if leave or not (start and end):
                    parts.append(leave or "—")
                else:
                    hours += paid_hours(start, end, breaks_paid=breaks_are_paid)
                    # ONE LINE. These were stacked on the assumption that a
                    # range would not fit a seventh of a landscape page, which
                    # was never measured: "17:30 – 23:00" is 55pt at 9pt in a
                    # 77pt cell. Stacked, the two times read as two separate
                    # facts rather than one shift.
                    parts.append(f"{start} – {end}")
            cells.append("\n".join(parts))

        grand += hours
        name = person.get("name", "")
        role = person.get("role") or ""
        who = Paragraph(
            f"<b>{escape(name)}</b>"
            + (f"<br/><font size=7.5 color='#6b7280'>{escape(role)}</font>"
               if role else ""),
            person_style,
        )
        rows.append([who] + cells + [f"{hours:g}h"])

    rows.append([f"{len(people)} on the rota"] + [""] * 7 + [f"{grand:g}h"])

    widths = [38 * mm] + [31 * mm] * 7 + [16 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 1), (-1, -1), "Helvetica"),
        # 9pt rather than 7.5: this gets printed and read from a distance,
        # and the page has room now the times are on one line.
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
        ("TEXTCOLOR", (1, 0), (-1, 0), _MUTE),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Vertical rules only between DAY columns, plus a rule under each
        # person. A full grid boxes every cell and turns the page into a
        # mesh; the eye is following one person across the week.
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _RULE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.4, _RULE),
        ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, _MUTE),
        ("BACKGROUND", (0, 0), (-1, 0), _BAND),
        ("BACKGROUND", (0, -1), (-1, -1), _BAND),
        # Roomier rows. A rota is scanned, not read.
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    doc.build([
        Paragraph(shop_name, title),
        Paragraph(span, sub),
        Spacer(1, 6 * mm),
        table,
    ])
    return buffer.getvalue()
