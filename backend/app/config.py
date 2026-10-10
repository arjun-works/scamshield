"""Central settings, read from environment variables.

Locally the values come from the .env file in the repo root.
On Cloud Run they come from env vars / Secret Manager, so no .env is needed.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py -> repo root is two levels up from this folder
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

# strip(): a key stored in Secret Manager from a shell pipe can end in a newline.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# "-latest" aliases always point at the current model (do not pin 2.5 models).
# The lite model is the primary: on the free tier gemini-flash-latest allows
# only 20 requests a day.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

# Tried only if the main model fails after retries (the free tier is often
# overloaded). Set GEMINI_FALLBACK_MODEL to an empty value to turn it off.
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
GEMINI_MODELS = [GEMINI_MODEL] + ([GEMINI_FALLBACK_MODEL] if GEMINI_FALLBACK_MODEL else [])

# Investigate held payments automatically. Turn off to save Gemini quota; an
# analyst can still start an investigation from the case.
AUTO_INVESTIGATE = os.getenv("AUTO_INVESTIGATE", "true").lower() == "true"

# Where data is stored: "firestore" or "memory". Defaults to Firestore when a
# Google Cloud project is configured.
STORE_BACKEND = os.getenv("STORE_BACKEND", "firestore" if GOOGLE_CLOUD_PROJECT else "memory")

# With the memory store, load the synthetic demo customers at startup. Handy
# for trying the apps locally without touching Firestore.
SEED_ON_START = os.getenv("SEED_ON_START", "false").lower() == "true"

# Shared secret for POST /admin/reset (wipe and reseed the demo data). The
# endpoint is switched off when this is empty.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

# Comma-separated list of frontend origins allowed to call the API.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
