import json
import os
import sys
import time

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

POLL_SECONDS = int(os.environ.get("LUNA_CONDITIONS_POLL_SECONDS", "30"))
POLL_INTERVAL = int(os.environ.get("LUNA_CONDITIONS_POLL_INTERVAL", "3"))
MAX_REPORT_IDS = int(os.environ.get("LUNA_CONDITIONS_MAX_REPORT_IDS", "15"))

ALLOWED_REPORT_STATUSES = {
    "pending",
    "queued",
    "processing",
    "generating",
    "completed",
    "failed",
    "not_found",
    "unknown",
}


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
    url = f"{BASE_URL}{path}"
    r = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    text_preview = (r.text or "")[:500]
    payload = None
    try:
        payload = r.json()
    except Exception:
        payload = None
    return r.status_code, payload, text_preview


def require_json_dict(path: str, name: str):
    code, payload, text = request_json("GET", path)
    if code >= 400:
        raise RuntimeError(f"{name} failed with {code}: {text}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} expected JSON object, got: {text}")
    print(f"PASS: {name}")
    return payload


def main() -> int:
    try:
        startup = require_json_dict("/api/system/startup-status", "startup-status")
        if not startup.get("ready"):
            return fail(f"startup-status not ready: {json.dumps(startup)[:400]}", 3)

        queue = require_json_dict("/api/queue/status", "queue-status")
        if not queue.get("available"):
            return fail(f"queue unavailable: {json.dumps(queue)[:400]}", 4)
        if not queue.get("worker_running"):
            return fail(f"queue worker not running: {json.dumps(queue)[:400]}", 5)

        stats = require_json_dict("/api/stats", "stats")
        if "total_violations" not in stats and "total" not in stats:
            return fail(f"stats missing total/total_violations: {json.dumps(stats)[:400]}", 6)

        code, pending_payload, pending_text = request_json("GET", "/api/reports/pending")
        if code >= 400 or not isinstance(pending_payload, list):
            return fail(f"pending reports endpoint invalid ({code}): {pending_text}", 7)
        print(f"PASS: pending-reports (count={len(pending_payload)})")

        code, violations_payload, violations_text = request_json("GET", f"/api/violations?limit={MAX_REPORT_IDS}")
        if code >= 400 or not isinstance(violations_payload, list):
            return fail(f"violations endpoint invalid ({code}): {violations_text}", 8)
        print(f"PASS: violations-list (count={len(violations_payload)})")

        report_ids = []
        for item in violations_payload:
            if isinstance(item, dict):
                rid = item.get("report_id")
                if rid and rid not in report_ids:
                    report_ids.append(rid)

        if not report_ids:
            print("PASS: no report IDs available; baseline deployed endpoints are healthy")
            return 0

        for rid in report_ids[:5]:
            code, payload, text = request_json("GET", f"/api/report/{rid}/status")
            if code >= 400 or not isinstance(payload, dict):
                return fail(f"report status failed for {rid} ({code}): {text}", 9)

            status_value = str(payload.get("status") or "unknown").lower()
            if status_value not in ALLOWED_REPORT_STATUSES:
                return fail(f"unexpected status for {rid}: {status_value}", 10)
            print(f"PASS: report-status {rid} -> {status_value}")

        conditions = {
            "already_completed": False,
            "already_queued_or_generating": False,
            "accepted_new_or_reprocess": False,
            "missing_original": False,
        }

        progression_candidate = None

        for rid in report_ids:
            code, payload, text = request_json(
                "POST",
                f"/api/report/{rid}/generate-now",
                json={"force": False},
                timeout=45,
            )

            if code >= 500:
                return fail(f"generate-now server error for {rid}: {code} {text}", 11)

            if not isinstance(payload, dict):
                return fail(f"generate-now non-JSON response for {rid}: {text}", 12)

            err_msg = str(payload.get("error") or payload.get("message") or "").lower()
            success = payload.get("success")

            print(f"INFO: generate-now {rid} -> code={code} body={json.dumps(payload)[:350]}")

            if success is False:
                if "original image is missing" in err_msg:
                    conditions["missing_original"] = True
                    continue
                return fail(f"generate-now returned success=false for {rid}: {json.dumps(payload)[:350]}", 13)

            if payload.get("already_completed"):
                conditions["already_completed"] = True
            elif payload.get("already_queued"):
                conditions["already_queued_or_generating"] = True
                if progression_candidate is None:
                    progression_candidate = rid
            else:
                conditions["accepted_new_or_reprocess"] = True
                if progression_candidate is None:
                    progression_candidate = rid

            if any(conditions.values()):
                # Continue scanning a few IDs to widen observed condition surface.
                if sum(1 for v in conditions.values() if v) >= 2:
                    break

        if not any(conditions.values()):
            return fail("no recognized generate-now condition observed", 14)

        if progression_candidate:
            steps = max(1, POLL_SECONDS // max(1, POLL_INTERVAL))
            seen = []
            for i in range(1, steps + 1):
                code, payload, text = request_json("GET", f"/api/report/{progression_candidate}/status")
                if code >= 400 or not isinstance(payload, dict):
                    return fail(
                        f"status polling failed for {progression_candidate} ({code}): {text}",
                        15,
                    )
                status_value = str(payload.get("status") or "unknown").lower()
                seen.append(status_value)
                print(f"poll-{i}: {progression_candidate} -> {status_value}")
                if status_value in ("completed", "failed"):
                    break
                time.sleep(POLL_INTERVAL)

            if seen and all(s in ("pending", "queued") for s in seen):
                return fail(
                    f"{progression_candidate} remained queued/pending across polling window",
                    16,
                )

        print("PASS: deployed conditions matrix")
        print("observed-conditions=" + json.dumps(conditions, ensure_ascii=True))
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during conditions test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error in conditions test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
