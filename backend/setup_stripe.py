"""Create the Stripe product catalogue.

Run once against a Stripe account (test or live):

    python setup_stripe.py

Idempotent — it looks for existing products and prices before creating
anything, so re-running is safe. Prices in Stripe are immutable, so changing
an amount here deactivates the old price and creates a new one.
"""
import os
import sys
from pathlib import Path

import stripe
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

api_key = os.environ.get("STRIPE_SECRET_KEY")
if not api_key:
    sys.exit("STRIPE_SECRET_KEY is not set in backend/.env — nothing to do.")
stripe.api_key = api_key

# `lookup_key` is what the app asks for at checkout, so these strings are a
# contract with the frontend's pricing page. Amounts are in the currency's
# smallest unit (cents).
CATALOG = [
    {
        "product_key": "roster_pro",
        "name": "Roster · Pro",
        "tax_code": "txcd_10103001",  # SaaS — business use
        "prices": [
            {"lookup_key": "roster_pro_monthly", "amount": 1900, "currency": "usd", "interval": "month"},
            {"lookup_key": "roster_pro_yearly", "amount": 19000, "currency": "usd", "interval": "year"},
        ],
    },
]


def get_or_create_product(entry):
    for product in stripe.Product.list(active=True).auto_paging_iter():
        if product.metadata.get("product_key") == entry["product_key"]:
            print(f"Product '{entry['name']}' already exists ({product.id})")
            return product

    product = stripe.Product.create(
        name=entry["name"],
        tax_code=entry.get("tax_code"),
        metadata={"product_key": entry["product_key"]},
    )
    print(f"Created product '{entry['name']}' ({product.id})")
    return product


def ensure_prices(product, prices):
    for spec in prices:
        existing = stripe.Price.list(
            lookup_keys=[spec["lookup_key"]], active=True, limit=1
        ).data

        if existing:
            current = existing[0]
            unchanged = (
                current.unit_amount == spec["amount"]
                and current.currency == spec["currency"]
            )
            if unchanged:
                print(f"  Price '{spec['lookup_key']}' is already correct")
                continue
            # Stripe prices are immutable: retire the old one and make a new
            # one carrying the same lookup key.
            stripe.Price.modify(current.id, active=False)
            print(f"  Deactivated outdated price '{spec['lookup_key']}'")

        kwargs = {
            "product": product.id,
            "unit_amount": spec["amount"],
            "currency": spec["currency"],
            "lookup_key": spec["lookup_key"],
            "transfer_lookup_key": True,
        }
        if spec.get("interval"):
            kwargs["recurring"] = {"interval": spec["interval"]}

        stripe.Price.create(**kwargs)
        amount = spec["amount"] / 100
        period = f"/{spec['interval']}" if spec.get("interval") else ""
        print(f"  Created price '{spec['lookup_key']}': {amount:.2f} {spec['currency'].upper()}{period}")


if __name__ == "__main__":
    mode = "TEST" if api_key.startswith("sk_test_") else "LIVE"
    print(f"Configuring Stripe catalogue in {mode} mode\n")

    for entry in CATALOG:
        product = get_or_create_product(entry)
        ensure_prices(product, entry["prices"])

    print("\nCatalogue ready.")
