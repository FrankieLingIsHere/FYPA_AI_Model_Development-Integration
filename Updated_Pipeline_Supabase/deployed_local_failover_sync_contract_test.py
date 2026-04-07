import json
import os
import sys

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")



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
