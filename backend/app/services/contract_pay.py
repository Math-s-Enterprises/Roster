"""Pay for a full-time contract, entered as a weekly or a monthly salary.

A salaried contract is paid a fixed amount, not by the hour, so the Employees
screen takes it the way a contract states it: one figure, per week or per month.

HOW IT REACHES THE COSTS

Everything that costs a roster - the labour cost on the roster itself, the
dashboard totals, the Hours and Wages report - multiplies hours by the
employee's `hourly_rate`. Rather than teach each of those places a second way
of costing somebody, and risk two screens giving two answers for the same week,
the salary is turned into the hourly rate they already use:

    weekly pay   = the weekly salary, or the monthly salary x 12 / 52
    hourly rate  = weekly pay / contracted weekly hours

A month is not four weeks: a year is 52 weeks and 12 months, so a month is
52/12 = 4.33 weeks. Using four would overstate the weekly cost of everyone on
a monthly salary by about 8%.

"Contracted weekly hours" is the employee's `max_weekly_hours`, which the form
labels as PAID hours (unpaid breaks sit on top). That is the right divisor: a
week of exactly the contracted paid hours then costs exactly the salary.

THE ONE THING THIS IS NOT

A salary does not shrink in a short week, but an hourly rate does. A salaried
person who works fewer paid hours than contracted therefore shows a
proportionally lower cost than they are really paid. This is how the app has
always costed salaried staff (hours x a rate), so nothing gets worse, but it is
an approximation, and the exact version - a fixed weekly cost whatever the
hours - would change nine places that compute cost and needs decisions about
leave, part weeks and staff shared between roster groups.
"""

WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12
PERIODS = ("weekly", "monthly")

# Four decimals keeps a full contracted week within a fraction of a cent of the
# salary once it is multiplied back up, without storing a long float.
_RATE_DECIMALS = 4


def weekly_equivalent(period: str, salary: float) -> float:
    """What the salary comes to in one week."""
    if period == "weekly":
        return float(salary)
    if period == "monthly":
        return float(salary) * MONTHS_PER_YEAR / WEEKS_PER_YEAR
    raise ValueError(f"contract pay period must be one of {PERIODS}, not {period!r}")


def hourly_equivalent(period: str, salary: float, paid_hours_per_week: float) -> float:
    """The hourly rate that makes a full contracted week cost exactly the salary."""
    if not paid_hours_per_week or paid_hours_per_week <= 0:
        raise ValueError("contracted weekly hours must be more than zero")
    return round(weekly_equivalent(period, salary) / paid_hours_per_week, _RATE_DECIMALS)
