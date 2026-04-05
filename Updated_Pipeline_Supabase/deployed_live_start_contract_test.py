import json
import os
import sys

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")


def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    preview = (response.text or "")[:500]
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, preview


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


def is_expected_webcam_unavailable_message(msg: str) -> bool:
    message = (msg or "").lower()
    return (
        "failed to open webcam" in message
        or "could not open webcam" in message
        or ("webcam" in message and ("failed" in message or "unavailable" in message))
    )


def main() -> int:
    try:
        code, payload, text = request_json("GET", "/api/live/status")
        if code >= 400 or not isinstance(payload, dict):
            return fail(f"/api/live/status invalid ({code}): {text}", 3)
        print("PASS: live status endpoint is reachable")

        code, payload, text = request_json(
            "POST",
            "/api/live/start",
            json={"source": "webcam"},
            timeout=35,
        )
        if not isinstance(payload, dict):
            return fail(f"/api/live/start non-JSON response ({code}): {text}", 4)

        if payload.get("success") is True:
            print(f"PASS: live start accepted webcam request (status={code})")
            stop_code, stop_payload, stop_text = request_json("POST", "/api/live/stop", json={})
            if stop_code >= 400 or not isinstance(stop_payload, dict) or stop_payload.get("success") is False:
                return fail(
                    "live stop failed after successful start: "
                    f"status={stop_code} payload={json.dumps(stop_payload)[:300] if isinstance(stop_payload, dict) else stop_text}",
                    5,
                )
            print("PASS: live stop succeeded after start")
            return 0

        error_message = str(payload.get("error") or payload.get("message") or "")
        if is_expected_webcam_unavailable_message(error_message):
            print("PASS: live start returned explicit webcam-unavailable response")
            return 0

        return fail(
            "unexpected /api/live/start failure payload: "
            f"status={code} body={json.dumps(payload)[:400]}",
            6,
        )
    except requests.HTTPError as exc:
        return fail(f"HTTP error during live start contract test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during live start contract test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
