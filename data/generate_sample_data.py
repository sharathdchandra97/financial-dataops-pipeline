"""
Generate sample financial transaction data for the DataOps pipeline demo.
"""
import csv
import json
import random
import uuid
from datetime import datetime, timedelta

MERCHANTS = [
    "Amazon", "Tesco", "Sainsbury's", "Revolut P2P", "HMRC",
    "Netflix", "Spotify", "Uber", "TfL", "British Gas",
    "Sky Broadband", "Deliveroo", "Costa Coffee", "Apple", "Shell"
]
CATEGORIES = [
    "retail", "groceries", "transfer", "tax", "streaming",
    "transport", "utilities", "food_delivery", "fuel", "subscription"
]
MERCHANT_CATEGORY = dict(zip(MERCHANTS, CATEGORIES + CATEGORIES[:5]))

CURRENCIES = ["GBP", "USD", "EUR"]
STATUSES = ["completed", "completed", "completed", "pending", "failed"]  # weighted


def random_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def generate_transactions(n: int = 500) -> list[dict]:
    start = datetime(2024, 1, 1)
    end = datetime(2024, 12, 31)
    records = []
    for _ in range(n):
        merchant = random.choice(MERCHANTS)
        currency = random.choices(CURRENCIES, weights=[70, 20, 10])[0]
        amount = round(random.uniform(1.5, 2500.0), 2)
        # inject some data quality issues
        if random.random() < 0.03:
            amount = -amount          # negative amount anomaly
        if random.random() < 0.02:
            merchant = ""             # missing merchant
        ts = random_date(start, end)
        records.append({
            "transaction_id": str(uuid.uuid4()),
            "account_id": f"ACC{random.randint(1000, 9999)}",
            "timestamp": ts.isoformat(),
            "merchant": merchant,
            "category": MERCHANT_CATEGORY.get(merchant, "other"),
            "amount": amount,
            "currency": currency,
            "status": random.choice(STATUSES),
            "country_code": random.choice(["GB", "US", "DE", "FR", "NG"]),
            "is_international": currency != "GBP",
        })
    return records


def main():
    records = generate_transactions(500)
    # Write CSV
    csv_path = "transactions.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"[✓] Written {len(records)} records to {csv_path}")

    # Write JSON (first 50 records as a "streaming" sample)
    json_path = "transactions_sample.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records[:50], f, indent=2)
    print(f"[✓] Written 50 records to {json_path}")


if __name__ == "__main__":
    main()
