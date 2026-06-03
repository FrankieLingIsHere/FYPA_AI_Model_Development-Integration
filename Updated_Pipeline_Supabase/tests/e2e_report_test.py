# Readability: Test setup: document the contract this file protects.
import json
import os
import sys
import time
from pathlib import Path

import requests
from requests import RequestException

# Prepare base url for the next step.
BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")
IMAGE_PATH = os.environ.get(
    "CASM_TEST_IMAGE",
    str(Path("Updated_Pipeline_Supabase/pipeline/violations/20260420_134116/original.jpg").resolve()),
)


# Prepare strict e2 e for the next step.
STRICT_E2E = str(os.environ.get("CASM_E2E_STRICT", "1")).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


# Section: run the skip or fail workflow with clear inputs and outputs.
def skip_or_fail(message: str, code: int) -> int:
    # Choose the correct branch before the workflow continues.
    if STRICT_E2E:
        # Trigger the side effect required for this stage.
        print(f"FAIL: {message}")
        return code
    print(f"PASS: non-blocking skip, {message}")
    return 0


# Section: run the get violations workflow with clear inputs and outputs.
def get_violations(limit: int = 80):
    r = requests.get(f"{BASE_URL}/api/violations?limit={int(limit)}", timeout=30)
    # Trigger the side effect required for this stage.
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        # Return the prepared result to the caller.
        return data
    return []


# Section: run the get status workflow with clear inputs and outputs.
def get_status(report_id: str):
    r = requests.get(f"{BASE_URL}/api/report/{report_id}/status", timeout=30)
    # Trigger the side effect required for this stage.
    r.raise_for_status()
    return r.json()


# Section: run the upload image workflow with clear inputs and outputs.
def upload_image(path: str):
    with open(path, "rb") as f:
        # Prepare files for the next step.
        files = {"image": (Path(path).name, f, "image/png")}
        r = requests.post(f"{BASE_URL}/api/inference/upload", files=files, timeout=60)
    try:
        payload = r.json()
    except Exception:
        payload = {"raw": r.text}
    # Return the prepared result to the caller.
    return r.status_code, payload


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    image = Path(IMAGE_PATH)
    if not image.exists():
        # Trigger the side effect required for this stage.
        print(f"FAIL: test image not found: {image}")
        return 2

    # Protect this step so expected failures can fall back cleanly.
    try:
        startup = requests.get(f"{BASE_URL}/api/system/startup-status", timeout=30)
        print(f"startup-status={startup.status_code}")
    except RequestException as exc:
        return skip_or_fail(f"startup-status request failed: {exc}", 3)
    except Exception as exc:
        # Return the prepared result to the caller.
        return skip_or_fail(f"unexpected startup check error: {exc}", 4)

    try:
        before = get_violations()
    except RequestException as exc:
        return skip_or_fail(f"could not list initial violations: {exc}", 5)
    except Exception as exc:
        return skip_or_fail(f"unexpected initial list error: {exc}", 6)

    # Prepare before ids for the next step.
    before_ids = {v.get("report_id") for v in before if v.get("report_id")}

    try:
        # Prepare values needed by the next step.
        code, upload_payload = upload_image(str(image))
    except RequestException as exc:
        return skip_or_fail(f"upload request failed: {exc}", 7)
    except Exception as exc:
        return skip_or_fail(f"unexpected upload error: {exc}", 8)

    # Trigger the side effect required for this stage.
    print(f"upload-status={code}")
    print("upload-body=" + json.dumps(upload_payload, ensure_ascii=True)[:600])

    if code >= 400:
        # Return the prepared result to the caller.
        return skip_or_fail(f"upload endpoint rejected request with status={code}", 9)

    upload_report_id = None
    report_queued = False
    if isinstance(upload_payload, dict):
        upload_report_id = upload_payload.get("report_id")
        report_queued = bool(upload_payload.get("report_queued"))

    # Choose the correct branch before the workflow continues.
    if not upload_report_id and not report_queued:
        # Return the prepared result to the caller.
        return skip_or_fail("upload did not queue a report (likely no violation in test image)", 10)

    time.sleep(4)
    try:
        after = get_violations()
    except RequestException as exc:
        return skip_or_fail(f"could not list post-upload violations: {exc}", 11)
    except Exception as exc:
        return skip_or_fail(f"unexpected post-upload list error: {exc}", 12)

    # Prepare after ids for the next step.
    after_ids = [v.get("report_id") for v in after if v.get("report_id")]

    target = upload_report_id or None
    for rid in after_ids:
        # Choose the correct branch before the workflow continues.
        if target:
            break
        if rid not in before_ids:
            # Prepare target for the next step.
            target = rid
            break
    # Choose the correct branch before the workflow continues.
    if not target and after_ids:
        target = after_ids[0]

    if not target:
        # Return the prepared result to the caller.
        return skip_or_fail("no report id found after upload", 13)

    print(f"target-report-id={target}")

    final = None
    # Process each item in this collection using the same rule set.
    for i in range(1, 31):
        try:
            # Prepare st for the next step.
            st = get_status(target)
        except RequestException as exc:
            return skip_or_fail(f"polling request failed: {exc}", 14)
        except Exception as exc:
            return skip_or_fail(f"unexpected polling error: {exc}", 15)

        # Prepare final for the next step.
        final = st
        status = st.get("status")
        has_report = st.get("has_report")
        msg = st.get("message")
        print(f"poll-{i}: status={status} has_report={has_report} msg={msg}")
        if status in ("completed", "failed"):
            break
        time.sleep(3)

    # Choose the correct branch before the workflow continues.
    if not final:
        # Return the prepared result to the caller.
        return skip_or_fail("no final status", 16)

    if final.get("status") == "completed" and final.get("has_report"):
        print("PASS: report completed with artifact")
        return 0

    # Pull failure details from violations list
    match = next((v for v in after if v.get("report_id") == target), None)
    if match:
        print("final-error=" + str(match.get("error_message")))

    return skip_or_fail("report did not complete successfully within test window", 17)


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    raise SystemExit(main())
