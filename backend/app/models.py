"""Request/response schemas (Pydantic).

These are the API's contract with the frontend — they are NOT database
models. MongoDB stores plain dicts; these classes validate what comes in
over HTTP and shape what goes back out.

Anything a client sends is parsed and validated against one of these before
a route handler runs, so handlers can assume well-formed input.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

DayKey = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_TIME_HELP = "Time as 24-hour HH:MM, e.g. '09:00' or '23:30'."


def _validate_hhmm(v: str) -> str:
    """Reject malformed times at the API boundary.

    The scheduler does integer arithmetic on these strings; a bad value like
    '9am' or '25:00' would otherwise surface as a confusing crash deep inside
    roster generation rather than a clear 422 at the edge.
    """
    parts = v.split(":")
    if len(parts) != 2:
        raise ValueError(_TIME_HELP)
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(_TIME_HELP)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(_TIME_HELP)
    return f"{h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="At least 8 characters.")
    name: str = Field(min_length=1)
    shop_name: Optional[str] = None


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthReq(BaseModel):
    """ID token issued by Google Identity Services in the browser."""
    credential: str


class ForgotPasswordReq(BaseModel):
    email: EmailStr


class ResetPasswordReq(BaseModel):
    token: str
    password: str = Field(min_length=8, description="At least 8 characters.")


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------
class ShopHours(BaseModel):
    day: DayKey
    open: str
    close: str
    closed: bool = False

    _v_open = field_validator("open")(_validate_hhmm)
    _v_close = field_validator("close")(_validate_hhmm)


class ShiftTemplate(BaseModel):
    template_id: Optional[str] = None
    name: str
    start: str
    end: str
    min_staff: int = Field(1, ge=1, le=50)

    _v_start = field_validator("start")(_validate_hhmm)
    _v_end = field_validator("end")(_validate_hhmm)


class RosterRecipient(BaseModel):
    """Somebody who is sent the roster but does not appear on it."""

    name: str = Field(default="", max_length=80)
    email: EmailStr


class ShopUpdate(BaseModel):
    """Partial update — every field optional, only what's sent is written."""
    name: Optional[str] = None
    hours: Optional[List[ShopHours]] = None
    min_shift_hours: Optional[float] = Field(None, gt=0, le=24)
    max_shift_hours: Optional[float] = Field(None, gt=0, le=24)
    roles: Optional[List[str]] = None
    departments: Optional[List[str]] = None
    multi_department: Optional[bool] = None
    open_24h: Optional[bool] = None
    shift_templates: Optional[List[ShiftTemplate]] = None
    onboarded: Optional[bool] = None
    # Ordered most senior first. Drives who is considered first when
    # allocating hours — one of the rules that cannot be overridden.
    role_hierarchy: Optional[List[str]] = None
    # What a roster file's wording means in this shop's own vocabulary:
    # {"Shop Floor": "Floor Assistant", "Ass Manager": "Assistant Manager"}.
    # Imports match loosely enough to forgive "Mgr" for "Manager", but an
    # abbreviation only this shop uses has to be stated rather than guessed —
    # guessing is what silently rewrote everybody's job title before.
    role_aliases: Optional[Dict[str, str]] = None
    # People who get the WHOLE roster when it is dispatched, without working
    # in the shop — an area manager, a franchise owner, head office. They are
    # deliberately NOT employees: giving them an employee record to hang an
    # address off would put them in the seniority ladder, in the solver's
    # candidate list and on the printed rota, and somebody would eventually be
    # rostered a shift they do not work.
    #
    # Name and email only. Nothing here needs an age, a wage or a contract.
    roster_recipients: Optional[List["RosterRecipient"]] = None
    # Paid sick leave per year, in DAYS — which is how the law writes it
    # (Ireland's statutory entitlement is 5) and how a manager thinks. It is
    # spent in hours, converted per person from their own usual shift, so a
    # part-timer losing a 4-hour Saturday is not charged the same as a
    # full-timer losing a 10-hour Monday.
    paid_sick_days: Optional[float] = Field(None, ge=0, le=365)
    # Consecutive hours off between finishing one shift and starting the
    # next. Health and safety, and the daily rest entitlement in the
    # Organisation of Working Time Act, which puts the Irish floor at 11.
    #
    # Configurable because jurisdictions differ and some shops promise more.
    # Nothing here stops a shop setting it lower than 11 — that is a decision
    # the owner makes and can be held to, not one the app can make for them.
    min_rest_hours: Optional[float] = Field(None, ge=0, le=24)
    # Manual row order for the roster grid and exports, as employee_ids.
    # Presentation only: it never changes who gets hours first, so grouping
    # the night staff together cannot quietly promote them. Send an empty
    # list to go back to the job ladder.
    employee_order: Optional[List[str]] = None
    # True  -> a preferred day off is never overridden, even if that leaves
    #          an hour uncovered (the gap is reported as critical instead).
    # False -> preferences yield to keeping the shop attended.
    strict_days_off: Optional[bool] = None
    # Some shops pay through breaks and some do not. Changes every wage
    # figure in the app; does NOT change a full-time contract, which is
    # written in hours on the floor either way.
    breaks_are_paid: Optional[bool] = None


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
class AvailabilityWindow(BaseModel):
    """Hard limits on when someone can work.

    Distinct from preferred_days_off, which is a preference. A student who
    cannot start before 10:00 genuinely cannot open the shop — rostering them
    at 06:00 produces a schedule that will not happen.
    """
    earliest_start: Optional[str] = Field(None, description="e.g. '10:00'")
    latest_finish: Optional[str] = Field(None, description="e.g. '23:00'")
    available_days: Optional[List[DayKey]] = Field(
        None, description="Days they can work at all. None means any day."
    )
    preferred_shift: Optional[Literal["morning", "afternoon", "evening", "any"]] = "any"
    can_work_overnight: bool = True

    _v_earliest = field_validator("earliest_start")(
        lambda v: _validate_hhmm(v) if v else v
    )
    _v_latest = field_validator("latest_finish")(
        lambda v: _validate_hhmm(v) if v else v
    )


class SummerBreak(BaseModel):
    """A student's break period, when their hour cap lifts."""
    start_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    max_weekly_hours: Optional[float] = Field(
        None, gt=0, le=168,
        description="Hours they can work during the break, e.g. 40.",
    )


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1)
    # Optional because a roster spreadsheet does not contain email addresses.
    # The importer used to invent one — "jane@imported.shop_645.local" — which
    # failed this very validator twice over: an underscore is illegal in a
    # domain, and ".local" is a reserved name. Imported staff could be created
    # and then never edited, because saving any change re-validated an address
    # the manager had never typed and could not see.
    #
    # A missing address is also the truth. Dispatch skips these people and
    # says so, rather than reporting a successful send to nowhere.
    email: Optional[EmailStr] = None
    role: str
    age: int = Field(ge=13, le=100)
    hourly_rate: float = Field(ge=0)
    max_weekly_hours: float = Field(40, gt=0, le=168)
    preferred_days_off: List[DayKey] = []
    departments: List[str] = ["Shop Floor"]

    # Inactive staff keep their history (so past rosters stay readable) but
    # are never scheduled. Preferable to deleting a leaver, which would
    # orphan every shift they ever worked.
    is_active: bool = True

    availability: Optional[AvailabilityWindow] = None

    # How this person's hours are governed.
    #   full_time_contract — salaried. Contracted to be ON THE FLOOR for
    #       contract_span_hours (breaks included), and paid the same whether
    #       they hit it or fall short by up to the tolerance.
    #   student           — term-time and summer-break paid-hour caps.
    #   hourly            — paid for what they work, capped by max_weekly_hours.
    employment_type: Literal["full_time_contract", "student", "hourly"] = "hourly"

    # Full-time only. Hours on the floor, not paid hours — a contract is
    # written clock-in to clock-out, and mixing the two is what made a 40h
    # employee read as "1.8h over" for taking their breaks.
    contract_span_hours: Optional[float] = Field(
        None, gt=0, le=168,
        description="Contracted hours on the floor per week. Defaults to 42.5.",
    )
    contract_span_tolerance: Optional[float] = Field(
        None, ge=0, le=24,
        description="How far under the contract a week may land. Defaults to 1.5.",
    )

    # Kept for records written before employment_type existed.
    is_student: bool = False
    term_time_max_hours: Optional[float] = Field(
        None, gt=0, le=168,
        description="Weekly cap during term. Falls back to max_weekly_hours.",
    )
    summer_break: Optional[SummerBreak] = None

    @model_validator(mode="after")
    def _sync_student_flag(self) -> "EmployeeIn":
        """Keep the old flag in step so nothing reading it goes stale."""
        self.is_student = self.employment_type == "student" or self.is_student
        if self.is_student and self.employment_type == "hourly":
            self.employment_type = "student"
        return self

    # Balance carried in from whatever the shop used before. Set once at
    # import; after that the balance is derived from approved rosters.
    opening_holiday_hours: Optional[float] = Field(None, ge=0)


class HolidayAdjustment(BaseModel):
    """A manual correction to someone's holiday balance.

    Recorded rather than applied silently: a balance that changed without
    explanation is impossible to defend if an employee queries it.
    """
    hours: float = Field(description="Positive adds, negative deducts.")
    reason: str = Field(min_length=3)


# ---------------------------------------------------------------------------
# Holidays / leave
# ---------------------------------------------------------------------------
class HolidayIn(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD, inclusive.")
    label: str
    # "employee"    -> paid holiday, draws down entitlement (HOL)
    # "unavailable" -> unpaid, blocks scheduling, no pay (N/A)
    # "sick"        -> paid or not per policy, never used as training signal
    scope: Literal["shop", "employee", "unavailable", "sick"] = "shop"
    employee_id: Optional[str] = None


class SickReport(BaseModel):
    """Somebody has called in for a shift on an approved roster."""
    employee_id: str
    day: DayKey
    cover_employee_id: Optional[str] = Field(
        None, description="Who takes the shift. Omit to leave it uncovered."
    )
    reason: Optional[str] = None
    # Rules the manager knowingly accepted breaking to get cover. Recorded on
    # the shift and in the activity log, because "we had no choice" is a
    # defensible position only if it was written down at the time.
    overrides: List[str] = Field(default_factory=list)


class LeaveRequest(BaseModel):
    """Book leave over a date range, marking which days are paid.

    Two things this has to get right, and both come from how leave actually
    works rather than from how it is easiest to store:

    1. Only days INSIDE the range are affected. Someone off Thursday and
       Friday still works Monday to Wednesday, so the rest of that week must
       be left alone rather than blocked.

    2. Within the range, an employee is paid only for the days they would
       normally have worked. The rest are unpaid and simply unavailable —
       booking a fortnight off is not fourteen days of holiday pay.

    Paid days are given as explicit dates rather than weekday names, because
    over a multi-week booking "Monday" is ambiguous and the paid days
    genuinely differ from week to week.
    """
    employee_id: str
    start_date: str = Field(description="First day of leave, YYYY-MM-DD")
    end_date: str = Field(description="Last day of leave, inclusive, YYYY-MM-DD")
    paid_dates: List[str] = Field(
        default_factory=list,
        description="Dates within the range paid as holiday. The rest are unpaid.",
    )
    label: str = "Holiday"
    hours_per_day: Optional[float] = Field(
        None, gt=0, le=24,
        description="Paid hours per holiday day. Defaults to their usual day.",
    )


class FixedShiftIn(BaseModel):
    employee_id: str
    days: List[DayKey]
    start: str
    end: str

    _v_start = field_validator("start")(_validate_hhmm)
    _v_end = field_validator("end")(_validate_hhmm)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
class AIRuleIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    enabled: bool = True
    category: Literal["legal", "safety", "custom"] = "custom"


# ---------------------------------------------------------------------------
# Rosters
# ---------------------------------------------------------------------------
class RosterGenReq(BaseModel):
    week_start: str = Field(description="Monday of the target week, YYYY-MM-DD")
    department: Optional[str] = None
    # Rebalance rather than start over: hold the shifts the manager placed by
    # hand and re-solve everyone else around them.
    keep_pinned: bool = False
    # Re-solve ONE day and leave the other six exactly as they are. Their
    # hours still count against weekly caps and the five-day limit — this
    # narrows what may be changed, not what is taken into account.
    only_day: Optional[DayKey] = None


class ChangePassword(BaseModel):
    """Changing your own password while logged in.

    The CURRENT password is required even though the caller is already
    authenticated. Being logged in proves a browser session exists; it does
    not prove the person at the keyboard is the account holder. Without this,
    anyone passing an unlocked laptop could lock the owner out permanently.
    """
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class ForceApproval(BaseModel):
    """Approving a week that breaks rules, deliberately.

    The password is the account's own, re-entered. It is not a second factor
    and does not pretend to be — it establishes WHO authorised the override,
    so the record names a person rather than a session that was left open.
    """
    force: bool = False
    password: str = ""
    reason: str = Field("", max_length=300)


class CorrectionDecision(BaseModel):
    """Accepting or refusing one learned suggestion."""
    signature: str = Field(min_length=1, max_length=200)


class ExtraShiftReq(BaseModel):
    """Somebody rostered above the usual level for a known reason."""
    employee_id: str
    day: DayKey
    start: str
    end: str
    reason: str = Field("", max_length=200)

    _v_start = field_validator("start")(_validate_hhmm)
    _v_end = field_validator("end")(_validate_hhmm)


class ShiftIn(BaseModel):
    """One cell of the roster grid.

    Times are optional because a leave entry genuinely has none — somebody on
    holiday is not in the shop from any hour to any other. Requiring them
    meant that once a week contained booked leave, saving ANY edit to ANY
    shift failed validation, because the grid sends the whole week back.
    """
    employee_id: str
    day: DayKey
    start: str = ""
    end: str = ""
    paid_holiday: bool = False
    unpaid_holiday: bool = False
    sick: bool = False
    temp_override: bool = False
    # Set by hand and held through a rebalance. Sent explicitly as False to
    # release one, so the solver may move that person again.
    pinned: Optional[bool] = None
    # Deliberately ON TOP of normal staffing — a delivery, a renovation, an
    # unusually busy Saturday. The exact inverse of pinned: a pin says "THIS
    # person fills that slot", an extra says "this person AS WELL AS the
    # slots", so an extra shift never cancels one and is never reported as
    # overstaffing.
    extra: bool = False

    _v_start = field_validator("start")(lambda v: _validate_hhmm(v) if v else "")
    _v_end = field_validator("end")(lambda v: _validate_hhmm(v) if v else "")

    @property
    def is_leave(self) -> bool:
        return self.paid_holiday or self.unpaid_holiday or self.sick

    @model_validator(mode="after")
    def _work_shifts_need_times(self) -> "ShiftIn":
        """Optional for leave, still mandatory for actual work."""
        if not self.is_leave and not (self.start and self.end):
            raise ValueError("A work shift needs both a start and an end time.")
        return self


class RosterUpdate(BaseModel):
    shifts: List[ShiftIn]


class OCRRequest(BaseModel):
    image_url: str


class OCRBatchRequest(BaseModel):
    image_urls: List[str]


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    lookup_key: str
    quantity: int = Field(1, ge=1, le=100)
    origin_url: str


class ContactEntry(BaseModel):
    employee_id: str
    email: str


class ContactApply(BaseModel):
    """The rows the manager confirmed in the preview.

    Resolved pairs rather than the file: re-parsing on apply would let what
    gets written differ from what was approved on screen, and the whole point
    of the two-step flow is that a human saw every match.
    """
    entries: List[ContactEntry] = Field(default_factory=list)
