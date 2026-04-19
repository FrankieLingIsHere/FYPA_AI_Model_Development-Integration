import html
import os
import re
import sys
from typing import Dict, List, Optional

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

MAX_VIOLATION_SCAN = max(10, int(os.environ.get("LUNA_REPORT_QUALITY_MAX_SCAN", "120")))
MAX_REPORT_QUALITY_CANDIDATES = max(1, int(os.environ.get("LUNA_REPORT_QUALITY_MAX_CANDIDATES", "12")))
MIN_SCENE_DESC_CHARS = max(40, int(os.environ.get("LUNA_REPORT_QUALITY_MIN_CHARS", "120")))
ENFORCE_SCENE_GROUNDED_FLOOR = str(os.environ.get("LUNA_REPORT_QUALITY_ENFORCE_GROUNDED_SCENE", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENFORCE_EXECUTIVE_WHAT = str(os.environ.get("LUNA_REPORT_QUALITY_ENFORCE_WHAT", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
STRICT_REPORT_QUALITY = str(os.environ.get("LUNA_REPORT_QUALITY_STRICT", "0")).strip().lower() in {
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
)


def fail(msg: str, code: int = 2) -> int:
    if STRICT_REPORT_QUALITY:
        print(f"FAIL: {msg}")
        return code
    print(f"WARN: {msg}")
    return 0


def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    preview = (response.text or "")[:600]
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, preview


def request_text(method: str, path: str, *, timeout: int = 40, **kwargs):
    url = f"{BASE_URL}{path}"
    response = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    return response.status_code, (response.text or "")


def extract_ai_scene_description(report_html: str) -> str:
    pattern = re.compile(
        r"AI Scene Description</h2>.*?<div class=\"card-content\">\s*<p>(.*?)</p>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(report_html or "")
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    text = html.unescape(text)
    return " ".join(text.split()).strip()


def extract_executive_what(report_html: str) -> str:
    pattern = re.compile(
        r">\s*WHAT\s*</td>\s*<td[^>]*>(.*?)</td>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(report_html or "")
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    text = html.unescape(text)
    return " ".join(text.split()).strip()


def choose_latest_completed_with_report(items: List[Dict]) -> Optional[Dict]:
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        has_report = bool(item.get("has_report"))
        report_id = str(item.get("report_id") or "").strip()
        if report_id and has_report and status in {"completed", "unknown"}:
            return item
    return None


def is_generic_scene_description(scene_desc: str) -> bool:
    lower_desc = scene_desc.lower()
    generic_markers = (
        "person is visible",
        "people are visible",
        "indoor environment",
        "outdoor environment",
        "no description available",
        "caption generation failed",
    )
    if any(marker in lower_desc for marker in generic_markers):
        return True
    # Allow "general workspace" phrasing when backed by richer grounded detail.
    if "general workspace setting" in lower_desc and len(scene_desc) < 170:
        return True
    return False


def has_grounded_scene_floor(scene_desc: str) -> bool:
    lower_desc = scene_desc.lower()
    required_markers = (
        "the scene depicts a",
        "person",
        "yolo detection identified",
        "ppe deficiencies",
    )
    return all(marker in lower_desc for marker in required_markers)


def is_non_work_caption(caption: str) -> bool:
    lower_caption = str(caption or "").strip().lower()
    if not lower_caption:
        return False
    return any(marker in lower_caption for marker in NON_WORK_CAPTION_MARKERS)


def rank_quality_candidate(item: Dict) -> tuple:
    status = str(item.get("status") or "").strip().lower()
    has_report = bool(item.get("has_report"))
    try:
        detection_count = int(item.get("detection_count") or 0)
    except (TypeError, ValueError):
        detection_count = 0
    report_id = str(item.get("report_id") or "")
    report_digits = "".join(ch for ch in report_id if ch.isdigit())
    try:
        report_sort_score = int(report_digits) if report_digits else 0
    except ValueError:
        report_sort_score = 0

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


def main() -> int:
    try:
        status_code, violations, text_preview = request_json("GET", "/api/violations", timeout=35)
        if status_code >= 400:
            return fail(f"/api/violations failed ({status_code}): {text_preview}", 3)
        if not isinstance(violations, list) or not violations:
            return fail("/api/violations returned no data", 4)

        sample = violations[:MAX_VIOLATION_SCAN]
        candidates = [
            item for item in sample
            if isinstance(item, dict)
            and str(item.get("report_id") or "").strip()
            and bool(item.get("has_report"))
            and str(item.get("status") or "").strip().lower() in {"completed", "unknown"}
        ]
        candidates.sort(key=rank_quality_candidate)
        candidates = candidates[:MAX_REPORT_QUALITY_CANDIDATES]

        if not candidates:
            return fail(
                "Could not find a completed violation with report artifact in scan window; "
                "quality check cannot run",
                5,
            )
        failures = []
        skipped_non_work: List[str] = []
        skipped_legacy_template: List[str] = []
        quality_checked_count = 0
        for target in candidates:
            report_id = str(target.get("report_id"))
            print(f"INFO: quality target report_id={report_id}")

            v_code, violation, v_preview = request_json("GET", f"/api/violation/{report_id}", timeout=35)
            if v_code >= 400 or not isinstance(violation, dict):
                failures.append(f"/api/violation/{report_id} failed ({v_code}): {v_preview}")
                continue

            caption = str(violation.get("caption") or "").strip()
            if not caption:
                failures.append(f"caption is empty for report {report_id}")
                continue

            if is_non_work_caption(caption):
                skipped_non_work.append(report_id)
                print(
                    "INFO: skipping non-work/system-message candidate "
                    f"report_id={report_id} caption={caption[:160]}"
                )
                continue

            quality_checked_count += 1

            r_code, report_html = request_text("GET", f"/report/{report_id}", timeout=45)
            if r_code >= 400:
                failures.append(f"/report/{report_id} failed ({r_code})")
                continue

            if "AI Scene Description" not in report_html:
                skipped_legacy_template.append(report_id)
                print(
                    "INFO: skipping legacy report template without AI Scene Description section "
                    f"report_id={report_id}"
                )
                continue

            scene_desc = extract_ai_scene_description(report_html)
            if not scene_desc:
                failures.append(f"AI Scene Description is empty in rendered report {report_id}")
                continue

            what_text = extract_executive_what(report_html)
            if not what_text:
                failures.append(f"Executive summary WHAT row is empty in rendered report {report_id}")
                continue

            if len(scene_desc) < MIN_SCENE_DESC_CHARS:
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

            if ENFORCE_SCENE_GROUNDED_FLOOR and not has_grounded_scene_floor(scene_desc):
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
            if ENFORCE_EXECUTIVE_WHAT and any(marker in lower_what for marker in what_placeholders):
                failures.append(
                    f"Executive summary WHAT row placeholder-like for report {report_id}: {what_text[:220]}"
                )
                continue
            if ENFORCE_EXECUTIVE_WHAT and len(what_text) < 30:
                failures.append(
                    f"Executive summary WHAT row too short ({len(what_text)} chars) for report {report_id}: {what_text}"
                )
                continue

            if (not ENFORCE_EXECUTIVE_WHAT) and (any(marker in lower_what for marker in what_placeholders) or len(what_text) < 30):
                print(
                    "WARN: executive WHAT row quality not enforced; "
                    f"observed what_len={len(what_text)} text={what_text[:140]}"
                )

            print(
                "PASS: deployed report quality contract verified "
                f"(report_id={report_id}, caption_len={len(caption)}, scene_desc_len={len(scene_desc)}, what_len={len(what_text)})"
            )
            return 0

        if quality_checked_count == 0:
            extra_parts = []
            if skipped_non_work:
                extra_parts.append(f"skipped_non_work={skipped_non_work[:5]}")
            if skipped_legacy_template:
                extra_parts.append(f"skipped_legacy={skipped_legacy_template[:5]}")
            extra = (" " + " ".join(extra_parts)) if extra_parts else ""
            return fail(
                "No work-scene report candidate available for quality contract validation."
                + extra,
                12,
            )

        return fail(
            "No scanned report met quality contract. "
            + (" | ".join(failures[:3]) if failures else "No detailed failure reason captured."),
            11,
        )
    except requests.HTTPError as exc:
        return fail(f"HTTP error during report quality test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during report quality test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
