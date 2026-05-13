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
from datetime import datetime, timezone

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


class CloudDB:
    def get_detection_event(self, report_id):
        return {
            "report_id": report_id,
            "status": "generating",
            "device_id": "webcam_0",
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_violation(self, report_id):
        return {
            "report_id": report_id,
            "original_image_key": f"violations/{report_id}/original.jpg",
            "annotated_image_key": None,
            "report_html_key": None,
            "detection_data": {
                "source_scope": "cloud",
                "source": "cloud_live",
            },
        }


class LocalUnsyncedDB:
    def get_detection_event(self, report_id):
        return {
            "report_id": report_id,
            "status": "generating",
            "device_id": "offline_local_cache",
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_violation(self, report_id):
        return {
            "report_id": report_id,
            "original_image_key": None,
            "annotated_image_key": None,
            "report_html_key": None,
            "detection_data": {
                "source_scope": "local",
                "source": "offline_local_cache",
                "device_id": "offline_local_cache",
            },
        }


class LocalSyncedDB:
    def get_detection_event(self, report_id):
        return {
            "report_id": report_id,
            "status": "generating",
            "device_id": "offline_local_cache",
            "sync_state": "cloud_sync_queued",
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_violation(self, report_id):
        return {
            "report_id": report_id,
            "original_image_key": f"violations/{report_id}/original.jpg",
            "annotated_image_key": None,
            "report_html_key": f"violations/{report_id}/report.html",
            "detection_data": {
                "source_scope": "synced_local",
                "source": "sync_local_cache",
                "sync_source": "sync_local_cache",
                "device_id": "offline_local_cache",
                "sync_state": "cloud_sync_queued",
            },
        }


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


def test_cloud_status_keeps_cloud_source_while_local_staging_files_exist():
    report_id = "20260511_164211"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"cloud-job-staged-original")
        (report_dir / "caption.txt").write_text("caption exists while cloud report is generating", encoding="utf-8")

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = CloudDB()

            with casm_app.app.test_client() as client:
                response = client.get(f"/api/report/{report_id}/status")
                payload = response.get_json() or {}

            _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
            _assert(payload.get("status") == "generating", f"Unexpected payload status: {payload}")
            _assert(payload.get("has_original") is True, "Cloud original image was not surfaced")
            _assert(payload.get("source_scope") == "cloud", f"Cloud source scope drifted: {payload}")
            _assert(payload.get("source_label") == "Cloud", f"Cloud source label drifted: {payload}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_cloud_violations_list_keeps_cloud_source_while_local_staging_files_exist():
    report_id = "20260513_190011"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"cloud-list-staged-original")
        (report_dir / "annotated.jpg").write_bytes(b"cloud-list-staged-annotated")

        class CloudViolationsDB:
            def get_all_violations_with_status(self, limit=200):
                return [{
                    "report_id": report_id,
                    "timestamp": datetime.now(timezone.utc),
                    "status": "generating",
                    "device_id": "webcam_0",
                    "severity": "HIGH",
                    "person_count": 1,
                    "violation_count": 1,
                    "violation_summary": "Cloud generation in flight",
                    "missing_ppe": ["Hardhat"],
                    "original_image_key": f"violations/{report_id}/original.jpg",
                    "annotated_image_key": None,
                    "report_html_key": None,
                    "detection_data": {
                        "source_scope": "cloud",
                        "source": "cloud_live",
                        "device_id": "webcam_0",
                    },
                }]

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = CloudViolationsDB()

            with casm_app.app.test_client() as client:
                response = client.get("/api/violations?limit=50")
                payload = response.get_json() or []

            _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
            row = next((item for item in payload if item.get("report_id") == report_id), None)
            _assert(row is not None, f"Cloud row missing from violations payload: {payload}")
            _assert(row.get("source_scope") == "cloud", f"Cloud report drifted in violations list: {row}")
            _assert(row.get("source_label") == "Cloud", f"Cloud label drifted in violations list: {row}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_local_db_status_stays_local_until_reconnect_sync_evidence_exists():
    report_id = "20260513_181500"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"local-unsynced-original")

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "local"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = LocalUnsyncedDB()

            with casm_app.app.test_client() as client:
                response = client.get(f"/api/report/{report_id}/status")
                payload = response.get_json() or {}

            _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
            _assert(payload.get("status") in {"pending", "generating"}, f"Unexpected payload status: {payload}")
            _assert(payload.get("source_scope") == "local", f"Unsynced local report drifted: {payload}")
            _assert(payload.get("source_label") == "Local", f"Unsynced local label drifted: {payload}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_local_db_status_becomes_local_synced_after_reconnect_sync_signal():
    report_id = "20260513_182200"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"local-synced-original")
        (report_dir / "report.html").write_text("<html>local synced report</html>", encoding="utf-8")

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "local"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = LocalSyncedDB()

            with casm_app.app.test_client() as client:
                response = client.get(f"/api/report/{report_id}/status")
                payload = response.get_json() or {}

            _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
            _assert(payload.get("status") in {"completed", "generating"}, f"Unexpected payload status: {payload}")
            _assert(payload.get("source_scope") == "synced_local", f"Reconnected local report did not promote: {payload}")
            _assert(payload.get("source_label") == "Local Synced", f"Reconnected local label drifted: {payload}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def main():
    tests = [
        test_status_endpoint_uses_local_artifacts_during_db_backoff,
        test_cloud_status_keeps_cloud_source_while_local_staging_files_exist,
        test_cloud_violations_list_keeps_cloud_source_while_local_staging_files_exist,
        test_local_db_status_stays_local_until_reconnect_sync_evidence_exists,
        test_local_db_status_becomes_local_synced_after_reconnect_sync_signal,
    ]
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
