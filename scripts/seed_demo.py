"""Seeds the demo customers and their payment history (all synthetic).

Run from the repo root:
    uv run --project backend python scripts/seed_demo.py            # add or refresh seed data
    uv run --project backend python scripts/seed_demo.py --wipe     # delete everything first
    uv run --project backend python scripts/seed_demo.py --dry-run  # in memory, writes nothing

Writes to Firestore (project from .env). Seed documents have fixed IDs, so
running it twice does not create duplicates. Restart the backend afterwards:
it loads Firestore data at startup.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wipe", action="store_true", help="delete all ScamShield data in the store first")
    parser.add_argument("--dry-run", action="store_true", help="use an in-memory store; nothing is written")
    args = parser.parse_args()

    if args.dry_run:
        os.environ["STORE_BACKEND"] = "memory"

    # Imported after the environment is set, because config is read on import.
    from app import config
    from app.schemas import current_step
    from db.seed_data import seed_store
    from db.store import get_store

    print(f"Store: {config.STORE_BACKEND}" + (f" (project {config.GOOGLE_CLOUD_PROJECT})" if config.STORE_BACKEND == "firestore" else ""))
    store = get_store()
    if args.wipe:
        print("Deleting existing data...")
        store.wipe()

    summary = seed_store(store, now_step=current_step())
    print(f"Seeded {summary['customers']} customers and {summary['transactions']} transactions.")
    print(f"Tiers of seeded history: {summary['tiers']}")
    if not args.dry_run:
        print("Restart the backend so it loads the new data.")


if __name__ == "__main__":
    main()
