"""
Contract test: provider routing changes must invalidate short-lived API caches.

This prevents local<->cloud mode flips from briefly serving stale dashboard
tags/state snapshots from the previous routing profile.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_provider_routing_cache_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_provider_routing_cache_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)

import casm_app


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_provider_routing_update_invalidates_runtime_caches():
    env_keys = [
        "CASM_ROUTING_PROFILE",
        "MODEL_API_ENABLED",
        "GEMINI_ENABLED",
        "GEMINI_DAILY_BUDGET_USD",
        "GEMINI_MONTHLY_BUDGET_USD",
        "GEMINI_MAX_OUTPUT_TOKENS_PER_REPORT",
        "NLP_PROVIDER_ORDER",
        "EMBEDDING_PROVIDER_ORDER",
        "VISION_PROVIDER_ORDER",
        "NLP_API_MODEL",
        "EMBEDDING_API_MODEL",
        "GEMINI_MODEL",
        "GEMINI_REPORT_MODEL",
        "GEMINI_VISION_MODEL",
        "OLLAMA_MODEL",
        "OLLAMA_VISION_MODEL",
        "LOCAL_OLLAMA_UNIFIED_MODEL",
    ]
    old_env = {key: os.environ.get(key) for key in env_keys}
    old_model_api = dict(casm_app.MODEL_API_CONFIG)
    old_gemini = dict(casm_app.GEMINI_CONFIG)
    old_ollama = dict(casm_app.OLLAMA_CONFIG)

    try:
        with casm_app.queue_context_snapshot_cache_lock:
            casm_app.queue_context_snapshot_cache["ts"] = 123.0
            casm_app.queue_context_snapshot_cache["snapshot"] = {"queue_size": 9}
        with casm_app.local_report_state_cache_lock:
            casm_app.local_report_state_cache["ts"] = 123.0
            casm_app.local_report_state_cache["limit"] = 10
            casm_app.local_report_state_cache["rows"] = [{"report_id": "abc"}]
        with casm_app.dashboard_snapshot_cache_lock:
            casm_app.dashboard_snapshot_cache["violations"]["demo"] = {
                "expires_at": 9999999999.0,
                "payload": [{"report_id": "abc"}],
            }
            casm_app.dashboard_snapshot_cache["stats"]["demo"] = {
                "expires_at": 9999999999.0,
                "payload": {"total": 1},
            }

        with patch.object(casm_app, "_sync_report_generator_provider_runtime", return_value=None):
            with casm_app.app.test_client() as client:
                response = client.post(
                    "/api/settings/provider-routing",
                    json={"routing_profile": "cloud"},
                )
                payload = response.get_json() or {}

        _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
        _assert(payload.get("success") is True, f"Unexpected payload: {payload}")

        with casm_app.queue_context_snapshot_cache_lock:
            _assert(
                casm_app.queue_context_snapshot_cache.get("snapshot") is None,
                "Queue context cache was not invalidated",
            )
        with casm_app.local_report_state_cache_lock:
            _assert(
                casm_app.local_report_state_cache.get("rows") == [],
                "Local report state cache was not invalidated",
            )
        with casm_app.dashboard_snapshot_cache_lock:
            _assert(
                not casm_app.dashboard_snapshot_cache["violations"],
                "Violations snapshot cache was not invalidated",
            )
            _assert(
                not casm_app.dashboard_snapshot_cache["stats"],
                "Stats snapshot cache was not invalidated",
            )
    finally:
        casm_app.MODEL_API_CONFIG.clear()
        casm_app.MODEL_API_CONFIG.update(old_model_api)
        casm_app.GEMINI_CONFIG.clear()
        casm_app.GEMINI_CONFIG.update(old_gemini)
        casm_app.OLLAMA_CONFIG.clear()
        casm_app.OLLAMA_CONFIG.update(old_ollama)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        casm_app._invalidate_queue_context_snapshot_cache()
        casm_app._invalidate_local_report_state_cache()
        casm_app._invalidate_dashboard_snapshot_cache()


def main():
    try:
        test_provider_routing_update_invalidates_runtime_caches()
        print("PASS: test_provider_routing_update_invalidates_runtime_caches")
    except Exception as exc:
        print(f"FAIL: test_provider_routing_update_invalidates_runtime_caches: {exc}")
        raise SystemExit(1)

    print("Provider routing cache invalidation contract test passed")


if __name__ == "__main__":
    main()
