"""Generates the synthetic demo customers and their payment history.

Everything here is invented: names, cities, payees and amounts. No real
personal data is used. Output is deterministic for a given seed.
"""

import random
from datetime import datetime, timezone

from app.schemas import IST_OFFSET_SECONDS

# Preferred language -> (synthetic names, cities)
PEOPLE = {
    "English": (
        ["Ananya Rao", "Rohan Mehta", "Priya Nair", "Arjun Shetty", "Sneha Kulkarni", "Vikram Desai",
         "Meera Iyer", "Karan Malhotra", "Divya Menon", "Nikhil Reddy", "Aisha Khan", "Joseph Thomas"],
        ["Bengaluru", "Mumbai", "Hyderabad", "Pune", "Kochi"],
    ),
    "Tamil": (
        ["Lakshmi Narayanan", "Murugan Selvam", "Kavitha Rajendran", "Senthil Kumar", "Revathi Subramanian",
         "Karthik Palani", "Meenakshi Sundaram", "Ganesan Pillai", "Saranya Venkatesh", "Ravi Chandran"],
        ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli"],
    ),
    "Hindi": (
        ["Sunita Sharma", "Rajesh Verma", "Pooja Gupta", "Amit Tiwari", "Kamla Devi Yadav",
         "Manoj Mishra", "Neha Agarwal", "Suresh Chauhan"],
        ["Delhi", "Lucknow", "Jaipur", "Bhopal"],
    ),
}

# Customer segment -> typical payment range (min, max)
SEGMENTS = {
    "student": (100, 3_000),
    "salaried": (500, 25_000),
    "senior_citizen": (300, 15_000),
    "small_business": (2_000, 80_000),
}
SEGMENT_ORDER = ["salaried", "senior_citizen", "salaried", "small_business", "student"]

# Shared merchants: (payee_id, name, category)
MERCHANTS = [
    ("M-ELECTRICITY", "City Electricity Board", "utilities"),
    ("M-GROCERY", "FreshMart Groceries", "groceries"),
    ("M-MOBILE", "QuickRecharge Mobile", "mobile recharge"),
    ("M-WATER", "Metro Water Board", "utilities"),
    ("M-INSURANCE", "SafeLife Insurance", "insurance"),
    ("M-PHARMACY", "CarePlus Pharmacy", "pharmacy"),
]
PERSONAL_PAYEES = [("landlord", "Rent"), ("family", "Family support")]
FAMILY_NAMES = ["Anand", "Geetha", "Imran", "Latha", "Mohan", "Nisha", "Prakash", "Sarita", "Uma", "Vijay"]

HISTORY_PER_CUSTOMER = 12
HISTORY_DAYS = 30


def generate_customers(seed: int = 42) -> list[dict]:
    """About 30 synthetic customers: 12 English, 10 Tamil, 8 Hindi speakers."""
    rng = random.Random(seed)
    customers = []
    for language, (names, cities) in PEOPLE.items():
        for name in names:
            number = len(customers) + 1
            segment = SEGMENT_ORDER[number % len(SEGMENT_ORDER)]
            low, high = SEGMENTS[segment]

            usual_payees = [
                {"payee_id": pid, "name": pname, "category": category, "type": "PAYMENT"}
                for pid, pname, category in rng.sample(MERCHANTS, 3)
            ]
            for index, (category, label) in enumerate(PERSONAL_PAYEES, start=1):
                usual_payees.append({
                    "payee_id": f"P-{number:03d}-{index}",
                    "name": f"{label} ({rng.choice(FAMILY_NAMES)})",
                    "category": category,
                    "type": "TRANSFER",
                })

            customers.append({
                "customer_id": f"CUST-{number:03d}",
                "name": name,
                "preferred_language": language,
                "city": rng.choice(cities),
                "segment": segment,
                "member_since": rng.randint(2012, 2024),
                # Balance is comfortably above typical payments.
                "balance": float(round(high * rng.uniform(15, 40), -2)),
                "typical_amount_min": low,
                "typical_amount_max": high,
                "usual_payees": usual_payees,
                "synthetic": True,
            })
    return customers


def step_to_iso(step: int, minute: int = 0) -> str:
    """Timestamp for an hour counter produced by schemas.current_step()."""
    seconds = step * 3600 - IST_OFFSET_SECONDS + minute * 60
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def generate_history(customers: list[dict], now_step: int, seed: int = 42) -> list[dict]:
    """Ordinary past payments to each customer's usual payees, oldest first.

    Each item is {"transaction": <TransactionIn fields>, "created_at": iso}.
    """
    rng = random.Random(seed + 1)
    history = []
    for customer in customers:
        for index in range(HISTORY_PER_CUSTOMER):
            payee = rng.choice(customer["usual_payees"])
            step = now_step - rng.randint(2, HISTORY_DAYS * 24)
            amount = round(rng.uniform(customer["typical_amount_min"], customer["typical_amount_max"]), -1)
            history.append({
                "transaction": {
                    "transaction_id": f"SEED-{customer['customer_id']}-{index:02d}",
                    "step": step,
                    "type": payee["type"],
                    "amount": float(max(amount, 10)),
                    "sender_id": customer["customer_id"],
                    "sender_balance_before": customer["balance"],
                    "payee_id": payee["payee_id"],
                    "payee_balance_before": float(rng.randint(5, 400) * 1000),
                    "description": payee["name"],
                },
                "created_at": step_to_iso(step, minute=rng.randint(0, 59)),
            })
    history.sort(key=lambda item: item["transaction"]["step"])
    return history


def seed_store(store, now_step: int, seed: int = 42) -> dict:
    """Writes customers and history to a store. Returns a short summary."""
    from app.schemas import TransactionIn
    from app.service import process_transaction

    customers = generate_customers(seed)
    for customer in customers:
        store.upsert_customer(customer)

    tiers: dict[str, int] = {}
    for item in generate_history(customers, now_step, seed):
        record = process_transaction(TransactionIn(**item["transaction"]), store, created_at=item["created_at"])
        tiers[record["tier"]] = tiers.get(record["tier"], 0) + 1
    return {"customers": len(customers), "transactions": sum(tiers.values()), "tiers": tiers}
