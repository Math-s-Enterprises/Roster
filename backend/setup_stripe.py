"""Idempotent Stripe catalog setup for Roster AI."""
import os, stripe
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

CATALOG = [
    {
        "emergent_product_id": "roster_pro",
        "name": "Roster AI · Pro",
        "tax_code": "txcd_10103001",  # SaaS
        "prices": [
            {"lookup_key": "roster_pro_monthly", "amount": 1900, "currency": "usd", "interval": "month"},
            {"lookup_key": "roster_pro_yearly",  "amount": 19000, "currency": "usd", "interval": "year"},
        ],
    },
]


def get_or_create_product(entry):
    for p in stripe.Product.list(active=True).auto_paging_iter():
        if p.to_dict().get("metadata", {}).get("emergent_product_id") == entry["emergent_product_id"]:
            return p
    return stripe.Product.create(
        name=entry["name"],
        tax_code=entry.get("tax_code"),
        metadata={"managed_by": "emergent", "emergent_product_id": entry["emergent_product_id"]},
    )


def ensure_prices(product, prices):
    for p in prices:
        existing = stripe.Price.list(lookup_keys=[p["lookup_key"]], active=True, limit=1).data
        if existing and (existing[0].unit_amount != p["amount"] or existing[0].currency != p["currency"]):
            stripe.Price.modify(existing[0].id, active=False)
            existing = []
        if not existing:
            kwargs = dict(product=product.id, unit_amount=p["amount"], currency=p["currency"],
                          lookup_key=p["lookup_key"], transfer_lookup_key=True)
            if p.get("interval"):
                kwargs["recurring"] = {"interval": p["interval"]}
            stripe.Price.create(**kwargs)
            print(f"Created price {p['lookup_key']} ({p['amount']} {p['currency']})")
        else:
            print(f"Price {p['lookup_key']} already exists")


if __name__ == "__main__":
    for entry in CATALOG:
        prod = get_or_create_product(entry)
        ensure_prices(prod, entry["prices"])
    print("Catalog ready.")
