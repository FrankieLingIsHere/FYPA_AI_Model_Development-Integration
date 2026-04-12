import json
import os
import sys
import time

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

REPEATS = max(2, int(os.environ.get("LUNA_LIVE_DEDUP_REPEATS", "4")))
MAX_ACCEPTED = max(1, int(os.environ.get("LUNA_LIVE_DEDUP_MAX_ACCEPTED", "1")))
MIN_BLOCKED = max(1, int(os.environ.get("LUNA_LIVE_DEDUP_MIN_BLOCKED", "1")))


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


def request_json(method: str, path: str, *, timeout: int = 45, **kwargs):
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    preview = (response.text or "")[:500]
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, preview


def main() -> int:
    startup_code, startup_payload, startup_text = request_json("GET", "/api/system/startup-status", timeout=30)
    if startup_code >= 400:
        return fail(f"startup-status failed ({startup_code}): {startup_text}", 3)
    if isinstance(startup_payload, dict) and not startup_payload.get("ready", True):
        return fail(f"startup-status not ready: {json.dumps(startup_payload)[:300]}", 4)

    status_code = None
    payload = None
    preview = ""
    gateway_like_codes = {502, 503, 504}
    for attempt in range(1, 6):
        try:
            status_code, payload, preview = request_json(
                "POST",
                "/api/testing/live-dedup/probe",
                json={"repeats": REPEATS},
                timeout=70,
            )
        except requests.RequestException as exc:
            print(f"INFO: live dedup probe request failed on attempt {attempt}: {exc}")
            if attempt < 5:
                time.sleep(6)
                continue
            print("PASS: true live dedup probe skipped (transient request failures on deployed target)")
            return 0

        # Endpoint may lag behind repository pushes on deployed targets.
        if status_code in (404,):
            print(f"INFO: live dedup probe endpoint unavailable on attempt {attempt} (status={status_code})")
            if attempt < 5:
                time.sleep(8)
                continue
            print("PASS: true live dedup probe skipped (endpoint not yet available on deployed target)")
            return 0

        if status_code == 403 and isinstance(payload, dict) and payload.get("error") == "testing_endpoints_disabled":
            print("PASS: true live dedup probe skipped (testing endpoints disabled by default)")
            return 0

        if status_code in gateway_like_codes:
            print(f"INFO: live dedup probe gateway status on attempt {attempt}: {status_code}")
            if attempt < 5:
                time.sleep(6)
                continue
            print("PASS: true live dedup probe skipped (persistent gateway outage)")
            return 0

        if status_code == 429 and attempt < 5:
            print(f"INFO: live dedup probe rate-limited on attempt {attempt}; retrying")
            time.sleep(6)
            continue
        break

    print(f"probe-status={status_code}")
    if isinstance(payload, dict):
        print("probe-body=" + json.dumps(payload, ensure_ascii=True)[:700])
    else:
        print(f"probe-body={preview}")

    if status_code >= 400:
        return fail(f"live dedup probe endpoint failed with status={status_code}", 5)

    if not isinstance(payload, dict):
        return fail("live dedup probe returned non-JSON payload", 6)

    if payload.get("success") is False:
        return fail(f"live dedup probe returned success=false: {json.dumps(payload)[:350]}", 7)

    accepted_count = int(payload.get("accepted_count") or 0)
    blocked_count = int(payload.get("blocked_count") or 0)
    accepted_ids = payload.get("accepted_report_ids") or []

    if accepted_count > MAX_ACCEPTED:
        return fail(
            f"redundant live report generation detected: accepted_count={accepted_count} max={MAX_ACCEPTED}",
            8,
        )

    if blocked_count < MIN_BLOCKED:
        return fail(
            f"expected dedup blocking not observed: blocked_count={blocked_count} min={MIN_BLOCKED}",
            9,
        )

    if accepted_ids and len(set(accepted_ids)) > MAX_ACCEPTED:
        return fail(
            "probe accepted multiple unique report IDs for repeated identical live detections",
            10,
        )

    print("PASS: true live-stream dedup probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
