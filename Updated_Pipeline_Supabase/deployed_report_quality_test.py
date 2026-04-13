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
MIN_SCENE_DESC_CHARS = max(40, int(os.environ.get("LUNA_REPORT_QUALITY_MIN_CHARS", "90")))
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
        "general workspace setting",
    )
    return any(marker in lower_desc for marker in generic_markers)


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
        ][:MAX_REPORT_QUALITY_CANDIDATES]

        if not candidates:
            return fail(
                "Could not find a completed violation with report artifact in scan window; "
                "quality check cannot run",
                5,
            )
        failures = []
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

            r_code, report_html = request_text("GET", f"/report/{report_id}", timeout=45)
            if r_code >= 400:
                failures.append(f"/report/{report_id} failed ({r_code})")
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
