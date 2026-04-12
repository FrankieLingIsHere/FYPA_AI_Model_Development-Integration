import json
import os
import re
import sys
import time

import requests


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

DEFAULT_RAILWAY_URL = "https://fypaaimodeldevelopment-integration-production.up.railway.app"
RAILWAY_URL = os.environ.get("LUNA_BASE_URL", "").rstrip("/")
STARTUP_WAIT_SECONDS = int(os.environ.get("LUNA_STARTUP_WAIT_SECONDS", "180"))
STARTUP_POLL_INTERVAL_SECONDS = int(os.environ.get("LUNA_STARTUP_POLL_INTERVAL_SECONDS", "6"))
QUEUE_WAIT_SECONDS = int(os.environ.get("LUNA_QUEUE_WAIT_SECONDS", "90"))
QUEUE_POLL_INTERVAL_SECONDS = int(os.environ.get("LUNA_QUEUE_POLL_INTERVAL_SECONDS", "6"))


def fail(msg: str, code: int = 2) -> int:
    print(f"FAIL: {msg}")
    return code


def get_json(url: str, timeout: int = 30):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except Exception as exc:
        raise RuntimeError(f"Expected JSON from {url}, got: {r.text[:220]}") from exc


def parse_runtime_api_base(js_text: str) -> str:
    match = re.search(r"API_BASE_URL\s*:\s*'([^']+)'", js_text)
    if not match:
        match = re.search(r'API_BASE_URL\s*:\s*"([^"]+)"', js_text)
    return (match.group(1).strip() if match else "")


def is_placeholder_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return (not text) or ("your-backend" in text) or text.endswith("example.com")


def wait_for_startup_ready(api_base: str):
    deadline = time.time() + max(STARTUP_WAIT_SECONDS, 0)
    last_payload = None
    while True:
        try:
            payload = get_json(f"{api_base}/api/system/startup-status")
            last_payload = payload
            ready = isinstance(payload, dict) and bool(payload.get("ready"))
            progress = payload.get("progress") if isinstance(payload, dict) else None
            message = payload.get("message") if isinstance(payload, dict) else None
            print(f"INFO: startup poll ready={ready} progress={progress} message={message}")
            if ready:
                return payload
        except Exception as exc:
            print(f"INFO: startup poll error: {exc}")

        if time.time() >= deadline:
            break
        time.sleep(max(1, STARTUP_POLL_INTERVAL_SECONDS))

    return last_payload


def wait_for_queue_healthy(api_base: str):
    deadline = time.time() + max(QUEUE_WAIT_SECONDS, 0)
    last_payload = None
    while True:
        try:
            payload = get_json(f"{api_base}/api/queue/status")
            last_payload = payload
            available = isinstance(payload, dict) and bool(payload.get("available"))
            worker_running = isinstance(payload, dict) and bool(payload.get("worker_running"))
            print(f"INFO: queue poll available={available} worker_running={worker_running}")
            if available and worker_running:
                return payload
        except Exception as exc:
            print(f"INFO: queue poll error: {exc}")

        if time.time() >= deadline:
            break
        time.sleep(max(1, QUEUE_POLL_INTERVAL_SECONDS))

    return last_payload


def main() -> int:
    try:
        home = requests.get(f"{VERCEL_URL}/", timeout=30)
        home.raise_for_status()
        if "PPE Safety Monitor" not in home.text:
            return fail("Vercel homepage loaded but expected app title text is missing", 3)
        print("PASS: Vercel homepage reachable")

        runtime_cfg = requests.get(f"{VERCEL_URL}/js/runtime-config.js", timeout=30)
        runtime_cfg.raise_for_status()
        configured_api_base = parse_runtime_api_base(runtime_cfg.text)
        if is_placeholder_url(configured_api_base):
            configured_api_base = DEFAULT_RAILWAY_URL
        print(f"Runtime API base: {configured_api_base}")

        if not RAILWAY_URL:
            api_base = configured_api_base
        else:
            api_base = RAILWAY_URL

        startup = wait_for_startup_ready(api_base)
        degraded_startup = False
        if isinstance(startup, dict) and startup.get("ready"):
            print("PASS: Backend startup ready")
        elif isinstance(startup, dict) and startup.get("status") == "running" and not startup.get("error_message"):
            degraded_startup = True
            progress = startup.get("progress")
            current_step = startup.get("current_step")
            print(
                "WARN: Backend startup still running after wait window; proceeding in degraded mode "
                f"(progress={progress}, step={current_step})"
            )
        else:
            return fail(
                "Backend startup not ready after wait window. "
                "Check Railway env vars SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_DB_URL and deployment logs. "
                f"Last payload: {json.dumps(startup)[:500]}",
                4,
            )

        queue = wait_for_queue_healthy(api_base)
        if not isinstance(queue, dict) or not queue.get("available"):
            return fail(f"Queue endpoint unavailable after wait window: {json.dumps(queue)[:500]}", 5)
        if not queue.get("worker_running"):
            return fail(f"Queue worker is not running after wait window: {json.dumps(queue)[:500]}", 6)
        print("PASS: Queue worker healthy")

        if degraded_startup:
            print("PASS: degraded routing/health accepted (startup still running, queue healthy)")

        print("PASS: deployed routing and backend health checks")
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during check: {exc}", 10)
    except Exception as exc:
        return fail(f"Unhandled error during routing check: {exc}", 11)


if __name__ == "__main__":
    sys.exit(main())
