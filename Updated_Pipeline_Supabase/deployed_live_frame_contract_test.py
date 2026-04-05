import json
import os
from pathlib import Path

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

IMAGE_PATH = os.environ.get(
    "LUNA_LIVE_FRAME_TEST_IMAGE",
    str(Path("Updated_Pipeline_Supabase/static/images/handbook-live.png").resolve()),
)


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


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


def main() -> int:
    image = Path(IMAGE_PATH)
    if not image.exists():
        return fail(f"live-frame test image not found: {image}", 3)

    try:
        startup_code, startup_payload, startup_text = request_json("GET", "/api/system/startup-status", timeout=30)
        if startup_code >= 400:
            return fail(f"startup-status failed ({startup_code}): {startup_text}", 4)
        if isinstance(startup_payload, dict) and not startup_payload.get("ready", True):
            return fail(f"startup-status not ready: {json.dumps(startup_payload)[:300]}", 5)

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

        if code >= 400:
            return fail(f"/api/inference/live-frame failed ({code}): {text}", 6)
        if not isinstance(payload, dict):
            return fail(f"/api/inference/live-frame non-JSON response ({code}): {text}", 7)
        if payload.get("success") is not True:
            return fail(f"/api/inference/live-frame success flag false: {json.dumps(payload)[:350]}", 8)

        source = str(payload.get("source") or "")
        if source != "near_edge_live_frame":
            return fail(f"/api/inference/live-frame source mismatch: {source}", 9)

        required_keys = (
            "detections",
            "count",
            "violations_detected",
            "violation_count",
            "report_queued",
            "report_queue_reason",
        )
        missing = [k for k in required_keys if k not in payload]
        if missing:
            return fail(f"/api/inference/live-frame missing keys: {missing}", 10)

        if not isinstance(payload.get("detections"), list):
            return fail("/api/inference/live-frame detections is not a list", 11)

        print(
            "PASS: live-frame contract verified "
            f"(count={payload.get('count')}, violations={payload.get('violations_detected')}, "
            f"queued={payload.get('report_queued')})"
        )
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during live-frame contract test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during live-frame contract test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
