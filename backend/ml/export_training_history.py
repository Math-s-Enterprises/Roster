"""Read-only, one-shop JSONL evidence export. No database writes.

Run from backend: python ml/export_training_history.py --shop-id ID --output FILE
The output must not already exist. It contains observations, approval outcomes
and only explicitly safe pairwise swap labels. Contains employee identifiers;
keep local.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.tenancy import ShopScope
from app.services.training_evidence import historical_examples


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        scope = ShopScope({"shop_id": args.shop_id}, {})
        rosters = [r async for r in scope.rosters.stream({"approved": True})]
        if not rosters:
            parser.error("No approved rosters for this shop; nothing exported.")
        employee_ids = {e["employee_id"] async for e in scope.employees.stream()}
        counts = {}
        with args.output.open("x", encoding="utf-8") as target:
            for row in historical_examples(rosters, employee_ids):
                target.write(json.dumps(row, sort_keys=True) + "\n")
                counts[row["kind"]] = counts.get(row["kind"], 0) + 1
        print(json.dumps(counts, sort_keys=True))
    finally:
        db.client.close()


if __name__ == "__main__":
    asyncio.run(main())
