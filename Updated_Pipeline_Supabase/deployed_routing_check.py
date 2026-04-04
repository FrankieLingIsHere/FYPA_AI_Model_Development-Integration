import json
import os
import re
import sys

import requests


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

DEFAULT_RAILWAY_URL = "https://fypaaimodeldevelopment-integration-production.up.railway.app"
RAILWAY_URL = os.environ.get("LUNA_BASE_URL", "").rstrip("/")


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

        startup = get_json(f"{api_base}/api/system/startup-status")
        if not isinstance(startup, dict) or not startup.get("ready"):
            return fail(f"Backend startup not ready: {json.dumps(startup)[:350]}", 4)
        print("PASS: Backend startup ready")

        queue = get_json(f"{api_base}/api/queue/status")
        if not isinstance(queue, dict) or not queue.get("available"):
            return fail(f"Queue endpoint unavailable: {json.dumps(queue)[:350]}", 5)
        if not queue.get("worker_running"):
            return fail(f"Queue worker is not running: {json.dumps(queue)[:350]}", 6)
        print("PASS: Queue worker healthy")

        print("PASS: deployed routing and backend health checks")
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during check: {exc}", 10)
    except Exception as exc:
        return fail(f"Unhandled error during routing check: {exc}", 11)


if __name__ == "__main__":
    sys.exit(main())
