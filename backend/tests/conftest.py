import os

# Tests never touch Firestore. Set before the app modules read their config.
os.environ["STORE_BACKEND"] = "memory"
# Tests never call Gemini either (the live test in test_agent_live.py opts in).
os.environ["AUTO_INVESTIGATE"] = "false"
