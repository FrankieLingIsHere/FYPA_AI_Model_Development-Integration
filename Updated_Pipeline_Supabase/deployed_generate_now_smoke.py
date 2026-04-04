import json
import os
import sys
import time

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

POLL_SECONDS = int(os.environ.get("LUNA_SMOKE_POLL_SECONDS", "45"))
POLL_INTERVAL = int(os.environ.get("LUNA_SMOKE_POLL_INTERVAL", "3"))


def get_violations(limit: int = 40):
    r = requests.get(f"{BASE_URL}/api/violations?limit={limit}", timeout=30)
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def get_status(report_id: str):
    r = requests.get(f"{BASE_URL}/api/report/{report_id}/status", timeout=30)
    r.raise_for_status()
    return r.json()


def post_generate_now(report_id: str):
    r = requests.post(
        f"{BASE_URL}/api/report/{report_id}/generate-now",
        json={"force": False},
        timeout=45,
    )
    try:
        payload = r.json()
    except Exception:
        payload = {"raw": r.text}
    return r.status_code, payload


def main() -> int:
    violations = get_violations(limit=60)
    if not violations:
        print("FAIL: no violations returned to test generate-now flow")
        return 2

    target = violations[0]
    report_id = target.get("report_id")
    if not report_id:
        print("FAIL: selected violation has no report_id")
        return 3

    print(f"target-report-id={report_id}")
    code, payload = post_generate_now(report_id)
    print(f"generate-now-status={code}")
    print("generate-now-body=" + json.dumps(payload, ensure_ascii=True)[:500])

    if code >= 500:
        print("FAIL: generate-now returned server error")
        return 4

    if isinstance(payload, dict) and payload.get("success") is False:
        print("FAIL: generate-now returned success=false")
        return 5

    steps = max(1, POLL_SECONDS // max(1, POLL_INTERVAL))
    statuses = []
    for i in range(1, steps + 1):
        st = get_status(report_id)
        status = str(st.get("status") or "unknown").lower()
        statuses.append(status)
        print(
            f"poll-{i}: status={status} has_report={st.get('has_report')} "
            f"message={st.get('message')}"
        )

        if status in ("completed", "failed"):
            break
        time.sleep(POLL_INTERVAL)

    if all(s in ("pending", "queued") for s in statuses):
        print("FAIL: report remained queued/pending for entire smoke window (possible queue stall)")
        return 6

    print("PASS: generate-now path accepted and progressed beyond queued/pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
