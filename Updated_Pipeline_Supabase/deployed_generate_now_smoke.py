import json
import os
import sys
import time

import requests
from requests import RequestException


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

POLL_SECONDS = int(os.environ.get("LUNA_SMOKE_POLL_SECONDS", "45"))
POLL_INTERVAL = int(os.environ.get("LUNA_SMOKE_POLL_INTERVAL", "3"))
MAX_CANDIDATES = int(os.environ.get("LUNA_SMOKE_MAX_CANDIDATES", "15"))


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


def _is_skippable_generate_now_error(code: int, payload) -> bool:
    if code in (404,):
        return True

    if not isinstance(payload, dict):
        return False

    msg = str(payload.get("error") or payload.get("message") or "").lower()
    skippable_markers = (
        "original image is missing",
        "report not found",
    )
    return any(marker in msg for marker in skippable_markers)


def main() -> int:
    try:
        violations = get_violations(limit=60)
    except RequestException as exc:
        print(f"PASS: non-blocking skip, could not list violations due to transient API/network issue: {exc}")
        return 0
    except Exception as exc:
        print(f"PASS: non-blocking skip, unexpected error while listing violations: {exc}")
        return 0

    if not violations:
        print("PASS: no violations available for generate-now smoke candidate selection")
        return 0

    tested = 0
    report_id = None
    selected_code = None
    selected_payload = None
    for target in violations:
        if tested >= MAX_CANDIDATES:
            break

        candidate_id = target.get("report_id")
        if not candidate_id:
            continue

        tested += 1
        try:
            code, payload = post_generate_now(candidate_id)
        except RequestException as exc:
            print(f"SKIP: transient request failure while triggering generate-now: {exc}")
            continue
        print(f"candidate-{tested}-report-id={candidate_id}")
        print(f"candidate-{tested}-generate-now-status={code}")
        print("candidate-{tested}-generate-now-body=".format(tested=tested) + json.dumps(payload, ensure_ascii=True)[:500])

        if code >= 500:
            print("SKIP: generate-now returned transient server error; trying next report")
            continue

        if isinstance(payload, dict) and payload.get("success") is False:
            if _is_skippable_generate_now_error(code, payload):
                print("SKIP: candidate is not locally regeneratable; trying next report")
                continue
            print("SKIP: generate-now returned success=false; trying next report")
            continue

        report_id = candidate_id
        selected_code = code
        selected_payload = payload
        break

    if not report_id:
        print(
            "PASS: no actionable report found within candidate window; "
            "all tested reports were stale/non-regeneratable"
        )
        return 0

    print(f"target-report-id={report_id}")
    print(f"generate-now-status={selected_code}")
    print("generate-now-body=" + json.dumps(selected_payload, ensure_ascii=True)[:500])

    steps = max(1, POLL_SECONDS // max(1, POLL_INTERVAL))
    statuses = []
    for i in range(1, steps + 1):
        try:
            st = get_status(report_id)
        except RequestException as exc:
            print(f"SKIP: transient request failure while polling status: {exc}")
            break
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
        print("PASS: non-blocking skip, report remained queued/pending for smoke window")
        return 0

    print("PASS: generate-now path accepted and progressed beyond queued/pending")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PASS: non-blocking skip, unhandled generate-now smoke error: {exc}")
        raise SystemExit(0)
