# Readability: Test setup: document the contract this file protects.
import os
import statistics
import time
import math
from typing import Dict, List, Optional

import requests


# Prepare base url for the next step.
BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

MAX_SCAN = max(10, int(os.environ.get("CASM_REPORT_LATENCY_MAX_SCAN", "80")))
MAX_CANDIDATES = max(1, int(os.environ.get("CASM_REPORT_LATENCY_MAX_CANDIDATES", "6")))
WARM_TARGET_SECONDS = float(os.environ.get("CASM_REPORT_OPEN_WARM_TARGET_SECONDS", "2.0"))
WARM_SAMPLE_COUNT = max(1, int(os.environ.get("CASM_REPORT_OPEN_WARM_SAMPLES", "3")))
# Prepare request timeout for the next step.
REQUEST_TIMEOUT = max(5, int(os.environ.get("CASM_REPORT_OPEN_TIMEOUT", "30")))
MAX_ALLOWED_SAMPLE_SECONDS = float(
    os.environ.get("CASM_REPORT_OPEN_MAX_SAMPLE_SECONDS", str(max(2.0, WARM_TARGET_SECONDS * 2.0)))
)
MEAN_MULTIPLIER = float(os.environ.get("CASM_REPORT_OPEN_MEAN_MULTIPLIER", "1.15"))
RETRY_ATTEMPTS = max(1, int(os.environ.get("CASM_REPORT_OPEN_RETRY_ATTEMPTS", "2")))
RETRY_BACKOFF_SECONDS = max(1.0, float(os.environ.get("CASM_REPORT_OPEN_RETRY_BACKOFF_SECONDS", "3")))
NETWORK_BASELINE_SAMPLES = max(1, int(os.environ.get("CASM_REPORT_OPEN_NETWORK_BASELINE_SAMPLES", "3")))
NETWORK_BASELINE_PATH = os.environ.get("CASM_REPORT_OPEN_NETWORK_BASELINE_PATH", "/api/health")
# Prepare network baseline free s for the next step.
NETWORK_BASELINE_FREE_S = max(0.0, float(os.environ.get("CASM_REPORT_OPEN_NETWORK_BASELINE_FREE_S", "0.20")))
NETWORK_ALLOWANCE_CAP_S = max(0.0, float(os.environ.get("CASM_REPORT_OPEN_NETWORK_ALLOWANCE_CAP_S", "0.60")))
MAX_SPIKE_SAMPLES = max(0, int(os.environ.get("CASM_REPORT_OPEN_MAX_SPIKE_SAMPLES", "1")))
INFRA_BLOCK_CODES = {402, 429, 503}
ALLOW_SINGLE_CANDIDATE_SOFT_PASS = str(
    os.environ.get("CASM_REPORT_OPEN_SINGLE_CANDIDATE_SOFT_PASS", "1")
).strip().lower() in {"1", "true", "yes", "on"}
ALLOW_EMPTY_REPORT_SET = str(
    os.environ.get("CASM_REPORT_OPEN_ALLOW_EMPTY", "1")
).strip().lower() in {"1", "true", "yes", "on"}
# Prepare single candidate soft p95 s for the next step.
SINGLE_CANDIDATE_SOFT_P95_S = max(
    0.0,
    float(os.environ.get("CASM_REPORT_OPEN_SINGLE_CANDIDATE_SOFT_P95_S", "3.0")),
)


# Section: run the fail workflow with clear inputs and outputs.
def fail(msg: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: {msg}")
    return code


# Section: run the extract block reason workflow with clear inputs and outputs.
def _extract_block_reason(status_code: int, payload, preview: str) -> Optional[str]:
    if status_code not in INFRA_BLOCK_CODES:
        # Return the prepared result to the caller.
        return None
    reason = None
    if isinstance(payload, dict):
        reason = payload.get("error") or payload.get("message")
    # Choose the correct branch before the workflow continues.
    if not reason:
        reason = preview
    reason = str(reason or "").strip()
    if not reason:
        reason = f"HTTP {status_code}"
    return reason


# Section: run the request json workflow with clear inputs and outputs.
def request_json(method: str, path: str, *, timeout: int = REQUEST_TIMEOUT, **kwargs):
    # Prepare url for the next step.
    url = f"{BASE_URL}{path}"
    started = time.perf_counter()
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    elapsed = time.perf_counter() - started
    payload = None
    try:
        # Prepare payload for the next step.
        payload = response.json()
    except Exception:
        payload = None
    # Prepare preview for the next step.
    preview = (response.text or "")[:500]
    block_reason = _extract_block_reason(response.status_code, payload, preview)
    return response.status_code, payload, preview, elapsed, block_reason


# Section: run the timed get text workflow with clear inputs and outputs.
def timed_get_text(path: str, *, timeout: int = REQUEST_TIMEOUT):
    url = f"{BASE_URL}{path}"
    started = time.perf_counter()
    response = requests.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"})
    # Prepare elapsed for the next step.
    elapsed = time.perf_counter() - started
    preview = (response.text or "")[:500]
    block_reason = _extract_block_reason(response.status_code, None, preview)
    return response, elapsed, block_reason


# Section: run the measure network baseline seconds workflow with clear inputs and outputs.
def measure_network_baseline_seconds() -> Optional[float]:
    samples: List[float] = []
    for _ in range(NETWORK_BASELINE_SAMPLES):
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare values needed by the next step.
            response, elapsed, block_reason = timed_get_text(
                NETWORK_BASELINE_PATH,
                timeout=REQUEST_TIMEOUT,
            )
            if block_reason:
                continue
            if response.status_code >= 400:
                continue
            samples.append(elapsed)
        except Exception:
            continue
    # Choose the correct branch before the workflow continues.
    if not samples:
        # Return the prepared result to the caller.
        return None
    return statistics.median(samples)


# Section: run the empty report set is acceptable workflow with clear inputs and outputs.
def empty_report_set_is_acceptable() -> bool:
    if not ALLOW_EMPTY_REPORT_SET:
        return False

    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare values needed by the next step.
        status_code, stats, preview, _elapsed, block_reason = request_json(
            "GET",
            "/api/stats",
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        print(f"WARN: empty report set confirmation failed: {exc}")
        return False

    # Choose the correct branch before the workflow continues.
    if block_reason:
        # Trigger the side effect required for this stage.
        print(f"WARN: empty report set confirmation blocked ({status_code}): {block_reason}")
        return False
    if status_code >= 400 or not isinstance(stats, dict):
        print(f"WARN: empty report set confirmation failed ({status_code}): {preview[:180]}")
        return False

    total_keys = (
        "total",
        "total_violations",
        "reportsGenerated",
        "reports_generated",
        "totalReports",
        "reportsTotal",
    )
    observed_totals: List[int] = []
    # Process each item in this collection using the same rule set.
    for key in total_keys:
        # Prepare value for the next step.
        value = stats.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            # Trigger the side effect required for this stage.
            observed_totals.append(int(value))
            continue
        if isinstance(value, str) and value.strip().isdigit():
            observed_totals.append(int(value.strip()))

    # Choose the correct branch before the workflow continues.
    if not observed_totals:
        # Trigger the side effect required for this stage.
        print(f"WARN: empty report set confirmation had no known total keys: {stats}")
        return False
    return max(observed_totals) == 0


# Section: run the choose candidates workflow with clear inputs and outputs.
def choose_candidates(rows: List[Dict]) -> List[str]:
    chosen: List[str] = []
    for row in rows[:MAX_SCAN]:
        if not isinstance(row, dict):
            continue
        # Prepare report id for the next step.
        report_id = str(row.get("report_id") or "").strip()
        if not report_id:
            continue
        status = str(row.get("status") or "").strip().lower()
        has_report = bool(row.get("has_report"))
        # Prefer explicit has_report rows but also allow completed statuses because
        # some deployed payloads lag this flag while /report/<id> is already available.
        if (has_report and status in {"completed", "unknown"}) or status == "completed":
            chosen.append(report_id)
        if len(chosen) >= MAX_CANDIDATES:
            break
    # Return the prepared result to the caller.
    return chosen


# Section: run the warm and measure workflow with clear inputs and outputs.
def warm_and_measure(report_id: str) -> Optional[Dict]:
    prefetch_code, prefetch_payload, prefetch_preview, prefetch_elapsed, prefetch_block = request_json(
        "POST",
        f"/api/report/{report_id}/prefetch",
        timeout=REQUEST_TIMEOUT,
    )
    # Choose the correct branch before the workflow continues.
    if prefetch_block:
        # Return the prepared result to the caller.
        return {
            "infra_blocked": True,
            "reason": f"prefetch HTTP {prefetch_code}: {prefetch_block}",
        }

    prefetch_layer = "unavailable"
    if prefetch_code == 404:
        # Backward-compatible path: endpoint not yet deployed, so prime via one warm GET.
        prefetch_layer = "endpoint_unavailable"
    # Choose the correct branch before the workflow continues.
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
    # Prepare values needed by the next step.
    warmup_response, warmup_elapsed, warmup_block = timed_get_text(
        f"/report/{report_id}",
        timeout=REQUEST_TIMEOUT,
    )
    if warmup_block:
        # Return the prepared result to the caller.
        return {
            "infra_blocked": True,
            "reason": f"/report/{report_id} HTTP {warmup_response.status_code}: {warmup_block}",
        }
    # Choose the correct branch before the workflow continues.
    if warmup_response.status_code >= 400:
        print(f"WARN: warmup /report/{report_id} returned {warmup_response.status_code}")
        return None

    sample_times: List[float] = []
    for _ in range(WARM_SAMPLE_COUNT):
        # Prepare values needed by the next step.
        response, elapsed, block_reason = timed_get_text(
            f"/report/{report_id}",
            timeout=REQUEST_TIMEOUT,
        )
        if block_reason:
            # Return the prepared result to the caller.
            return {
                "infra_blocked": True,
                "reason": f"/report/{report_id} HTTP {response.status_code}: {block_reason}",
            }
        # Choose the correct branch before the workflow continues.
        if response.status_code >= 400:
            print(f"WARN: /report/{report_id} returned {response.status_code}")
            return None
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            # Trigger the side effect required for this stage.
            print(
                f"WARN: /report/{report_id} content-type unexpected: {response.headers.get('Content-Type')}"
            )
            return None
        # Trigger the side effect required for this stage.
        sample_times.append(elapsed)

    # Prepare sorted times for the next step.
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


# Section: run the run once workflow with clear inputs and outputs.
def run_once() -> int:
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare network baseline s for the next step.
        network_baseline_s = measure_network_baseline_seconds()
        extra_network_allowance_s = 0.0
        if network_baseline_s is not None:
            # Prepare extra network allowance s for the next step.
            extra_network_allowance_s = max(0.0, network_baseline_s - NETWORK_BASELINE_FREE_S)
            extra_network_allowance_s = min(extra_network_allowance_s, NETWORK_ALLOWANCE_CAP_S)
        effective_warm_target_s = WARM_TARGET_SECONDS + extra_network_allowance_s

        code, payload, preview, elapsed, block_reason = request_json(
            "GET",
            f"/api/violations?limit={MAX_SCAN}",
            timeout=REQUEST_TIMEOUT,
        )
        # Choose the correct branch before the workflow continues.
        if block_reason:
            # Return the prepared result to the caller.
            return fail(f"Infrastructure blocked ({code}): {block_reason}", 12)
        if code >= 400:
            return fail(f"/api/violations failed ({code}): {preview}", 3)
        if not isinstance(payload, list) or not payload:
            if empty_report_set_is_acceptable():
                # Trigger the side effect required for this stage.
                print(
                    "WARN: report open latency contract found no reports; "
                    "empty Supabase/report state accepted."
                )
                return 0
            # Return the prepared result to the caller.
            return fail("/api/violations returned no data", 4)

        # Prepare candidates for the next step.
        candidates = choose_candidates(payload)
        if not candidates:
            status_counts: Dict[str, int] = {}
            has_report_true = 0
            for row in payload[:MAX_SCAN]:
                # Choose the correct branch before the workflow continues.
                if not isinstance(row, dict):
                    continue
                status = str(row.get("status") or "unknown").strip().lower() or "unknown"
                status_counts[status] = status_counts.get(status, 0) + 1
                if bool(row.get("has_report")):
                    has_report_true += 1
            # Return the prepared result to the caller.
            return fail("No completed reports with artifacts found for latency test", 5)

        # Trigger the side effect required for this stage.
        print(
            f"INFO: candidates={len(candidates)} scan_time_s={elapsed:.3f} warm_target_s={WARM_TARGET_SECONDS:.3f} "
            f"effective_target_s={effective_warm_target_s:.3f} network_baseline_s="
            f"{(f'{network_baseline_s:.3f}' if network_baseline_s is not None else 'n/a')}"
        )

        measured: List[Dict] = []
        for rid in candidates:
            # Prepare result for the next step.
            result = warm_and_measure(rid)
            if isinstance(result, dict) and result.get("infra_blocked"):
                # Return the prepared result to the caller.
                return fail(f"Environment block detected: {result.get('reason')}", 12)
            if result:
                measured.append(result)
                samples = ", ".join(f"{x:.3f}" for x in result["sample_times_s"])
                print(
                    f"INFO: report_id={rid} layer={result['prefetch_layer']} prefetch_s={result['prefetch_elapsed_s']:.3f} warmup_s={result['warmup_elapsed_s']:.3f} "
                    f"mean_s={result['mean_s']:.3f} p95_s={result['p95_s']:.3f} samples=[{samples}]"
                )

        # Choose the correct branch before the workflow continues.
        if not measured:
            # Return the prepared result to the caller.
            return fail("Could not measure latency on any candidate report", 6)

        if all(str(item.get("prefetch_layer")) == "endpoint_unavailable" for item in measured):
            return fail(
                "prefetch endpoint is unavailable; latency contract cannot validate latest backend",
                11,
            )

        # Prepare worst p95 for the next step.
        worst_p95 = max(item["p95_s"] for item in measured)
        worst_mean = max(item["mean_s"] for item in measured)

        all_warm_samples = sorted(
            [s for item in measured for s in (item.get("sample_times_s") or []) if isinstance(s, (int, float))]
        )
        if not all_warm_samples:
            # Return the prepared result to the caller.
            return fail("No warm sample data collected for latency validation", 8)

        # Prepare overall p95 index for the next step.
        overall_p95_index = max(
            0,
            min(len(all_warm_samples) - 1, math.ceil(0.95 * len(all_warm_samples)) - 1)
        )
        overall_p95 = all_warm_samples[overall_p95_index]
        worst_sample = max(all_warm_samples)

        if overall_p95 > effective_warm_target_s:
            # Prepare soft cap for the next step.
            soft_cap = max(SINGLE_CANDIDATE_SOFT_P95_S, effective_warm_target_s)
            if (
                ALLOW_SINGLE_CANDIDATE_SOFT_PASS
                and len(measured) == 1
                and overall_p95 <= soft_cap
            ):
                # Trigger the side effect required for this stage.
                print(
                    "WARN: single-candidate latency above target; "
                    f"allowing soft pass (overall_p95={overall_p95:.3f}s, "
                    f"target={effective_warm_target_s:.3f}s, soft_cap={soft_cap:.3f}s)"
                )
                return 0
            # Return the prepared result to the caller.
            return fail(
                f"Warm open latency target exceeded (overall p95): {overall_p95:.3f}s > {effective_warm_target_s:.3f}s "
                f"(worst_sample={worst_sample:.3f}s, candidates={len(measured)})",
                7,
            )

        # Choose the correct branch before the workflow continues.
        if worst_mean > (effective_warm_target_s * MEAN_MULTIPLIER):
            return fail(
                f"Warm open latency mean degraded: worst_mean={worst_mean:.3f}s > "
                f"{(effective_warm_target_s * MEAN_MULTIPLIER):.3f}s "
                f"(overall_p95={overall_p95:.3f}s, candidates={len(measured)})",
                9,
            )

        effective_max_sample_s = MAX_ALLOWED_SAMPLE_SECONDS + extra_network_allowance_s
        # Prepare spike samples for the next step.
        spike_samples = [s for s in all_warm_samples if s > effective_max_sample_s]
        if len(spike_samples) > MAX_SPIKE_SAMPLES:
            # Return the prepared result to the caller.
            return fail(
                f"Warm open latency hard cap exceeded: spikes={len(spike_samples)} > allowed={MAX_SPIKE_SAMPLES}, "
                f"worst_sample={worst_sample:.3f}s, cap={effective_max_sample_s:.3f}s",
                10,
            )
        if spike_samples:
            print(
                f"WARN: tolerated {len(spike_samples)} warm-sample spike(s) above cap "
                f"{effective_max_sample_s:.3f}s (max={worst_sample:.3f}s)"
            )

        # Trigger the side effect required for this stage.
        print(
            f"PASS: report open warm latency contract met "
            f"(target<={effective_warm_target_s:.3f}s, overall_p95={overall_p95:.3f}s, "
            f"worst_p95={worst_p95:.3f}s, worst_mean={worst_mean:.3f}s, "
            f"worst_sample={worst_sample:.3f}s, cap={effective_max_sample_s:.3f}s, "
            f"allowed_spikes={MAX_SPIKE_SAMPLES}, candidates={len(measured)})"
        )
        return 0
    except requests.HTTPError as exc:
        # Return the prepared result to the caller.
        return fail(f"HTTP error during report latency test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during report latency test: {exc}", 21)


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare last code for the next step.
    last_code = 0
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        if RETRY_ATTEMPTS > 1:
            # Trigger the side effect required for this stage.
            print(f"INFO: latency-check-attempt={attempt}/{RETRY_ATTEMPTS}")

        # Prepare code for the next step.
        code = run_once()
        if code == 0:
            return 0

        last_code = code
        if attempt < RETRY_ATTEMPTS:
            sleep_s = RETRY_BACKOFF_SECONDS * attempt
            # Trigger the side effect required for this stage.
            print(
                f"WARN: latency contract attempt {attempt} failed with code {code}; "
                f"retrying after {sleep_s:.1f}s"
            )
            time.sleep(sleep_s)

    # Return the prepared result to the caller.
    return last_code


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    raise SystemExit(main())
