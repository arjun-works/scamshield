"""The evaluation script's arithmetic and report, checked without calling Gemini."""

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("eval_scam", REPO_ROOT / "scripts" / "eval_scam.py")
eval_scam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_scam)


def outcome(label: str, paused: bool) -> dict:
    return {
        "label": label, "scam_type": "digital_arrest" if label == "scam" else None, "language": "English",
        "paused": paused, "payment_status": "safety_paused" if paused else "held", "turns_sent": 2,
        "signals": [{"type": "fake_official", "confidence": 0.9, "source": "gemini"}] if paused else [],
        "models": ["fake-model"], "error": None,
    }


def test_confusion_matrix_and_metrics():
    conversations = {
        "s1": outcome("scam", True), "s2": outcome("scam", True), "s3": outcome("scam", False),
        "g1": outcome("genuine", False), "g2": outcome("genuine", True),
    }
    c = eval_scam.confusion(conversations)
    assert (c["tp"], c["fn"], c["fp"], c["tn"]) == (2, 1, 1, 1)
    assert c["accuracy"] == 3 / 5
    assert c["precision"] == 2 / 3 and c["recall"] == 2 / 3


def test_wilson_interval_is_wide_for_small_samples():
    low, high = eval_scam.wilson_interval(20, 20)
    assert 0.83 < low < 0.84 and high == 1.0
    assert eval_scam.wilson_interval(0, 0) == (0.0, 1.0)


def test_reports_render_and_state_the_misses():
    results = {
        "conversations": {"scam-01": outcome("scam", False), "genuine-01": outcome("genuine", False)},
        "messages": {
            "fake_kyc": {**outcome("scam", True), "type": "fake_kyc", "input": "screenshot", "expected_signals": ["fake_official", "suspicious_link"]},
            "prompt_injection": {
                **outcome("scam", True), "type": "prompt_injection", "input": "pasted text", "expected_signals": ["embedded_instructions"],
                "signals": [{"type": "embedded_instructions", "confidence": 0.95, "source": "gemini"}],
            },
        },
    }
    report = eval_scam.render_scam_eval(results)
    assert "Incomplete run" in report                      # no completed_on date
    assert "| scam-01 | English | digital_arrest | scam | not paused | **NO** |" in report
    assert "1 of 2" in report                              # expected signals found for fake_kyc
    assert "Flagged by Gemini as `embedded_instructions`: **yes**" in report

    model_metrics = json.loads((REPO_ROOT / "backend" / "ml" / "artifacts" / "metrics.json").read_text())
    combined = eval_scam.render_combined(results, model_metrics)
    assert "PR-AUC" in combined and "safety_paused" in combined
