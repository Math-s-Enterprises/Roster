"""Convert stored employee ages to age groups. Dry run unless --commit is passed."""
import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402
from app.services.age_groups import age_group  # noqa: E402


async def migrate(employees, *, commit: bool = False) -> Counter:
    counts = Counter()
    async for employee in employees.find({"age": {"$exists": True}}):
        group = age_group(employee)
        if commit:
            # A concurrent employee edit can confirm their group while the scan runs.
            # The update also clears age on edit, so this filter will then skip the row.
            result = await employees.update_one(
                {"_id": employee["_id"], "shop_id": employee["shop_id"],
                 "age": {"$exists": True, "$eq": employee["age"]}},
                {"$set": {"age_group": group}, "$unset": {"age": ""}},
            )
            if not result.modified_count:
                continue
        counts[group or "unconfirmed"] += 1
    return counts


async def run(commit: bool) -> None:
    try:
        counts = await migrate(db.employees, commit=commit)
        action = "Converted" if commit else "Would convert"
        print(f"{action} {sum(counts.values())} employee records in {config.DB_NAME}.")
        for group, count in sorted(counts.items()):
            print(f"  {group}: {count}")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Apply the conversion.")
    asyncio.run(run(parser.parse_args().commit))
