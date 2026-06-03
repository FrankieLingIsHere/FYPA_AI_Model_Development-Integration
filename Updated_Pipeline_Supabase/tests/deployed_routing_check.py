# Readability: Test setup: document the contract this file protects.
import json
import os
import re
import sys
import time

import requests


# Prepare vercel url for the next step.
VERCEL_URL = os.environ.get(
    "CASM_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

DEFAULT_RAILWAY_URL = "https://fypaaimodeldevelopment-integration-production.up.railway.app"
RAILWAY_URL = os.environ.get("CASM_BASE_URL", "").rstrip("/")
STARTUP_WAIT_SECONDS = int(os.environ.get("CASM_STARTUP_WAIT_SECONDS", "180"))
STARTUP_POLL_INTERVAL_SECONDS = int(os.environ.get("CASM_STARTUP_POLL_INTERVAL_SECONDS", "6"))
# Prepare queue wait seconds for the next step.
QUEUE_WAIT_SECONDS = int(os.environ.get("CASM_QUEUE_WAIT_SECONDS", "90"))
QUEUE_POLL_INTERVAL_SECONDS = int(os.environ.get("CASM_QUEUE_POLL_INTERVAL_SECONDS", "6"))
ALLOW_DEGRADED_STARTUP = os.environ.get("CASM_ALLOW_DEGRADED_STARTUP", "0").strip().lower() in ("1", "true", "yes")


# Section: run the fail workflow with clear inputs and outputs.
def fail(msg: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: {msg}")
    return code


# Section: run the get json workflow with clear inputs and outputs.
def get_json(url: str, timeout: int = 30):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    try:
        # Return the prepared result to the caller.
        return r.json()
    except Exception as exc:
        raise RuntimeError(f"Expected JSON from {url}, got: {r.text[:220]}") from exc


# Section: run the parse runtime api base workflow with clear inputs and outputs.
def parse_runtime_api_base(js_text: str) -> str:
    # Prepare match for the next step.
    match = re.search(r"API_BASE_URL\s*:\s*'([^']+)'", js_text)
    if not match:
        match = re.search(r'API_BASE_URL\s*:\s*"([^"]+)"', js_text)
    return (match.group(1).strip() if match else "")


# Section: run the is placeholder url workflow with clear inputs and outputs.
def is_placeholder_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return (not text) or ("your-backend" in text) or text.endswith("example.com")


# Section: run the wait for startup ready workflow with clear inputs and outputs.
def wait_for_startup_ready(api_base: str):
    # Prepare deadline for the next step.
    deadline = time.time() + max(STARTUP_WAIT_SECONDS, 0)
    last_payload = None
    while True:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare payload for the next step.
            payload = get_json(f"{api_base}/api/system/startup-status")
            last_payload = payload
            ready = isinstance(payload, dict) and bool(payload.get("ready"))
            progress = payload.get("progress") if isinstance(payload, dict) else None
            message = payload.get("message") if isinstance(payload, dict) else None
            print(f"INFO: startup poll ready={ready} progress={progress} message={message}")
            if ready:
                # Return the prepared result to the caller.
                return payload
        except Exception as exc:
            # Trigger the side effect required for this stage.
            print(f"INFO: startup poll error: {exc}")

        # Choose the correct branch before the workflow continues.
        if time.time() >= deadline:
            break
        time.sleep(max(1, STARTUP_POLL_INTERVAL_SECONDS))

    # Return the prepared result to the caller.
    return last_payload


# Section: run the wait for queue healthy workflow with clear inputs and outputs.
def wait_for_queue_healthy(api_base: str):
    deadline = time.time() + max(QUEUE_WAIT_SECONDS, 0)
    last_payload = None
    while True:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare payload for the next step.
            payload = get_json(f"{api_base}/api/queue/status")
            last_payload = payload
            available = isinstance(payload, dict) and bool(payload.get("available"))
            worker_running = isinstance(payload, dict) and bool(payload.get("worker_running"))
            print(f"INFO: queue poll available={available} worker_running={worker_running}")
            if available and worker_running:
                # Return the prepared result to the caller.
                return payload
        except Exception as exc:
            print(f"INFO: queue poll error: {exc}")

        # Choose the correct branch before the workflow continues.
        if time.time() >= deadline:
            break
        time.sleep(max(1, QUEUE_POLL_INTERVAL_SECONDS))

    # Return the prepared result to the caller.
    return last_payload


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    try:
        # Prepare home for the next step.
        home = requests.get(f"{VERCEL_URL}/", timeout=30)
        home.raise_for_status()
        if "PPE Safety Monitor" not in home.text:
            # Return the prepared result to the caller.
            return fail("Vercel homepage loaded but expected app title text is missing", 3)
        print("PASS: Vercel homepage reachable")

        runtime_cfg = requests.get(f"{VERCEL_URL}/js/runtime-config.js", timeout=30)
        runtime_cfg.raise_for_status()
        configured_api_base = parse_runtime_api_base(runtime_cfg.text)
        # Choose the correct branch before the workflow continues.
        if is_placeholder_url(configured_api_base):
            configured_api_base = DEFAULT_RAILWAY_URL
        print(f"Runtime API base: {configured_api_base}")

        if not RAILWAY_URL:
            # Prepare api base for the next step.
            api_base = configured_api_base
        else:
            api_base = RAILWAY_URL

        # Prepare startup for the next step.
        startup = wait_for_startup_ready(api_base)
        degraded_startup = False
        if isinstance(startup, dict) and startup.get("ready"):
            print("PASS: Backend startup ready")
        elif ALLOW_DEGRADED_STARTUP and isinstance(startup, dict) and startup.get("status") == "running" and not startup.get("error_message"):
            # Prepare degraded startup for the next step.
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

        # Prepare queue for the next step.
        queue = wait_for_queue_healthy(api_base)
        if not isinstance(queue, dict) or not queue.get("available"):
            # Return the prepared result to the caller.
            return fail(f"Queue endpoint unavailable after wait window: {json.dumps(queue)[:500]}", 5)
        if not queue.get("worker_running"):
            return fail(f"Queue worker is not running after wait window: {json.dumps(queue)[:500]}", 6)
        print("PASS: Queue worker healthy")

        if degraded_startup:
            print("PASS: degraded routing/health accepted (startup still running, queue healthy)")

        # Trigger the side effect required for this stage.
        print("PASS: deployed routing and backend health checks")
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during check: {exc}", 10)
    except Exception as exc:
        return fail(f"Unhandled error during routing check: {exc}", 11)


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    sys.exit(main())
