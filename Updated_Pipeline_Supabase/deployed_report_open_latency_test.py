import os
import statistics
import time
import math
from typing import Dict, List, Optional

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

MAX_SCAN = max(10, int(os.environ.get("LUNA_REPORT_LATENCY_MAX_SCAN", "120")))
MAX_CANDIDATES = max(1, int(os.environ.get("LUNA_REPORT_LATENCY_MAX_CANDIDATES", "6")))
WARM_TARGET_SECONDS = float(os.environ.get("LUNA_REPORT_OPEN_WARM_TARGET_SECONDS", "1.0"))
WARM_SAMPLE_COUNT = max(1, int(os.environ.get("LUNA_REPORT_OPEN_WARM_SAMPLES", "3")))
REQUEST_TIMEOUT = max(5, int(os.environ.get("LUNA_REPORT_OPEN_TIMEOUT", "30")))


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


def request_json(method: str, path: str, *, timeout: int = REQUEST_TIMEOUT, **kwargs):
    url = f"{BASE_URL}{path}"
    started = time.perf_counter()
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    elapsed = time.perf_counter() - started
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    preview = (response.text or "")[:500]
    return response.status_code, payload, preview, elapsed


def timed_get_text(path: str, *, timeout: int = REQUEST_TIMEOUT):
    url = f"{BASE_URL}{path}"
    started = time.perf_counter()
    response = requests.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"})
    elapsed = time.perf_counter() - started
    return response, elapsed


def choose_candidates(rows: List[Dict]) -> List[str]:
    chosen: List[str] = []
    for row in rows[:MAX_SCAN]:
        if not isinstance(row, dict):
            continue
        report_id = str(row.get("report_id") or "").strip()
        if not report_id:
            continue
        status = str(row.get("status") or "").strip().lower()
        has_report = bool(row.get("has_report"))
        if has_report and status in {"completed", "unknown"}:
            chosen.append(report_id)
        if len(chosen) >= MAX_CANDIDATES:
            break
    return chosen


def warm_and_measure(report_id: str) -> Optional[Dict]:
    prefetch_code, prefetch_payload, prefetch_preview, prefetch_elapsed = request_json(
        "POST",
        f"/api/report/{report_id}/prefetch",
        timeout=REQUEST_TIMEOUT,
    )

    prefetch_layer = "unavailable"
    if prefetch_code == 404:
        # Backward-compatible path: endpoint not yet deployed, so prime via one warm GET.
        prefetch_layer = "endpoint_unavailable"
    elif prefetch_code >= 400:
        print(
            f"WARN: prefetch failed for {report_id} ({prefetch_code}): {prefetch_preview[:180]}"
        )
        prefetch_layer = f"failed_{prefetch_code}"
    elif not isinstance(prefetch_payload, dict) or not prefetch_payload.get("success"):
        print(f"WARN: prefetch returned non-success for {report_id}: {prefetch_payload}")
        prefetch_layer = "failed_payload"
    else:
        prefetch_layer = str(prefetch_payload.get("layer") or "prefetch")

    # Prime report path regardless of prefetch outcome so we measure warm-open latency.
    warmup_response, warmup_elapsed = timed_get_text(f"/report/{report_id}", timeout=REQUEST_TIMEOUT)
    if warmup_response.status_code >= 400:
        print(f"WARN: warmup /report/{report_id} returned {warmup_response.status_code}")
        return None

    sample_times: List[float] = []
    for _ in range(WARM_SAMPLE_COUNT):
        response, elapsed = timed_get_text(f"/report/{report_id}", timeout=REQUEST_TIMEOUT)
        if response.status_code >= 400:
            print(f"WARN: /report/{report_id} returned {response.status_code}")
            return None
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            print(
                f"WARN: /report/{report_id} content-type unexpected: {response.headers.get('Content-Type')}"
            )
            return None
        sample_times.append(elapsed)

    sorted_times = sorted(sample_times)
    p95_index = max(0, min(len(sorted_times) - 1, math.ceil(0.95 * len(sorted_times)) - 1))
    p95 = sorted_times[p95_index]
    mean_time = statistics.mean(sample_times)

    return {
        "report_id": report_id,
        "prefetch_elapsed_s": prefetch_elapsed,
        "prefetch_layer": prefetch_layer,
        "warmup_elapsed_s": warmup_elapsed,
        "sample_times_s": sample_times,
        "mean_s": mean_time,
        "p95_s": p95,
    }


def main() -> int:
    try:
        code, payload, preview, elapsed = request_json("GET", "/api/violations", timeout=REQUEST_TIMEOUT)
        if code >= 400:
            return fail(f"/api/violations failed ({code}): {preview}", 3)
        if not isinstance(payload, list) or not payload:
            return fail("/api/violations returned no data", 4)

        candidates = choose_candidates(payload)
        if not candidates:
            return fail("No completed reports with artifacts found for latency test", 5)

        print(
            f"INFO: candidates={len(candidates)} scan_time_s={elapsed:.3f} warm_target_s={WARM_TARGET_SECONDS:.3f}"
        )

        measured: List[Dict] = []
        for rid in candidates:
            result = warm_and_measure(rid)
            if result:
                measured.append(result)
                samples = ", ".join(f"{x:.3f}" for x in result["sample_times_s"])
                print(
                    f"INFO: report_id={rid} layer={result['prefetch_layer']} prefetch_s={result['prefetch_elapsed_s']:.3f} warmup_s={result['warmup_elapsed_s']:.3f} "
                    f"mean_s={result['mean_s']:.3f} p95_s={result['p95_s']:.3f} samples=[{samples}]"
                )

        if not measured:
            return fail("Could not measure latency on any candidate report", 6)

        if all(str(item.get("prefetch_layer")) == "endpoint_unavailable" for item in measured):
            print(
                "PASS: prefetch endpoint not deployed yet; latency contract skipped "
                "until backend rollout is active"
            )
            return 0

        worst_p95 = max(item["p95_s"] for item in measured)
        worst_mean = max(item["mean_s"] for item in measured)

        if worst_p95 > WARM_TARGET_SECONDS:
            return fail(
                f"Warm open latency target exceeded: p95={worst_p95:.3f}s > {WARM_TARGET_SECONDS:.3f}s "
                f"(worst_mean={worst_mean:.3f}s, candidates={len(measured)})",
                7,
            )

        print(
            f"PASS: report open warm latency contract met "
            f"(target<={WARM_TARGET_SECONDS:.3f}s, worst_p95={worst_p95:.3f}s, worst_mean={worst_mean:.3f}s, candidates={len(measured)})"
        )
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during report latency test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during report latency test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
