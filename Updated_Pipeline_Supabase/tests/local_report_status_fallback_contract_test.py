"""
Contract test for local/offline report status fallback.

When Supabase is in reconnect backoff, db_manager can still be present while
local artifacts are the only reliable source of truth. The status endpoint must
not return not_found for a local report folder that exists.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_local_status_contract_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_local_status_contract_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)
os.environ.setdefault("SUPABASE_DB_URL", "postgres://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://projtest123.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-test-key")

import casm_app


class BackoffDB:
    def get_detection_event(self, report_id):
        raise ConnectionError("Database reconnect backoff active")

    def get_violation(self, report_id):
        raise ConnectionError("Database reconnect backoff active")


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_status_endpoint_uses_local_artifacts_during_db_backoff():
    report_id = "20260508_113411"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"not-a-real-image-but-present")

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        try:
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = BackoffDB()
            casm_app.update_report_progress(
                current=report_id,
                status="processing",
                current_step="Generating image caption",
            )

            with casm_app.app.test_client() as client:
                response = client.get(f"/api/report/{report_id}/status")
                payload = response.get_json() or {}

            _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
            _assert(payload.get("status") == "generating", f"Unexpected payload status: {payload}")
            _assert(payload.get("has_original") is True, "Local original image was not surfaced")
            _assert(payload.get("source_scope") == "local", "Local source scope was not preserved")
            _assert(payload.get("message") != "Report not found", "Local report was incorrectly reported as not_found")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.reset_report_progress()


def main():
    tests = [test_status_endpoint_uses_local_artifacts_during_db_backoff]
    failures = []
    for test_fn in tests:
        try:
            test_fn()
            print(f"PASS: {test_fn.__name__}")
        except Exception as exc:
            failures.append((test_fn.__name__, str(exc)))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    if failures:
        print("Local report status fallback contract test failed")
        raise SystemExit(1)

    print("Local report status fallback contract test passed")


if __name__ == "__main__":
    main()
