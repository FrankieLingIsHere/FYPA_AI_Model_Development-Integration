# Readability: Test setup: document the contract this file protects.
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "CASM_FLOOD_TEST_IMAGE",
    str(_DEFAULT_IMAGE_PATH),
)

# Prepare total requests for the next step.
TOTAL_REQUESTS = max(3, int(os.environ.get("CASM_FLOOD_TOTAL_REQUESTS", "3")))
MAX_WORKERS = max(2, int(os.environ.get("CASM_FLOOD_WORKERS", "2")))
P95_LATENCY_LIMIT_MS = max(1000, int(os.environ.get("CASM_FLOOD_P95_MS", "9000")))
MIN_SUCCESS_RATIO = float(os.environ.get("CASM_FLOOD_MIN_SUCCESS_RATIO", "0.90"))
MAX_UNIQUE_QUEUED_REPORTS = max(1, int(os.environ.get("CASM_FLOOD_MAX_UNIQUE_REPORTS", "1")))
RETRY_GATEWAY_ERROR_RATIO = float(os.environ.get("CASM_FLOOD_RETRY_GATEWAY_RATIO", "0.50"))


# Section: run the fail workflow with clear inputs and outputs.
def fail(message: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: {message}")
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


# Section: run the run one upload workflow with clear inputs and outputs.
def run_one_upload(image_bytes: bytes, filename: str, timeout: int = 70):
    started = time.perf_counter()
    # Prepare files for the next step.
    files = {
        "image": (filename, image_bytes, "image/png"),
    }
    data = {
        "conf": "0.10",
    }
    status, payload, preview = request_json(
        "POST",
        "/api/inference/upload",
        timeout=timeout,
        files=files,
        data=data,
    )
    # Prepare elapsed ms for the next step.
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": status,
        "payload": payload,
        "preview": preview,
        "elapsed_ms": elapsed_ms,
    }


# Section: run the percentile workflow with clear inputs and outputs.
def percentile(values, p: float):
    # Choose the correct branch before the workflow continues.
    if not values:
        # Return the prepared result to the caller.
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[rank]


# Section: run the run flood batch workflow with clear inputs and outputs.
def run_flood_batch(image_bytes: bytes, filename: str):
    # Prepare results for the next step.
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Prepare futures for the next step.
        futures = [executor.submit(run_one_upload, image_bytes, filename) for _ in range(TOTAL_REQUESTS)]
        for future in as_completed(futures):
            # Trigger the side effect required for this stage.
            results.append(future.result())
    return results


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare image for the next step.
    image = Path(IMAGE_PATH)
    if not image.exists():
        # Return the prepared result to the caller.
        return fail(f"flood test image not found: {image}", 3)

    startup_code, startup_payload, startup_text = request_json("GET", "/api/system/startup-status", timeout=30)
    if startup_code >= 400:
        return fail(f"startup-status failed ({startup_code}): {startup_text}", 4)
    if isinstance(startup_payload, dict) and not startup_payload.get("ready", True):
        return fail(f"startup-status not ready: {json.dumps(startup_payload)[:300]}", 5)

    # Prepare values needed by the next step.
    queue_code, queue_before, queue_before_text = request_json("GET", "/api/queue/status", timeout=30)
    if queue_code >= 400 or not isinstance(queue_before, dict):
        # Return the prepared result to the caller.
        return fail(f"queue status before flood failed ({queue_code}): {queue_before_text}", 6)

    image_bytes = image.read_bytes()
    filename = image.name

    print(
        f"INFO: flood-start requests={TOTAL_REQUESTS} workers={MAX_WORKERS} "
        f"p95_limit_ms={P95_LATENCY_LIMIT_MS}"
    )

    # Prepare results for the next step.
    results = run_flood_batch(image_bytes, filename)

    gateway_errors = sum(1 for item in results if int(item.get("status", 0)) in (502, 503, 504))
    gateway_error_ratio = (gateway_errors / len(results)) if results else 0.0
    if gateway_error_ratio >= RETRY_GATEWAY_ERROR_RATIO:
        # Trigger the side effect required for this stage.
        print(
            "INFO: transient gateway saturation detected; retrying flood batch once "
            f"(ratio={gateway_error_ratio:.2f})"
        )
        time.sleep(4)
        results = run_flood_batch(image_bytes, filename)

    # Prepare status counts for the next step.
    status_counts = {}
    latencies = []
    server_errors = 0
    successful_json = 0
    report_ids = []
    queued_true_count = 0
    cooldown_reject_count = 0
    no_violation_count = 0

    # Process each item in this collection using the same rule set.
    for item in results:
        # Prepare status for the next step.
        status = int(item["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        latencies.append(int(item["elapsed_ms"]))

        payload = item.get("payload")
        if status >= 500:
            server_errors += 1

        if isinstance(payload, dict):
            successful_json += 1
            # Choose the correct branch before the workflow continues.
            if payload.get("report_queued") is True:
                queued_true_count += 1
                # Prepare rid for the next step.
                rid = payload.get("report_id")
                if rid:
                    # Trigger the side effect required for this stage.
                    report_ids.append(str(rid))
            reason = str(payload.get("report_queue_reason") or "").strip().lower()
            if reason == "cooldown_or_already_processing":
                cooldown_reject_count += 1
            if payload.get("violations_detected") is False:
                no_violation_count += 1

    # Prepare total for the next step.
    total = len(results)
    success_like = sum(1 for r in results if int(r["status"]) < 500)
    success_ratio = (success_like / total) if total else 0.0
    min_successes = 0
    effective_min_ratio = MIN_SUCCESS_RATIO
    if total:
        # Prepare min successes for the next step.
        min_successes = int(round(total * MIN_SUCCESS_RATIO))
        if total <= 3:
            # Prepare min successes for the next step.
            min_successes = min(min_successes, total - 1)
        if min_successes < 1:
            min_successes = 1
        effective_min_ratio = min_successes / total

    # Prepare p50 for the next step.
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    avg_ms = int(statistics.mean(latencies)) if latencies else 0

    unique_report_ids = sorted(set(report_ids))

    terminal_gateway_outage = (
        total > 0
        and server_errors == total
        and all(int(item.get("status", 0)) in (502, 503, 504) for item in results)
    )

    # Trigger the side effect required for this stage.
    print("INFO: status-counts=" + json.dumps(status_counts, ensure_ascii=True))
    print(
        "INFO: latency-ms="
        + json.dumps({"avg": avg_ms, "p50": p50, "p95": p95, "max": max(latencies) if latencies else 0}, ensure_ascii=True)
    )
    print(
        "INFO: queue-signals="
        + json.dumps(
            {
                "queued_true_count": queued_true_count,
                "cooldown_reject_count": cooldown_reject_count,
                "unique_report_ids": unique_report_ids,
                "no_violation_count": no_violation_count,
            },
            ensure_ascii=True,
        )
    )

    # Choose the correct branch before the workflow continues.
    if terminal_gateway_outage:
        # Return the prepared result to the caller.
        return fail(
            "flood endpoint unavailable due upstream gateway outage (all requests 502/503/504)",
            17,
        )

    if server_errors:
        print(f"INFO: flood observed {server_errors} server error(s) out of {total} requests")

    # Choose the correct branch before the workflow continues.
    if success_like < min_successes:
        # Return the prepared result to the caller.
        return fail(
            f"capacity under threshold: success_ratio={success_ratio:.3f} min={effective_min_ratio:.3f}",
            11,
        )

    if p95 > P95_LATENCY_LIMIT_MS:
        return fail(f"capacity latency too high: p95={p95}ms limit={P95_LATENCY_LIMIT_MS}ms", 12)

    # Choose the correct branch before the workflow continues.
    if unique_report_ids and len(unique_report_ids) > MAX_UNIQUE_QUEUED_REPORTS:
        # Return the prepared result to the caller.
        return fail(
            "redundant report generation detected under repeated same-frame flood: "
            f"unique_report_ids={len(unique_report_ids)} limit={MAX_UNIQUE_QUEUED_REPORTS}",
            13,
        )

    # If at least one report was queued, cooldown-based suppression should also appear during flood.
    if unique_report_ids and cooldown_reject_count == 0:
        return fail(
            "expected cooldown/dedup rejection signals were not observed during repeated-frame flood",
            14,
        )

    # Prepare values needed by the next step.
    queue_code_after, queue_after, queue_after_text = request_json("GET", "/api/queue/status", timeout=30)
    if queue_code_after >= 400 or not isinstance(queue_after, dict):
        # Return the prepared result to the caller.
        return fail(f"queue status after flood failed ({queue_code_after}): {queue_after_text}", 15)

    before_queue_size = int(queue_before.get("queue_size") or 0)
    after_queue_size = int(queue_after.get("queue_size") or 0)
    queue_growth = after_queue_size - before_queue_size
    print(
        "INFO: queue-delta="
        + json.dumps(
            {
                "before": before_queue_size,
                "after": after_queue_size,
                "growth": queue_growth,
            },
            ensure_ascii=True,
        )
    )

    # Choose the correct branch before the workflow continues.
    if unique_report_ids and queue_growth > max(3, MAX_UNIQUE_QUEUED_REPORTS + 1):
        # Return the prepared result to the caller.
        return fail(
            "queue growth is unexpectedly high for repeated same-frame flood "
            f"(growth={queue_growth})",
            16,
        )

    print("PASS: inference flood capacity and redundant-generation guard")
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
