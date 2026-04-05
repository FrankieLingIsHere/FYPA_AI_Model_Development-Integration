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
MIN_SCENE_DESC_CHARS = max(40, int(os.environ.get("LUNA_REPORT_QUALITY_MIN_CHARS", "90")))


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


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


def main() -> int:
    try:
        status_code, violations, text_preview = request_json("GET", "/api/violations", timeout=35)
        if status_code >= 400:
            return fail(f"/api/violations failed ({status_code}): {text_preview}", 3)
        if not isinstance(violations, list) or not violations:
            return fail("/api/violations returned no data", 4)

        sample = violations[:MAX_VIOLATION_SCAN]
        target = choose_latest_completed_with_report(sample)
        if not target:
            return fail(
                "Could not find a completed violation with report artifact in scan window; "
                "quality check cannot run",
                5,
            )

        report_id = str(target.get("report_id"))
        print(f"INFO: quality target report_id={report_id}")

        v_code, violation, v_preview = request_json("GET", f"/api/violation/{report_id}", timeout=35)
        if v_code >= 400 or not isinstance(violation, dict):
            return fail(f"/api/violation/{report_id} failed ({v_code}): {v_preview}", 6)

        caption = str(violation.get("caption") or "").strip()
        if not caption:
            return fail(f"caption is empty for report {report_id}", 7)

        r_code, report_html = request_text("GET", f"/report/{report_id}", timeout=45)
        if r_code >= 400:
            return fail(f"/report/{report_id} failed ({r_code})", 8)

        scene_desc = extract_ai_scene_description(report_html)
        if not scene_desc:
            return fail(f"AI Scene Description is empty in rendered report {report_id}", 9)

        lower_desc = scene_desc.lower()
        generic_markers = (
            "person is visible",
            "people are visible",
            "indoor environment",
            "outdoor environment",
            "no description available",
            "caption generation failed",
        )

        if len(scene_desc) < MIN_SCENE_DESC_CHARS:
            return fail(
                f"AI Scene Description too short ({len(scene_desc)} chars < {MIN_SCENE_DESC_CHARS}) "
                f"for report {report_id}: {scene_desc[:180]}",
                10,
            )

        if any(marker in lower_desc for marker in generic_markers):
            return fail(
                f"AI Scene Description still generic/placeholder for report {report_id}: {scene_desc[:220]}",
                11,
            )

        print(
            "PASS: deployed report quality contract verified "
            f"(report_id={report_id}, caption_len={len(caption)}, scene_desc_len={len(scene_desc)})"
        )
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during report quality test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error during report quality test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
