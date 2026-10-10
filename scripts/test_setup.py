"""Checks that the local environment is ready: .env values, Gemini key, Firestore.

Run from the repo root:
    uv run --project backend python scripts/test_setup.py

Uses one tiny Gemini request and one Firestore write/read/delete.
No personal data is sent anywhere.
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")


def check_env() -> bool:
    ok = True
    for name in ("GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT"):
        if os.getenv(name):
            print(f"[ok]   {name} is set")
        else:
            print(f"[FAIL] {name} is missing from .env")
            ok = False
    return ok


def check_gemini() -> bool:
    from google import genai
    from google.genai import errors, types

    # 30 s timeout (milliseconds) so a stuck request fails instead of hanging.
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=30_000),
    )

    # Free tier is rate limited and sometimes overloaded: retry on 429 (rate
    # limit) and 503 (model busy) with exponential backoff.
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=MODEL, contents="Reply with the single word: OK"
            )
            print(f"[ok]   Gemini ({MODEL}) replied: {(response.text or '').strip()!r}")
            return True
        except errors.APIError as exc:
            if exc.code in (429, 503) and attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"[..]   Gemini busy ({exc.code}), retrying in {wait}s")
                time.sleep(wait)
                continue
            print(f"[FAIL] Gemini error {exc.code}: {exc.message}")
            return False
        except Exception as exc:  # timeout, no network...
            print(f"[FAIL] Gemini: {type(exc).__name__}: {exc}")
            return False
    return False


def check_firestore() -> bool:
    from google.cloud import firestore

    try:
        db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
        doc = db.collection("_setup_check").document("ping")
        doc.set({"ok": True, "at": firestore.SERVER_TIMESTAMP})
        found = doc.get().exists
        doc.delete()
    except Exception as exc:  # auth, missing database, permissions...
        print(f"[FAIL] Firestore: {type(exc).__name__}: {exc}")
        print("       Hint: run 'gcloud auth application-default login' and make sure")
        print("       a Firestore database (Native mode) exists in this project.")
        return False

    if found:
        print(f"[ok]   Firestore write/read/delete in project {db.project}")
    else:
        print("[FAIL] Firestore write succeeded but the document was not readable")
    return found


def main() -> int:
    if not check_env():
        return 1
    # Run both checks even if the first fails, so all problems show at once.
    results = [check_gemini(), check_firestore()]
    print("\nSetup looks good." if all(results) else "\nSetup has problems, see above.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
