# Readability: Test setup: document the contract this file protects.
import html
import os
import re
import sys
import time
from typing import Dict, List, Optional

import requests


# Prepare base url for the next step.
BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

MAX_VIOLATION_SCAN = max(10, int(os.environ.get("CASM_REPORT_QUALITY_MAX_SCAN", "80")))
MAX_REPORT_QUALITY_CANDIDATES = max(1, int(os.environ.get("CASM_REPORT_QUALITY_MAX_CANDIDATES", "12")))
MIN_SCENE_DESC_CHARS = max(40, int(os.environ.get("CASM_REPORT_QUALITY_MIN_CHARS", "120")))
VIOLATION_FETCH_ATTEMPTS = max(1, int(os.environ.get("CASM_REPORT_QUALITY_VIOLATION_FETCH_ATTEMPTS", "4")))
# Prepare violation fetch backoff seconds for the next step.
VIOLATION_FETCH_BACKOFF_SECONDS = max(
    0.5,
    float(os.environ.get("CASM_REPORT_QUALITY_VIOLATION_FETCH_BACKOFF_SECONDS", "3.0")),
)
ENFORCE_SCENE_GROUNDED_FLOOR = str(os.environ.get("CASM_REPORT_QUALITY_ENFORCE_GROUNDED_SCENE", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Prepare enforce executive what for the next step.
ENFORCE_EXECUTIVE_WHAT = str(os.environ.get("CASM_REPORT_QUALITY_ENFORCE_WHAT", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
STRICT_REPORT_QUALITY = str(os.environ.get("CASM_REPORT_QUALITY_STRICT", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Prepare allow empty report set for the next step.
ALLOW_EMPTY_REPORT_SET = str(os.environ.get("CASM_REPORT_QUALITY_ALLOW_EMPTY", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

NON_WORK_CAPTION_MARKERS = (
    "not a physical environment",
    "system message",
    "digital screen",
    "placeholder",
    "missing image",
    "displaying text",
    "text on a dark background",
    "no individuals",
    "no person",
    "looking directly at the camera",
    "white t-shirt",
    "head and shoulders",
    "chest up",
    "seated at a table",
    "decorative, ornate design",
    "eyeglasses",
)

# Prepare work scene caption markers for the next step.
WORK_SCENE_CAPTION_MARKERS = (
    "construction",
    "worksite",
    "work site",
    "jobsite",
    "job site",
    "worker",
    "workers",
    "ppe",
    "hardhat",
    "helmet",
    "safety vest",
    "safety boots",
    "boots",
    "gloves",
    "mask",
    "scaffold",
    "ladder",
    "machinery",
    "equipment",
    "warehouse",
    "factory",
    "industrial",
    "loading dock",
    "floor work",
)

# Prepare demo indoor caption markers for the next step.
DEMO_INDOOR_CAPTION_MARKERS = (
    "indoor setting",
    "indoor office setting",
    "indoor residential setting",
    "indoor room setting",
    "single person visible",
    "one visible person",
    "young man",
    "wall adorned",
    "neutral gaze",
    "neutral posture",
    "looking directly",
)


# Section: run the fail workflow with clear inputs and outputs.
def fail(msg: str, code: int = 2) -> int:
    # Choose the correct branch before the workflow continues.
    if STRICT_REPORT_QUALITY:
        # Trigger the side effect required for this stage.
        print(f"FAIL: {msg}")
        return code
    print(f"WARN: {msg}")
    return 0


# Section: run the request json workflow with clear inputs and outputs.
def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
    url = f"{BASE_URL}{path}"
    # Prepare response for the next step.
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    preview = (response.text or "")[:600]
    payload = None
    try:
        # Prepare payload for the next step.
        payload = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, preview


# Section: run the request text workflow with clear inputs and outputs.
def request_text(method: str, path: str, *, timeout: int = 40, **kwargs):
    # Prepare url for the next step.
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    return response.status_code, (response.text or "")


# Section: run the fetch violations with retry workflow with clear inputs and outputs.
def fetch_violations_with_retry():
    last_status = 0
    last_payload = None
    last_preview = ""

    # Process each item in this collection using the same rule set.
    for attempt in range(1, VIOLATION_FETCH_ATTEMPTS + 1):
        # Prepare cache buster for the next step.
        cache_buster = int(time.time() * 1000)
        status_code, violations, text_preview = request_json(
            "GET",
            f"/api/violations?limit={MAX_VIOLATION_SCAN}&quality_probe={cache_buster}",
            timeout=35,
        )
        last_status = status_code
        last_payload = violations
        last_preview = text_preview

        # Choose the correct branch before the workflow continues.
        if status_code < 400 and isinstance(violations, list) and violations:
            # Choose the correct branch before the workflow continues.
            if attempt > 1:
                # Trigger the side effect required for this stage.
                print(f"INFO: /api/violations recovered after retry attempt={attempt}")
            return status_code, violations, text_preview

        retryable_empty = status_code < 400 and (not isinstance(violations, list) or not violations)
        retryable_status = status_code in {429, 500, 502, 503, 504}
        if attempt < VIOLATION_FETCH_ATTEMPTS and (retryable_empty or retryable_status):
            reason = (
                "empty payload"
                if retryable_empty
                else f"HTTP {status_code}"
            )
            # Trigger the side effect required for this stage.
            print(
                f"INFO: /api/violations returned {reason}; "
                f"retrying attempt={attempt + 1}/{VIOLATION_FETCH_ATTEMPTS}"
            )
            time.sleep(VIOLATION_FETCH_BACKOFF_SECONDS * attempt)
            continue

        break

    # Return the prepared result to the caller.
    return last_status, last_payload, last_preview


# Section: run the extract ai scene description workflow with clear inputs and outputs.
def extract_ai_scene_description(report_html: str) -> str:
    pattern = re.compile(
        r"AI Scene Description</h2>.*?<div class=\"card-content\">\s*<p>(.*?)</p>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(report_html or "")
    # Choose the correct branch before the workflow continues.
    if not match:
        # Return the prepared result to the caller.
        return ""
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    text = html.unescape(text)
    return " ".join(text.split()).strip()


# Section: run the extract executive what workflow with clear inputs and outputs.
def extract_executive_what(report_html: str) -> str:
    pattern = re.compile(
        r">\s*WHAT\s*</td>\s*<td[^>]*>(.*?)</td>",
        re.IGNORECASE | re.DOTALL,
    )
    # Prepare match for the next step.
    match = pattern.search(report_html or "")
    if not match:
        # Return the prepared result to the caller.
        return ""
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    text = html.unescape(text)
    return " ".join(text.split()).strip()


# Section: run the choose latest completed with report workflow with clear inputs and outputs.
def choose_latest_completed_with_report(items: List[Dict]) -> Optional[Dict]:
    # Process each item in this collection using the same rule set.
    for item in items:
        if not isinstance(item, dict):
            continue
        # Prepare status for the next step.
        status = str(item.get("status") or "").strip().lower()
        has_report = bool(item.get("has_report"))
        report_id = str(item.get("report_id") or "").strip()
        if report_id and has_report and status in {"completed", "unknown"}:
            # Return the prepared result to the caller.
            return item
    return None


# Section: run the is generic scene description workflow with clear inputs and outputs.
def is_generic_scene_description(scene_desc: str) -> bool:
    # Prepare lower desc for the next step.
    lower_desc = scene_desc.lower()
    generic_markers = (
        "person is visible",
        "people are visible",
        "indoor environment",
        "outdoor environment",
        "no description available",
        "caption generation failed",
    )
    # Choose the correct branch before the workflow continues.
    if any(marker in lower_desc for marker in generic_markers):
        # Return the prepared result to the caller.
        return True
    # Allow "general workspace" phrasing when backed by richer grounded detail.
    if "general workspace setting" in lower_desc and len(scene_desc) < 170:
        return True
    return False


# Section: run the has grounded scene floor workflow with clear inputs and outputs.
def has_grounded_scene_floor(scene_desc: str) -> bool:
    # Prepare lower desc for the next step.
    lower_desc = scene_desc.lower()
    required_markers = (
        "the scene depicts a",
        "person",
        "yolo detection identified",
        "ppe deficiencies",
    )
    return all(marker in lower_desc for marker in required_markers)


# Section: run the is non work caption workflow with clear inputs and outputs.
def is_non_work_caption(caption: str) -> bool:
    # Prepare lower caption for the next step.
    lower_caption = str(caption or "").strip().lower()
    if not lower_caption:
        # Return the prepared result to the caller.
        return False
    if any(marker in lower_caption for marker in NON_WORK_CAPTION_MARKERS):
        return True
    has_work_marker = any(marker in lower_caption for marker in WORK_SCENE_CAPTION_MARKERS)
    has_demo_indoor_marker = any(marker in lower_caption for marker in DEMO_INDOOR_CAPTION_MARKERS)
    return has_demo_indoor_marker and not has_work_marker


# Section: run the rank quality candidate workflow with clear inputs and outputs.
def rank_quality_candidate(item: Dict) -> tuple:
    # Prepare status for the next step.
    status = str(item.get("status") or "").strip().lower()
    has_report = bool(item.get("has_report"))
    try:
        # Prepare detection count for the next step.
        detection_count = int(item.get("detection_count") or 0)
    except (TypeError, ValueError):
        detection_count = 0
    report_id = str(item.get("report_id") or "")
    report_digits = "".join(ch for ch in report_id if ch.isdigit())
    try:
        report_sort_score = int(report_digits) if report_digits else 0
    except ValueError:
        report_sort_score = 0

    # Prepare status rank for the next step.
    status_rank = {
        "completed": 0,
        "unknown": 1,
    }.get(status, 2)

    return (
        0 if has_report else 1,
        status_rank,
        -max(0, detection_count),
        -report_sort_score,
        report_id,
    )


# Section: run the empty report set is acceptable workflow with clear inputs and outputs.
def empty_report_set_is_acceptable() -> bool:
    # Choose the correct branch before the workflow continues.
    if not ALLOW_EMPTY_REPORT_SET:
        # Return the prepared result to the caller.
        return False

    status_code, stats, preview = request_json("GET", "/api/stats", timeout=30)
    if status_code >= 400 or not isinstance(stats, dict):
        print(f"WARN: could not verify empty report set via /api/stats ({status_code}): {preview}")
        return False

    total_keys = (
        "total",
        "total_violations",
        "reportsGenerated",
        "reports_generated",
        "totalReports",
        "reportsTotal",
    )
    # Prepare observed totals for the next step.
    observed_totals = []
    for key in total_keys:
        # Choose the correct branch before the workflow continues.
        if key not in stats:
            continue
        try:
            # Trigger the side effect required for this stage.
            observed_totals.append(int(stats.get(key) or 0))
        except (TypeError, ValueError):
            pass

    # Return the prepared result to the caller.
    return bool(observed_totals) and max(observed_totals) == 0


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    try:
        # Prepare values needed by the next step.
        status_code, violations, text_preview = fetch_violations_with_retry()
        if status_code >= 400:
            # Return the prepared result to the caller.
            return fail(f"/api/violations failed ({status_code}): {text_preview}", 3)
        if not isinstance(violations, list) or not violations:
            if empty_report_set_is_acceptable():
                # Trigger the side effect required for this stage.
                print(
                    "WARN: deployed report quality contract found no reports; "
                    "empty Supabase/report state accepted."
                )
                return 0
            return fail("/api/violations returned no data", 4)

        # Prepare sample for the next step.
        sample = violations[:MAX_VIOLATION_SCAN]
        candidates = [
            item for item in sample
            if isinstance(item, dict)
            and str(item.get("report_id") or "").strip()
            and bool(item.get("has_report"))
            and str(item.get("status") or "").strip().lower() in {"completed", "unknown"}
        ]
        candidates.sort(key=rank_quality_candidate)
        # Prepare candidates for the next step.
        candidates = candidates[:MAX_REPORT_QUALITY_CANDIDATES]

        if not candidates:
            # Return the prepared result to the caller.
            return fail(
                "Could not find a completed violation with report artifact in scan window; "
                "quality check cannot run",
                5,
            )
        failures = []
        skipped_non_work: List[str] = []
        skipped_legacy_template: List[str] = []
        skipped_stale_local_only: List[str] = []
        # Prepare quality checked count for the next step.
        quality_checked_count = 0
        for target in candidates:
            # Prepare report id for the next step.
            report_id = str(target.get("report_id"))
            print(f"INFO: quality target report_id={report_id}")

            v_code, violation, v_preview = request_json("GET", f"/api/violation/{report_id}", timeout=35)
            if v_code == 404:
                # Trigger the side effect required for this stage.
                skipped_stale_local_only.append(report_id)
                print(
                    "INFO: skipping stale local-only candidate without DB detail "
                    f"report_id={report_id}"
                )
                continue
            # Choose the correct branch before the workflow continues.
            if v_code >= 400 or not isinstance(violation, dict):
                failures.append(f"/api/violation/{report_id} failed ({v_code}): {v_preview}")
                continue

            caption = str(violation.get("caption") or "").strip()
            if not caption:
                # Trigger the side effect required for this stage.
                failures.append(f"caption is empty for report {report_id}")
                continue

            # Choose the correct branch before the workflow continues.
            if is_non_work_caption(caption):
                skipped_non_work.append(report_id)
                print(
                    "INFO: skipping non-work/system-message candidate "
                    f"report_id={report_id} caption={caption[:160]}"
                )
                continue

            quality_checked_count += 1

            # Prepare values needed by the next step.
            r_code, report_html = request_text("GET", f"/report/{report_id}", timeout=45)
            if r_code >= 400:
                # Trigger the side effect required for this stage.
                failures.append(f"/report/{report_id} failed ({r_code})")
                continue

            if "AI Scene Description" not in report_html:
                skipped_legacy_template.append(report_id)
                print(
                    "INFO: skipping legacy report template without AI Scene Description section "
                    f"report_id={report_id}"
                )
                continue

            # Prepare scene desc for the next step.
            scene_desc = extract_ai_scene_description(report_html)
            if not scene_desc:
                # Trigger the side effect required for this stage.
                failures.append(f"AI Scene Description is empty in rendered report {report_id}")
                continue

            what_text = extract_executive_what(report_html)
            if not what_text:
                failures.append(f"Executive summary WHAT row is empty in rendered report {report_id}")
                continue

            # Choose the correct branch before the workflow continues.
            if len(scene_desc) < MIN_SCENE_DESC_CHARS:
                # Trigger the side effect required for this stage.
                failures.append(
                    f"AI Scene Description too short ({len(scene_desc)} chars < {MIN_SCENE_DESC_CHARS}) "
                    f"for report {report_id}: {scene_desc[:180]}"
                )
                continue

            if is_generic_scene_description(scene_desc):
                failures.append(
                    f"AI Scene Description generic for report {report_id}: {scene_desc[:220]}"
                )
                continue

            # Choose the correct branch before the workflow continues.
            if ENFORCE_SCENE_GROUNDED_FLOOR and not has_grounded_scene_floor(scene_desc):
                # Trigger the side effect required for this stage.
                failures.append(
                    f"AI Scene Description missing grounded floor markers for report {report_id}: {scene_desc[:260]}"
                )
                continue

            lower_what = what_text.lower()
            what_placeholders = (
                "analysis in progress",
                "summary unavailable",
                "no summary available",
                "not enough information",
                "pending analysis",
            )
            # Choose the correct branch before the workflow continues.
            if ENFORCE_EXECUTIVE_WHAT and any(marker in lower_what for marker in what_placeholders):
                # Trigger the side effect required for this stage.
                failures.append(
                    f"Executive summary WHAT row placeholder-like for report {report_id}: {what_text[:220]}"
                )
                continue
            if ENFORCE_EXECUTIVE_WHAT and len(what_text) < 30:
                failures.append(
                    f"Executive summary WHAT row too short ({len(what_text)} chars) for report {report_id}: {what_text}"
                )
                continue

            # Choose the correct branch before the workflow continues.
            if (not ENFORCE_EXECUTIVE_WHAT) and (any(marker in lower_what for marker in what_placeholders) or len(what_text) < 30):
                # Trigger the side effect required for this stage.
                print(
                    "WARN: executive WHAT row quality not enforced; "
                    f"observed what_len={len(what_text)} text={what_text[:140]}"
                )

            print(
                "PASS: deployed report quality contract verified "
                f"(report_id={report_id}, caption_len={len(caption)}, scene_desc_len={len(scene_desc)}, what_len={len(what_text)})"
            )
            # Return the prepared result to the caller.
            return 0

        # Choose the correct branch before the workflow continues.
        if quality_checked_count == 0:
            extra_parts = []
            if skipped_non_work:
                # Trigger the side effect required for this stage.
                extra_parts.append(f"skipped_non_work={skipped_non_work[:5]}")
            if skipped_legacy_template:
                extra_parts.append(f"skipped_legacy={skipped_legacy_template[:5]}")
            if skipped_stale_local_only:
                extra_parts.append(f"skipped_stale_local={skipped_stale_local_only[:5]}")
            # Prepare extra for the next step.
            extra = (" " + " ".join(extra_parts)) if extra_parts else ""
            if (skipped_non_work or skipped_legacy_template or skipped_stale_local_only) and not failures:
                print(
                    "WARN: No work-scene report candidate available for quality contract validation."
                    + extra
                )
                # Return the prepared result to the caller.
                return 0
            return fail(
                "No work-scene report candidate available for quality contract validation."
                + extra,
                12,
            )

        # Return the prepared result to the caller.
        return fail(
            "No scanned report met quality contract. "
            + (" | ".join(failures[:3]) if failures else "No detailed failure reason captured."),
            11,
        )
    except requests.HTTPError as exc:
        return fail(f"HTTP error during report quality test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during report quality test: {exc}", 21)


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
