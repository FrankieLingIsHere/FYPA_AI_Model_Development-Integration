# Readability: Test setup: document the contract this file protects.
import json
import os
from pathlib import Path

import requests


# Prepare base url for the next step.
BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_IMAGE_PATH = (_SCRIPT_DIR.parent / "static" / "images" / "handbook-live.png").resolve()

IMAGE_PATH = os.environ.get(
    "CASM_LIVE_FRAME_TEST_IMAGE",
    str(_DEFAULT_IMAGE_PATH),
)


# Section: run the fail workflow with clear inputs and outputs.
def fail(msg: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: {msg}")
    return code


# Section: run the request json workflow with clear inputs and outputs.
def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    preview = (response.text or "")[:500]
    payload = None
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare payload for the next step.
        payload = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, preview


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    image = Path(IMAGE_PATH)
    # Choose the correct branch before the workflow continues.
    if not image.exists():
        # Return the prepared result to the caller.
        return fail(f"live-frame test image not found: {image}", 3)

    try:
        startup_code, startup_payload, startup_text = request_json("GET", "/api/system/startup-status", timeout=30)
        if startup_code >= 400:
            # Return the prepared result to the caller.
            return fail(f"startup-status failed ({startup_code}): {startup_text}", 4)
        if isinstance(startup_payload, dict) and not startup_payload.get("ready", True):
            return fail(f"startup-status not ready: {json.dumps(startup_payload)[:300]}", 5)

        # Prepare image bytes for the next step.
        image_bytes = image.read_bytes()
        files = {"image": (image.name, image_bytes, "image/png")}
        data = {"conf": "0.10"}

        code, payload, text = request_json(
            "POST",
            "/api/inference/live-frame",
            timeout=45,
            files=files,
            data=data,
        )

        # Choose the correct branch before the workflow continues.
        if code >= 400:
            # Return the prepared result to the caller.
            return fail(f"/api/inference/live-frame failed ({code}): {text}", 6)
        if not isinstance(payload, dict):
            return fail(f"/api/inference/live-frame non-JSON response ({code}): {text}", 7)
        if payload.get("success") is not True:
            return fail(f"/api/inference/live-frame success flag false: {json.dumps(payload)[:350]}", 8)

        source = str(payload.get("source") or "")
        if source != "near_edge_live_frame":
            return fail(f"/api/inference/live-frame source mismatch: {source}", 9)

        # Prepare required keys for the next step.
        required_keys = (
            "detections",
            "count",
            "violations_detected",
            "violation_count",
            "report_queued",
            "report_queue_reason",
        )
        missing = [k for k in required_keys if k not in payload]
        # Choose the correct branch before the workflow continues.
        if missing:
            # Return the prepared result to the caller.
            return fail(f"/api/inference/live-frame missing keys: {missing}", 10)

        if not isinstance(payload.get("detections"), list):
            return fail("/api/inference/live-frame detections is not a list", 11)

        print(
            "PASS: live-frame contract verified "
            f"(count={payload.get('count')}, violations={payload.get('violations_detected')}, "
            f"queued={payload.get('report_queued')})"
        )
        # Return the prepared result to the caller.
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during live-frame contract test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during live-frame contract test: {exc}", 21)


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
