"""Upload historical rosters — spreadsheet, PDF or photo.

Deliberately two-phase. An upload is parsed and stored for review; nothing
reaches the roster history until it is explicitly confirmed. Rosters read
from a photo are a model's best guess, and quietly importing an approximation
of a shop's history would poison the very data the scheduler learns from — in
a way that is close to impossible to detect later.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app import db
from app.services import file_import, hierarchy, llm
from app.services.learning import training_summary
from app.services.scheduler import shift_duration_minutes
from app.services.shop_service import log_activity
from app.tenancy import ShopScope, CurrentScope

log = logging.getLogger("roster.imports")
router = APIRouter(prefix="/imports", tags=["imports"])

DEFAULT_RATE = 13.0
DEFAULT_MAX_WEEKLY_HOURS = 40.0
DEFAULT_AGE = 25

"""Roles are resolved against the shop's own ladder — see hierarchy.match_role.

There used to be a ROLE_MAP here that rewrote sheet titles onto a fixed
vocabulary: every kind of manager became "Manager", and both "Night Shift"
and "Goods Inwards" became "Stocker". It consulted nothing about the shop, so
a manager who had configured their real job titles during setup got them
silently replaced by roles they had never chosen — and five distinct rungs of
the hierarchy collapsed into one, destroying the seniority order the
scheduler allocates hours by.
"""


class CommitRequest(BaseModel):
    """Which weeks to import, and how sheet names map to real employees."""
    week_starts: Optional[List[str]] = Field(
        None, description="Weeks to import. Omit to import every usable week."
    )
    # name -> employee_id, or name -> "" to create a new employee
    employee_map: Dict[str, str] = Field(default_factory=dict)
    skip_unmapped: bool = Field(
        True, description="Skip shifts whose employee is not mapped or created."
    )
    past_staff: List[str] = Field(
        default_factory=list,
        description="Names to import as leavers: their shifts are kept so the "
                    "history shows the staffing the shop really ran, but they "
                    "are never rostered and never appear in the staff list.",
    )


def _map_role(raw: Optional[str], shop: Optional[Dict[str, Any]] = None) -> str:
    """A sheet's job title, as this shop spells it.

    Falls back to the bottom of the shop's ladder when the sheet says nothing
    at all, rather than to a hardcoded "Floor Assistant" that a shop with
    different job titles would never use.
    """
    matched = hierarchy.match_role(raw, shop)
    if matched:
        return matched
    ladder = hierarchy.get_hierarchy(shop)
    return ladder[-1] if ladder else "Floor Assistant"


# Imported staff are created with no email, because a roster spreadsheet does
# not contain one. There used to be a _placeholder_email() here inventing
# "jane@imported.shop_645.local", which failed EmployeeIn's own validator
# twice over — an underscore is illegal in a domain, and ".local" is a
# reserved name — so imported staff could never afterwards be edited.
#
# Dispatch reports anyone without an address instead of appearing to send.


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_roster_file(
    file: UploadFile = File(...),
    week_start: Optional[str] = Form(
        None,
        description="Monday to assign to any week the file itself does not date. "
                    "Needed for CSV exports and photos.",
    ),
    scope: ShopScope = CurrentScope,
):
    """Parse an uploaded roster and store it for review. Imports nothing."""
    data = await file.read()

    employees = await scope.employees.find(limit=1000)
    known_names = [e["name"] for e in employees]

    try:
        result = await file_import.parse_upload(
            file.filename or "upload",
            data,
            content_type=file.content_type or "",
            known_names=known_names,
            week_start=week_start,
        )
    except file_import.UnsupportedFile as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except llm.LLMUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Reading photos and PDFs needs AI to be configured. {exc}",
        )
    except Exception as exc:
        log.exception("Import parse failed")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not read that file: {exc}")

    usable = [w for w in result.weeks if w.is_usable]
    if not usable:
        # Distinguish "unreadable" from "read fine, but undated" — the second
        # is fixable by the user in one step, and saying so saves them
        # concluding the file is unsupported.
        undated = [w for w in result.weeks if w.shifts and not w.week_start]
        if undated and not week_start:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Read {sum(len(w.shifts) for w in undated)} shifts, but the file does "
                f"not say which week they belong to. Re-upload and set the week.",
            )
        detail = "; ".join(result.notes) if result.notes else ""
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"No rosters could be read from that file. {detail}".strip(),
        )

    # Match sheet names against existing staff so the review screen can show
    # who is already known and who would be created.
    existing = {e["name"].strip().lower(): e for e in employees}
    people = {}
    for week in usable:
        for name, role in week.employees.items():
            match = existing.get(name.strip().lower())
            people.setdefault(name, {
                "name": name,
                "role": _map_role(role, scope.shop),
                # Shown alongside so the manager can see when the sheet's
                # wording and the shop's ladder disagree, before committing.
                "role_in_file": (role or "").strip() or None,
                "matched_employee_id": match["employee_id"] if match else None,
                "shifts": 0,
            })
    for week in usable:
        for shift in week.shifts:
            if shift.employee_name in people:
                people[shift.employee_name]["shifts"] += 1

    already = {
        r["week_start"]
        for r in await scope.rosters.find({"historical": True}, limit=500)
    }

    import_id = f"imp_{uuid.uuid4().hex[:12]}"
    document = {
        "import_id": import_id,
        "filename": file.filename,
        "kind": result.kind,
        "pages": result.pages,
        "needs_review": result.needs_review,
        "notes": result.notes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "committed": False,
        "weeks": [w.to_dict() for w in usable],
    }
    await scope.imports.insert(document)

    return {
        "import_id": import_id,
        "filename": file.filename,
        "kind": result.kind,
        "pages": result.pages,
        # Photos and PDFs are a model's reading of a picture; spreadsheets are
        # parsed exactly. The UI uses this to decide how loudly to warn.
        "needs_review": result.needs_review,
        "notes": result.notes,
        "summary": {
            "weeks": len(usable),
            "already_imported": len([w for w in usable if w.week_start in already]),
            "shifts": sum(len(w.shifts) for w in usable),
            "employees": len(people),
            "new_employees": len([p for p in people.values() if not p["matched_employee_id"]]),
            "warnings": sum(len(w.warnings) for w in usable),
            "unreadable_cells": sum(len(w.unparsed_cells) for w in usable),
            "date_range": [
                min(w.week_start for w in usable),
                max(w.week_start for w in usable),
            ],
        },
        "people": sorted(people.values(), key=lambda p: -p["shifts"]),
        "weeks": [
            {
                "week_start": w.week_start,
                "sheet_name": w.sheet_name,
                "shifts": len(w.shifts),
                "already_imported": w.week_start in already,
                "warnings": w.warnings,
                "unparsed_cells": w.unparsed_cells,
                "preview": [s.to_dict() for s in w.shifts[:8]],
            }
            for w in usable
        ],
    }


@router.get("/capabilities")
async def import_capabilities():
    """Which upload formats this deployment can actually read.

    Spreadsheets and CSV are always available — they are parsed in-process.
    PDFs additionally need `pymupdf` to rasterise pages, and both PDFs and
    photos need an LLM key to read the resulting image.

    Exposed so the UI can say so up front. Offering a customer a "drop a
    photo here" box that returns a 503 after they have waited for the upload
    is a worse experience than telling them plainly that it is not set up.
    """
    pdf_renderer = True
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        pdf_renderer = False

    return {
        "spreadsheet": True,
        "csv": True,
        # A PDF needs both halves: rasterise, then read.
        "pdf": pdf_renderer and llm.enabled,
        "image": llm.enabled,
        "reasons": {
            **({} if llm.enabled else {
                "llm": "Reading photos and PDFs needs ANTHROPIC_API_KEY in backend/.env."
            }),
            **({} if pdf_renderer else {
                "pdf_renderer": "PDF support needs the 'pymupdf' package. "
                                "Run: pip install -r requirements.txt"
            }),
        },
        "max_bytes": file_import.MAX_UPLOAD_BYTES,
        "max_pdf_pages": file_import.MAX_PDF_PAGES,
    }


# Declared after /capabilities so the literal path wins over any future
# "/{import_id}" style route added below it.
@router.get("")
async def list_imports(scope: ShopScope = CurrentScope):
    records = await scope.imports.find(limit=50, sort=[("uploaded_at", -1)])
    return [
        {
            "import_id": r["import_id"],
            "filename": r.get("filename"),
            "kind": r.get("kind"),
            "uploaded_at": r.get("uploaded_at"),
            "committed": r.get("committed", False),
            "weeks": len(r.get("weeks", [])),
        }
        for r in records
    ]


async def _write_week(
    scope: ShopScope,
    week: Dict[str, Any],
    name_to_id: Dict[str, str],
    import_id: str,
) -> tuple[bool, int]:
    """Turn one parsed week into a historical roster.

    Shared by the first commit and by restoring a week that was removed, so
    the two cannot drift into producing subtly different rosters from the
    same source data.

    Returns (written, shifts_dropped). A week whose every shift belongs to an
    unmapped name writes nothing rather than an empty roster, which would
    otherwise count as a week of history teaching the solver nothing.
    """
    shifts = []
    dropped = 0
    for shift in week.get("shifts", []):
        employee_id = name_to_id.get(shift["employee_name"])
        if not employee_id:
            dropped += 1
            continue
        shifts.append({
            "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
            "employee_id": employee_id,
            "day": shift["day"],
            "start": shift["start"],
            "end": shift["end"],
            "fixed": False,
        })
    if not shifts:
        return False, dropped

    await scope.rosters.insert({
        "roster_id": f"hist_{uuid.uuid4().hex[:12]}",
        "week_start": week["week_start"],
        "version": "v1.0-hist",
        "shifts": shifts,
        "issues": [], "critical_issues": [],
        "compliance_score": 100,
        "labor_cost": 0,
        "total_hours": round(sum(
            shift_duration_minutes(s["start"], s["end"]) / 60 for s in shifts
        ), 1),
        "utilization": 0,
        "per_employee_hours": {},
        "approved": True,
        "historical": True,
        "source_import": import_id,
        "source_sheet": week.get("sheet_name"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return True, dropped


@router.post("/{import_id}/commit")
async def commit_import(
    import_id: str, payload: CommitRequest, scope: ShopScope = CurrentScope
):
    """Write reviewed weeks into the roster history."""
    record = await scope.imports.find_one({"import_id": import_id})
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    if record.get("committed"):
        raise HTTPException(status.HTTP_409_CONFLICT, "That import has already been applied.")

    weeks = record.get("weeks", [])
    if payload.week_starts is not None:
        wanted = set(payload.week_starts)
        weeks = [w for w in weeks if w["week_start"] in wanted]
    if not weeks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No weeks selected.")

    existing = {
        e["name"].strip().lower(): e["employee_id"]
        for e in await scope.employees.find(limit=1000)
    }

    # Resolve every name to an employee id before writing any roster, so a
    # half-mapped import cannot produce shifts pointing at nobody.
    name_to_id: Dict[str, str] = {}
    created_names: List[str] = []
    past_created: List[str] = []
    roles = {
        p["name"]: p.get("role")
        for week in record["weeks"] for p in
        [{"name": n, "role": r} for n, r in
         [(e["name"], e.get("role")) for e in week.get("employees", [])]]
    }

    # Leavers named by the manager. Their shifts are kept and their record is
    # created, because a shift must have an owner — but the record is flagged
    # so it never reaches the staff list or the solver. Dropping them instead
    # would make thirty weeks of history show a thinner shop than really
    # worked, and the solver copies the staffing it is shown.
    leavers = {n.strip().lower() for n in payload.past_staff}

    for week in weeks:
        for entry in week.get("employees", []):
            name = entry["name"]
            if name in name_to_id:
                continue
            chosen = payload.employee_map.get(name)
            if chosen:
                name_to_id[name] = chosen
                continue
            match = existing.get(name.strip().lower())
            if match:
                name_to_id[name] = match
                continue
            is_leaver = name.strip().lower() in leavers
            if payload.skip_unmapped and not is_leaver and name not in payload.employee_map:
                continue
            employee_id = f"emp_{uuid.uuid4().hex[:12]}"
            await scope.employees.insert({
                "employee_id": employee_id,
                "name": name,
                "email": None,
                "role": _map_role(roles.get(name) or entry.get("role"), scope.shop),
                "age": DEFAULT_AGE,
                "hourly_rate": DEFAULT_RATE,
                "max_weekly_hours": DEFAULT_MAX_WEEKLY_HOURS,
                "preferred_days_off": [],
                "departments": ["Shop Floor"],
                "imported": True,
                "is_active": not is_leaver,
                "past_staff": is_leaver,
            })
            name_to_id[name] = employee_id
            if not is_leaver:
                created_names.append(name)
            else:
                past_created.append(name)

    already = {
        r["week_start"]
        for r in await scope.rosters.find({"historical": True}, limit=500)
    }

    imported, skipped_weeks, skipped_shifts = 0, 0, 0
    for week in weeks:
        if week["week_start"] in already:
            skipped_weeks += 1
            continue

        written, dropped = await _write_week(scope, week, name_to_id, import_id)
        skipped_shifts += dropped
        if written:
            imported += 1
        else:
            skipped_weeks += 1

    await scope.imports.update_one({"import_id": import_id}, {
        "committed": True,
        "committed_at": datetime.now(timezone.utc).isoformat(),
        "weeks_imported": imported,
    })

    return {
        "ok": True,
        "weeks_imported": imported,
        "weeks_skipped": skipped_weeks,
        "employees_created": len(created_names),
        "created": created_names,
        # Reported separately so "31 people created" never includes leavers
        # the manager explicitly said were not staff.
        "past_staff_kept": past_created,
        "shifts_skipped": skipped_shifts,
    }


@router.delete("/{import_id}")
async def discard_import(import_id: str, scope: ShopScope = CurrentScope):
    if not await scope.imports.delete_one({"import_id": import_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return {"ok": True}


@router.get("/history")
async def list_imported_weeks(scope: ShopScope = CurrentScope):
    """The weeks that came from an upload, newest first.

    Kept separate from the roster history proper because these are the only
    approved weeks that can be removed. See `remove_imported_week` for why.
    """
    rosters = await scope.rosters.find(
        {"historical": True}, limit=500, sort=[("week_start", -1)]
    )
    return [
        {
            "roster_id": r["roster_id"],
            "week_start": r["week_start"],
            "shifts": len(r.get("shifts", [])),
            "total_hours": r.get("total_hours", 0),
            "source_sheet": r.get("source_sheet"),
            "source_import": r.get("source_import"),
            "created_at": r.get("created_at"),
        }
        for r in rosters
    ]


@router.delete("/history/{roster_id}")
async def remove_imported_week(roster_id: str, scope: ShopScope = CurrentScope):
    """Remove an imported week from the roster history.

    Imported weeks are the one kind of approved past week that can be taken
    back out, and the distinction is deliberate.

    A week this app generated and approved is a record of a decision the
    manager made and staff were told to work; rewriting it afterwards would
    change history the scheduler has already learned from. That is why
    unapproving a finished week is refused.

    An imported week is not that. It is data the manager loaded, and loading
    the wrong file — the wrong sheet, a misread photo, somebody else's shop —
    is an ordinary mistake with no way to spot it later except by looking at
    the rosters it produces. Without this it would be permanent.

    Deleting rather than unapproving, because there is no draft underneath to
    go back to. Re-upload the file to bring the week back.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That week was not found")

    if not roster.get("historical"):
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": (
                f"Week of {roster['week_start']} was built here, not imported, "
                "so it cannot be removed."
            ),
            "reasons": [
                "Rosters this app generated are the record of what staff were "
                "told to work. Unapprove the week instead if it is still open.",
            ],
        })

    await scope.rosters.delete_one({"roster_id": roster_id})

    # Noted on the source import so the week can be put back without the
    # original file. The parsed data is still sitting there; all that is
    # missing is a way to reach it, and re-uploading is no help to somebody
    # who deleted the spreadsheet months ago.
    source = roster.get("source_import")
    restorable = False
    if source:
        record = await scope.imports.find_one({"import_id": source})
        if record and any(
            w.get("week_start") == roster["week_start"]
            for w in record.get("weeks", [])
        ):
            removed = [
                w for w in record.get("removed_weeks", [])
                if w.get("week_start") != roster["week_start"]
            ]
            removed.append({
                "week_start": roster["week_start"],
                "removed_at": datetime.now(timezone.utc).isoformat(),
            })
            await scope.imports.update_one(
                {"import_id": source}, {"removed_weeks": removed}
            )
            restorable = True

    await log_activity(
        scope.shop_id, "import_week_removed",
        f"Removed imported week of {roster['week_start']} "
        f"({len(roster.get('shifts', []))} shifts) from roster history",
    )
    return {
        "ok": True,
        "week_start": roster["week_start"],
        "restorable": restorable,
    }


@router.get("/removed")
async def list_removed_weeks(scope: ShopScope = CurrentScope):
    """Weeks taken out of the history that the source upload can still put back.

    Computed by checking each noted removal against what is in the history
    now, rather than trusting the note alone — a week re-imported by
    re-uploading the file must stop being offered here.
    """
    live = {
        r["week_start"]
        for r in await scope.rosters.find({"historical": True}, limit=500)
    }

    out: List[Dict[str, Any]] = []
    for record in await scope.imports.find({"committed": True}, limit=100):
        weeks = {w.get("week_start"): w for w in record.get("weeks", [])}
        for note in record.get("removed_weeks", []):
            week = weeks.get(note.get("week_start"))
            if not week or note["week_start"] in live:
                continue
            out.append({
                "import_id": record["import_id"],
                "week_start": note["week_start"],
                "removed_at": note.get("removed_at"),
                "shifts": len(week.get("shifts", [])),
                "sheet_name": week.get("sheet_name"),
                "filename": record.get("filename"),
            })

    return sorted(out, key=lambda w: w["week_start"], reverse=True)


class RestoreRequest(BaseModel):
    import_id: str
    week_start: str


@router.post("/removed/restore")
async def restore_removed_week(
    payload: RestoreRequest, scope: ShopScope = CurrentScope
):
    """Put a removed week back from the upload it came from.

    Re-uploading the same file already works and skips whatever is present,
    so this exists for the case that one cannot cover: the file is gone. The
    parsed week never left the database — only the roster built from it did.

    Names are resolved against the current employee list. Anybody who was
    created by the original import is still there, so in practice this maps
    cleanly; a name that has since been renamed is recreated rather than
    dropped, because losing shifts silently is the worse failure.
    """
    record = await scope.imports.find_one({"import_id": payload.import_id})
    if not record:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The upload this week came from is no longer available. "
            "Re-upload the file to bring it back.",
        )

    week = next(
        (w for w in record.get("weeks", []) if w.get("week_start") == payload.week_start),
        None,
    )
    if not week:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"That upload does not contain the week of {payload.week_start}.",
        )

    clash = await scope.rosters.find_one({
        "week_start": payload.week_start, "historical": True,
    })
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": f"Week of {payload.week_start} is already in your history.",
            "reasons": ["Remove the one that is there before restoring this one."],
        })

    existing = {
        e["name"].strip().lower(): e["employee_id"]
        for e in await scope.employees.find(limit=1000)
    }
    name_to_id: Dict[str, str] = {}
    created: List[str] = []
    for entry in week.get("employees", []):
        name = entry["name"]
        if name in name_to_id:
            continue
        match = existing.get(name.strip().lower())
        if match:
            name_to_id[name] = match
            continue
        employee_id = f"emp_{uuid.uuid4().hex[:12]}"
        await scope.employees.insert({
            "employee_id": employee_id,
            "name": name,
            "email": None,
            "role": _map_role(entry.get("role"), scope.shop),
            "age": DEFAULT_AGE,
            "hourly_rate": DEFAULT_RATE,
            "max_weekly_hours": DEFAULT_MAX_WEEKLY_HOURS,
            "preferred_days_off": [],
            "departments": ["Shop Floor"],
            "imported": True,
        })
        name_to_id[name] = employee_id
        created.append(name)

    written, dropped = await _write_week(
        scope, week, name_to_id, payload.import_id
    )
    if not written:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"None of the {dropped} shift(s) in that week could be matched to "
            "an employee, so nothing was restored.",
        )

    await scope.imports.update_one({"import_id": payload.import_id}, {
        "removed_weeks": [
            w for w in record.get("removed_weeks", [])
            if w.get("week_start") != payload.week_start
        ],
    })
    await log_activity(
        scope.shop_id, "import_week_restored",
        f"Restored imported week of {payload.week_start} from {record.get('filename')}",
    )
    return {
        "ok": True,
        "week_start": payload.week_start,
        "shifts_restored": len(week.get("shifts", [])) - dropped,
        "employees_created": created,
    }


# Declared last so the literal path is not swallowed by "/{import_id}".
@router.get("/learning-summary")
async def learning_summary(scope: ShopScope = CurrentScope):
    """How much history the solver currently has to learn from.

    Lives with importing because that is the only thing that changes it, and
    it answers the question anybody asks straight after an import: did that
    actually give the roster more to go on?
    """
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    return training_summary(approved)
