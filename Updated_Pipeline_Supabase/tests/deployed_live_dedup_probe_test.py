# Readability: Test setup: document the contract this file protects.
import json
import os
import sys
import time

import requests


# Prepare base url for the next step.
BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

REPEATS = max(2, int(os.environ.get("CASM_LIVE_DEDUP_REPEATS", "3")))
MAX_ACCEPTED = max(1, int(os.environ.get("CASM_LIVE_DEDUP_MAX_ACCEPTED", "1")))
MIN_BLOCKED = max(1, int(os.environ.get("CASM_LIVE_DEDUP_MIN_BLOCKED", "1")))
STRICT_LIVE_DEDUP = os.environ.get("CASM_LIVE_DEDUP_STRICT", "1") != "0"


# Section: run the fail workflow with clear inputs and outputs.
def fail(msg: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: {msg}")
    return code


# Section: run the skip or fail workflow with clear inputs and outputs.
def skip_or_fail(msg: str, code: int) -> int:
    if STRICT_LIVE_DEDUP:
        # Return the prepared result to the caller.
        return fail(msg, code)
    print(f"PASS: true live dedup probe skipped ({msg})")
    return 0


# Section: run the request json workflow with clear inputs and outputs.
def request_json(method: str, path: str, *, timeout: int = 45, **kwargs):
    # Prepare url for the next step.
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    preview = (response.text or "")[:500]
    payload = None
    try:
        # Prepare payload for the next step.
        payload = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, preview


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare values needed by the next step.
    startup_code, startup_payload, startup_text = request_json("GET", "/api/system/startup-status", timeout=30)
    if startup_code >= 400:
        # Return the prepared result to the caller.
        return fail(f"startup-status failed ({startup_code}): {startup_text}", 3)
    if isinstance(startup_payload, dict) and not startup_payload.get("ready", True):
        return fail(f"startup-status not ready: {json.dumps(startup_payload)[:300]}", 4)

    status_code = None
    payload = None
    preview = ""
    # Prepare gateway like codes for the next step.
    gateway_like_codes = {502, 503, 504}
    for attempt in range(1, 6):
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare values needed by the next step.
            status_code, payload, preview = request_json(
                "POST",
                "/api/testing/live-dedup/probe",
                json={"repeats": REPEATS},
                timeout=70,
            )
        except requests.RequestException as exc:
            print(f"INFO: live dedup probe request failed on attempt {attempt}: {exc}")
            if attempt < 5:
                # Trigger the side effect required for this stage.
                time.sleep(6)
                continue
            # Return the prepared result to the caller.
            return skip_or_fail("transient request failures on deployed target", 11)

        # Endpoint may lag behind repository pushes on deployed targets.
        # Choose the correct branch before the workflow continues.
        if status_code in (404,):
            print(f"INFO: live dedup probe endpoint unavailable on attempt {attempt} (status={status_code})")
            if attempt < 5:
                time.sleep(8)
                continue
            return skip_or_fail("endpoint not yet available on deployed target", 12)

        if status_code == 403 and isinstance(payload, dict) and payload.get("error") == "testing_endpoints_disabled":
            # Return the prepared result to the caller.
            return skip_or_fail("testing endpoints disabled by default", 13)

        # Choose the correct branch before the workflow continues.
        if status_code in gateway_like_codes:
            print(f"INFO: live dedup probe gateway status on attempt {attempt}: {status_code}")
            if attempt < 5:
                # Trigger the side effect required for this stage.
                time.sleep(6)
                continue
            return skip_or_fail("persistent gateway outage", 14)

        if status_code == 429 and attempt < 5:
            # Trigger the side effect required for this stage.
            print(f"INFO: live dedup probe rate-limited on attempt {attempt}; retrying")
            time.sleep(6)
            continue
        break

    # Trigger the side effect required for this stage.
    print(f"probe-status={status_code}")
    if isinstance(payload, dict):
        # Trigger the side effect required for this stage.
        print("probe-body=" + json.dumps(payload, ensure_ascii=True)[:700])
    else:
        print(f"probe-body={preview}")

    if status_code >= 400:
        return fail(f"live dedup probe endpoint failed with status={status_code}", 5)

    # Choose the correct branch before the workflow continues.
    if not isinstance(payload, dict):
        return fail("live dedup probe returned non-JSON payload", 6)

    if payload.get("success") is False:
        # Return the prepared result to the caller.
        return fail(f"live dedup probe returned success=false: {json.dumps(payload)[:350]}", 7)

    accepted_count = int(payload.get("accepted_count") or 0)
    blocked_count = int(payload.get("blocked_count") or 0)
    accepted_ids = payload.get("accepted_report_ids") or []

    # Choose the correct branch before the workflow continues.
    if accepted_count > MAX_ACCEPTED:
        return fail(
            f"redundant live report generation detected: accepted_count={accepted_count} max={MAX_ACCEPTED}",
            8,
        )

    if blocked_count < MIN_BLOCKED:
        # Return the prepared result to the caller.
        return fail(
            f"expected dedup blocking not observed: blocked_count={blocked_count} min={MIN_BLOCKED}",
            9,
        )

    # Choose the correct branch before the workflow continues.
    if accepted_ids and len(set(accepted_ids)) > MAX_ACCEPTED:
        return fail(
            "probe accepted multiple unique report IDs for repeated identical live detections",
            10,
        )

    print("PASS: true live-stream dedup probe")
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
