"""Employee age groups and conversion of records written before them."""
from typing import Literal

AgeGroup = Literal["under_16", "16_17", "18_plus"]


def age_group(employee: dict) -> AgeGroup | None:
    if "age_group" in employee:
        group = employee["age_group"]
        return group if group in ("under_16", "16_17", "18_plus") else None
    age = employee.get("age")
    if type(age) is not int or not 13 <= age <= 100:
        return None
    if age == 25 and employee.get("imported") and not employee.get("details_confirmed"):
        return None
    if age < 16:
        return "under_16"
    return "16_17" if age < 18 else "18_plus"


def curfew_reason(employee: dict) -> str:
    if age_group(employee) is None:
        return "age group unconfirmed; confirm it in Employees"
    return "under-16 curfew"
