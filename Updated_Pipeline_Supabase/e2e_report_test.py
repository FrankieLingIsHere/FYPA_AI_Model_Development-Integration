import json
import os
import sys
import time
from pathlib import Path

import requests

BASE_URL = os.environ.get("LUNA_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
IMAGE_PATH = os.environ.get(
    "LUNA_TEST_IMAGE",
    str(Path("Updated_Pipeline_Supabase/static/images/handbook-live.png").resolve()),
)


def get_violations():
    r = requests.get(f"{BASE_URL}/api/violations", timeout=30)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return data
    return []


def get_status(report_id: str):
    r = requests.get(f"{BASE_URL}/api/report/{report_id}/status", timeout=30)
    r.raise_for_status()
    return r.json()


def upload_image(path: str):
    with open(path, "rb") as f:
        files = {"image": (Path(path).name, f, "image/png")}
        r = requests.post(f"{BASE_URL}/api/inference/upload", files=files, timeout=60)
    try:
        payload = r.json()
    except Exception:
        payload = {"raw": r.text}
    return r.status_code, payload


def main() -> int:
    image = Path(IMAGE_PATH)
    if not image.exists():
        print(f"FAIL: test image not found: {image}")
        return 2

    # Warm check
    startup = requests.get(f"{BASE_URL}/api/system/startup-status", timeout=30)
    print(f"startup-status={startup.status_code}")

    before = get_violations()
    before_ids = {v.get("report_id") for v in before if v.get("report_id")}

    code, upload_payload = upload_image(str(image))
    print(f"upload-status={code}")
    print("upload-body=" + json.dumps(upload_payload, ensure_ascii=True)[:600])

    if code >= 400:
        print("FAIL: upload endpoint rejected request")
        return 3

    upload_report_id = None
    report_queued = False
    if isinstance(upload_payload, dict):
        upload_report_id = upload_payload.get("report_id")
        report_queued = bool(upload_payload.get("report_queued"))

    if not upload_report_id and not report_queued:
        print("FAIL: upload did not queue a report (likely no violation in test image)")
        return 7

    time.sleep(4)
    after = get_violations()
    after_ids = [v.get("report_id") for v in after if v.get("report_id")]

    target = upload_report_id or None
    for rid in after_ids:
        if target:
            break
        if rid not in before_ids:
            target = rid
            break
    if not target and after_ids:
        target = after_ids[0]

    if not target:
        print("FAIL: no report id found after upload")
        return 4

    print(f"target-report-id={target}")

    final = None
    for i in range(1, 31):
        st = get_status(target)
        final = st
        status = st.get("status")
        has_report = st.get("has_report")
        msg = st.get("message")
        print(f"poll-{i}: status={status} has_report={has_report} msg={msg}")
        if status in ("completed", "failed"):
            break
        time.sleep(3)

    if not final:
        print("FAIL: no final status")
        return 5

    if final.get("status") == "completed" and final.get("has_report"):
        print("PASS: report completed with artifact")
        return 0

    # Pull failure details from violations list
    match = next((v for v in after if v.get("report_id") == target), None)
    if match:
        print("final-error=" + str(match.get("error_message")))

    print("FAIL: report did not complete successfully")
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
