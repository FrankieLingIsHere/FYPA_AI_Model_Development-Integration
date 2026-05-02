"""
Write a JSON diagnostics summary for the deployed system conditions job.

Samples key backend endpoints and records the active threshold configuration,
then writes the results to ``system-conditions-summary.json`` (or the path
specified via ``CASM_DIAG_SUMMARY_PATH``).  Invoked as an ``if: always()``
step so the artifact is available regardless of test outcome.
"""

import datetime
import json
import os

import requests


BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

SUMMARY_PATH = os.environ.get("CASM_DIAG_SUMMARY_PATH", "system-conditions-summary.json")

SAMPLED_PATHS = [
    "/api/system/startup-status",
    "/api/queue/status",
    "/api/stats",
]

THRESHOLD_KEYS = (
    "CASM_CONDITIONS_STRICT",
    "CASM_CONDITIONS_POLL_SECONDS",
    "CASM_CONDITIONS_POLL_INTERVAL",
    "CASM_FLOOD_TOTAL_REQUESTS",
    "CASM_FLOOD_WORKERS",
    "CASM_FLOOD_P95_MS",
    "CASM_FLOOD_MIN_SUCCESS_RATIO",
    "CASM_FLOOD_MAX_UNIQUE_REPORTS",
)


def main() -> int:
    results = {}
    for path in SAMPLED_PATHS:
        url = f"{BASE_URL}{path}"
        try:
            r = requests.get(url, timeout=20)
            try:
                body = r.json()
            except Exception:
                body = r.text[:300]
            results[path] = {"status": r.status_code, "body": body}
        except Exception as exc:
            results[path] = {"error": str(exc)}

    thresholds = {key: os.environ.get(key, "") for key in THRESHOLD_KEYS}

    summary = {
        "test_name": "deployed_system_conditions_diagnostics",
        "target_url": BASE_URL,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "endpoint_samples": results,
        "thresholds": thresholds,
    }

    try:
        with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=True, indent=2)
        print(f"INFO: diagnostics summary written to {SUMMARY_PATH}")
    except Exception as exc:
        print(f"WARN: could not write diagnostics summary: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
