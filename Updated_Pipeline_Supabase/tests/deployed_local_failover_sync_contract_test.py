import json
import os
from pathlib import Path
import sys

import requests


BASE_URL = os.environ.get(
    "CASM_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")
STRICT_LOCAL_FAILOVER_SYNC = os.environ.get("CASM_LOCAL_FAILOVER_SYNC_STRICT", "1") != "0"


REPO_ROOT = Path(__file__).resolve().parents[2]


def ensure_source_contracts() -> None:
    """Guard the local-to-cloud handoff path without consuming cloud/Gemini egress."""
    app_source = (REPO_ROOT / "Updated_Pipeline_Supabase" / "casm_app.py").read_text(encoding="utf-8")
    db_source = (
        REPO_ROOT
        / "Updated_Pipeline_Supabase"
        / "pipeline"
        / "backend"
        / "core"
        / "supabase_db.py"
    ).read_text(encoding="utf-8")
    report_generator_source = (
        REPO_ROOT
        / "Updated_Pipeline_Supabase"
        / "pipeline"
        / "backend"
        / "core"
        / "supabase_report_generator.py"
    ).read_text(encoding="utf-8")
    api_source = (
        REPO_ROOT / "Updated_Pipeline_Supabase" / "frontend" / "js" / "api.js"
    ).read_text(encoding="utf-8")
    app_js_source = (
        REPO_ROOT / "Updated_Pipeline_Supabase" / "frontend" / "js" / "app.js"
    ).read_text(encoding="utf-8")
    live_source = (
        REPO_ROOT / "Updated_Pipeline_Supabase" / "frontend" / "js" / "pages" / "live.js"
    ).read_text(encoding="utf-8")

    required_markers = {
        "backend partial handoff endpoint": "/api/reports/local-draft-handoff" in app_source,
        "backend partial sync marker": "sync_local_cache_partial" in app_source,
        "browser draft handoff marker": "browser_local_draft_handoff" in app_source,
        "handoff adoption timestamp": "cloud_adopt_after_epoch" in app_source,
        "cloud recovery adopts partial local handoffs": "sync_local_cache_partial" in db_source
        and "browser_local_draft_handoff" in db_source,
        "cloud generation updates pre-existing handoff row": "should_update_existing" in report_generator_source,
        "frontend IndexedDB draft handoff helper": "handoffLocalReportDraftsToCloud" in api_source,
        "adaptive reconnect invokes browser draft handoff": "handoffBrowserLocalDrafts" in app_js_source,
        "live drafts preserve detections for cloud continuation": "detections: Array.isArray(result.detections)" in live_source,
        "live notification is not blocked by draft persistence": "void API.upsertLocalReportDraft" in live_source,
    }
    missing = [name for name, ok in required_markers.items() if not ok]
    if missing:
        raise RuntimeError(f"source handoff contract missing markers: {missing}")



def fail(message: str, code: int = 2) -> int:
    print(f"FAIL: {message}")
    return code



def request_json(method: str, path: str, *, timeout: int = 40, **kwargs):
    url = f"{BASE_URL}{path}"
    resp = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    text_preview = (resp.text or "")[:500]
    payload = None
    try:
        payload = resp.json()
    except Exception:
        payload = None
    return resp.status_code, payload, text_preview



def ensure_dict(payload, context: str):
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context} expected JSON object payload")



def main() -> int:
    try:
        ensure_source_contracts()
        print("PASS: local partial handoff source contracts")

        code, startup, preview = request_json("GET", "/api/system/startup-status")
        if code >= 500:
            return fail(f"startup status failed with {code}: {preview}", 3)
        ensure_dict(startup, "startup-status")
        if "checks" not in startup:
            return fail("startup-status missing checks object", 4)
        print("PASS: startup-status endpoint reachable")

        code, options, preview = request_json("GET", "/api/reports/recovery/options")
        if code >= 400:
            return fail(f"recovery-options failed with {code}: {preview}", 5)
        ensure_dict(options, "recovery-options")
        if options.get("success") is False:
            return fail(f"recovery-options returned success=false: {json.dumps(options)[:350]}", 6)
        if "local" not in options or "counts" not in options:
            return fail("recovery-options missing local/counts fields", 7)
        print("PASS: recovery-options endpoint contract")

        code, sync_payload, preview = request_json(
            "POST",
            "/api/reports/sync-local-cache",
            json={"limit": 40, "dry_run": True},
        )
        if code == 404 and not STRICT_LOCAL_FAILOVER_SYNC:
            print(
                "WARN: sync-local-cache endpoint not deployed yet (404); "
                "treating as non-blocking by default "
                "(set CASM_LOCAL_FAILOVER_SYNC_STRICT=1 to enforce)"
            )
            print("PASS: deployed local failover/sync contracts (non-blocking mode)")
            return 0

        if code >= 400:
            return fail(f"sync-local-cache dry-run failed with {code}: {preview}", 8)
        ensure_dict(sync_payload, "sync-local-cache")

        required_keys = ["success", "dry_run", "scanned", "candidates", "enqueued", "skipped", "errors", "worker_running"]
        missing = [k for k in required_keys if k not in sync_payload]
        if missing:
            return fail(f"sync-local-cache response missing keys: {missing}", 9)

        if sync_payload.get("success") is False:
            return fail(f"sync-local-cache returned success=false: {json.dumps(sync_payload)[:350]}", 10)

        if sync_payload.get("dry_run") is not True:
            return fail("sync-local-cache did not honor dry_run=true", 11)

        scanned = int(sync_payload.get("scanned", 0) or 0)
        candidates = int(sync_payload.get("candidates", 0) or 0)
        enqueued = int(sync_payload.get("enqueued", 0) or 0)

        if scanned < 0 or candidates < 0 or enqueued < 0:
            return fail("sync-local-cache returned negative counters", 12)

        if enqueued != 0:
            return fail("sync-local-cache dry_run unexpectedly enqueued items", 13)

        print(
            "PASS: sync-local-cache dry-run contract "
            f"(scanned={scanned}, candidates={candidates}, enqueued={enqueued})"
        )

        print("PASS: deployed local failover/sync contracts")
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error: {exc}", 21)


if __name__ == "__main__":
    sys.exit(main())
