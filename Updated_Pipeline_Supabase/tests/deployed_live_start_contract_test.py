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


# Section: run the request json workflow with clear inputs and outputs.
def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
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


# Section: run the fail workflow with clear inputs and outputs.
def fail(msg: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: {msg}")
    return code


# Section: run the is expected webcam unavailable message workflow with clear inputs and outputs.
def is_expected_webcam_unavailable_message(msg: str) -> bool:
    message = (msg or "").lower()
    return (
        "failed to open webcam" in message
        or "could not open webcam" in message
        or ("webcam" in message and ("failed" in message or "unavailable" in message))
    )


# Section: run the stop live best effort workflow with clear inputs and outputs.
def stop_live_best_effort() -> None:
    # Prepare values needed by the next step.
    code, payload, text = request_json("POST", "/api/live/stop", json={}, timeout=20)
    if code >= 400 or not isinstance(payload, dict) or payload.get("success") is False:
        # Prepare preview for the next step.
        preview = json.dumps(payload)[:300] if isinstance(payload, dict) else text
        print(f"WARN: pre-test live stop cleanup was not accepted ({code}): {preview}")


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    try:
        code, payload, text = request_json("GET", "/api/live/status")
        if code >= 400 or not isinstance(payload, dict):
            # Return the prepared result to the caller.
            return fail(f"/api/live/status invalid ({code}): {text}", 3)
        # Trigger the side effect required for this stage.
        print("PASS: live status endpoint is reachable")

        stop_live_best_effort()

        last_failure = ""
        for attempt in range(1, 3):
            code, payload, text = request_json(
                "POST",
                "/api/live/start",
                json={"source": "webcam"},
                timeout=35,
            )
            # Choose the correct branch before the workflow continues.
            if not isinstance(payload, dict):
                # Prepare last failure for the next step.
                last_failure = f"/api/live/start non-JSON response ({code}): {text}"
            elif payload.get("success") is True:
                print(f"PASS: live start accepted webcam request (status={code})")
                stop_code, stop_payload, stop_text = request_json("POST", "/api/live/stop", json={})
                if stop_code >= 400 or not isinstance(stop_payload, dict) or stop_payload.get("success") is False:
                    # Return the prepared result to the caller.
                    return fail(
                        "live stop failed after successful start: "
                        f"status={stop_code} payload={json.dumps(stop_payload)[:300] if isinstance(stop_payload, dict) else stop_text}",
                        5,
                    )
                # Trigger the side effect required for this stage.
                print("PASS: live stop succeeded after start")
                return 0
            else:
                error_message = str(payload.get("error") or payload.get("message") or "")
                if is_expected_webcam_unavailable_message(error_message):
                    # Trigger the side effect required for this stage.
                    print("PASS: live start returned explicit webcam-unavailable response")
                    return 0
                last_failure = (
                    "unexpected /api/live/start failure payload: "
                    f"status={code} body={json.dumps(payload)[:400]}"
                )

            # Choose the correct branch before the workflow continues.
            if attempt < 2:
                # Trigger the side effect required for this stage.
                print(f"WARN: live start attempt {attempt} failed; cleaning up and retrying: {last_failure}")
                stop_live_best_effort()
                time.sleep(8)

        # Return the prepared result to the caller.
        return fail(last_failure, 6)
    except requests.HTTPError as exc:
        return fail(f"HTTP error during live start contract test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during live start contract test: {exc}", 21)


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
