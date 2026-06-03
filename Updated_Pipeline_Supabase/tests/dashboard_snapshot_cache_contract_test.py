"""
Contract test for short-lived dashboard snapshot caches.

Repeated /api/violations and /api/stats polls should be able to reuse a fresh
in-memory payload briefly instead of rebuilding from the DB every time.
"""
# Readability: Test setup: document the contract this file protects.

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_dashboard_cache_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_dashboard_cache_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
# Trigger the side effect required for this stage.
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)

import casm_app


# Section: group fake dashboard db state and behaviour in one readable unit.
class _FakeDashboardDB:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self):
        # Prepare calls for the next step.
        self.calls = 0

    # Section: run the get all violations with status workflow with clear inputs and outputs.
    def get_all_violations_with_status(self, limit=100):
        self.calls += 1
        return [
            {
                "report_id": "20260512_101500",
                "timestamp": datetime(2026, 5, 12, 10, 15, 0, tzinfo=timezone.utc),
                "person_count": 1,
                "violation_count": 1,
                "severity": "HIGH",
                "status": "completed",
                "error_message": None,
                "device_id": "webcam_0",
                "violation_id": "vio-1",
                "violation_summary": "PPE Violation Detected: NO-Hardhat",
                "caption": "Worker missing hardhat near scaffold.",
                "nlp_analysis": None,
                "detection_data": {
                    "source_scope": "cloud",
                    "source": "cloud_live",
                    "ppe_tags": ["NO-Hardhat"],
                    "missing_ppe": ["Hardhat"],
                },
                "original_image_key": "violations/20260512_101500/original.jpg",
                "annotated_image_key": "violations/20260512_101500/annotated.jpg",
                "report_html_key": "violations/20260512_101500/report.html",
                "report_pdf_key": None,
            }
        ]


# Section: group fake storage bucket state and behaviour in one readable unit.
class _FakeStorageBucket:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, mapping, bucket_name):
        # Prepare mapping for the next step.
        self.mapping = mapping
        self.bucket_name = bucket_name
        self.calls = []

    # Section: run the list workflow with clear inputs and outputs.
    def list(self, path="", options=None):
        normalized_path = str(path or "").strip("/")
        self.calls.append((self.bucket_name, normalized_path, options or {}))
        return [{"name": name} for name in self.mapping.get((self.bucket_name, normalized_path), [])]


# Section: group fake storage namespace state and behaviour in one readable unit.
class _FakeStorageNamespace:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, mapping):
        # Prepare mapping for the next step.
        self.mapping = mapping

    # Section: run the from workflow with clear inputs and outputs.
    def from_(self, bucket_name):
        return _FakeStorageBucket(self.mapping, bucket_name)


# Section: group fake storage client state and behaviour in one readable unit.
class _FakeStorageClient:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, mapping):
        self.storage = _FakeStorageNamespace(mapping)


# Section: group fake storage manager state and behaviour in one readable unit.
class _FakeStorageManager:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, mapping):
        # Prepare supabase url for the next step.
        self.supabase_url = "https://unit-test.supabase.co"
        self.reports_bucket = "reports"
        self.images_bucket = "violation-images"
        self.client = _FakeStorageClient(mapping)


# Section: group fake storage backed db state and behaviour in one readable unit.
class _FakeStorageBackedDB:
    # Section: run the get all violations with status workflow with clear inputs and outputs.
    def get_all_violations_with_status(self, limit=100):
        return [
            {
                "report_id": "20260512_101500",
                "timestamp": datetime(2026, 5, 12, 10, 15, 0, tzinfo=timezone.utc),
                "severity": "HIGH",
                "status": "completed",
                "device_id": "webcam_0",
                "detection_data": {"source_scope": "cloud", "source": "cloud_live"},
                "original_image_key": "violation-images/20260512_101500/original.jpg",
                "annotated_image_key": "violation-images/20260512_101500/annotated.jpg",
                "report_html_key": "reports/20260512_101500/report.html",
                "report_pdf_key": None,
            },
            {
                "report_id": "20260513_111500",
                "timestamp": datetime(2026, 5, 13, 11, 15, 0, tzinfo=timezone.utc),
                "severity": "MEDIUM",
                "status": "completed",
                "device_id": "local_cache_sync",
                "detection_data": {
                    "source_scope": "synced_local",
                    "source": "sync_local_cache",
                    "sync_state": "synced",
                },
                "original_image_key": "violation-images/20260513_111500/original.jpg",
                "annotated_image_key": "violation-images/20260513_111500/annotated.jpg",
                "report_html_key": "reports/20260513_111500/report.html",
                "report_pdf_key": None,
            },
            {
                "report_id": "20260401_010101",
                "timestamp": datetime(2026, 4, 1, 1, 1, 1, tzinfo=timezone.utc),
                "severity": "HIGH",
                "status": "completed",
                "device_id": "local_cache_sync",
                "detection_data": {
                    "source_scope": "synced_local",
                    "source": "sync_local_cache",
                    "sync_state": "synced",
                },
                "original_image_key": "violation-images/20260401_010101/original.jpg",
                "annotated_image_key": "violation-images/20260401_010101/annotated.jpg",
                "report_html_key": "reports/20260401_010101/report.html",
                "report_pdf_key": None,
            },
        ]


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test dashboard endpoints reuse short lived snapshot cache workflow with clear inputs and outputs.
def test_dashboard_endpoints_reuse_short_lived_snapshot_cache():
    fake_db = _FakeDashboardDB()

    old_db_manager = casm_app.db_manager
    old_storage_manager = casm_app.storage_manager
    # Prepare old violations dir for the next step.
    old_violations_dir = casm_app.VIOLATIONS_DIR
    old_violation_ttl = casm_app.VIOLATIONS_SNAPSHOT_CACHE_TTL_SECONDS
    old_stats_ttl = casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS

    with tempfile.TemporaryDirectory() as tmpdir:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare db manager for the next step.
            casm_app.db_manager = fake_db
            casm_app.storage_manager = None
            casm_app.VIOLATIONS_DIR = Path(tmpdir)
            casm_app.VIOLATIONS_SNAPSHOT_CACHE_TTL_SECONDS = 60.0
            casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS = 60.0
            casm_app._invalidate_dashboard_snapshot_cache()
            casm_app._invalidate_local_report_state_cache()

            with casm_app.app.test_client() as client:
                # Prepare first violations for the next step.
                first_violations = client.get("/api/violations?limit=50")
                second_violations = client.get("/api/violations?limit=50")
                first_stats = client.get("/api/stats")
                second_stats = client.get("/api/stats")

            # Trigger the side effect required for this stage.
            _assert(first_violations.status_code == 200, "First /api/violations call failed")
            _assert(second_violations.status_code == 200, "Second /api/violations call failed")
            _assert(first_stats.status_code == 200, "First /api/stats call failed")
            _assert(second_stats.status_code == 200, "Second /api/stats call failed")
            _assert(
                fake_db.calls == 2,
                f"Expected one DB rebuild per endpoint family, got calls={fake_db.calls}",
            )
        finally:
            # Prepare db manager for the next step.
            casm_app.db_manager = old_db_manager
            casm_app.storage_manager = old_storage_manager
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.VIOLATIONS_SNAPSHOT_CACHE_TTL_SECONDS = old_violation_ttl
            casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS = old_stats_ttl
            casm_app._invalidate_dashboard_snapshot_cache()
            casm_app._invalidate_local_report_state_cache()


# Section: run the test stats counts cloud storage metadata without downloads workflow with clear inputs and outputs.
def test_stats_counts_cloud_storage_metadata_without_downloads():
    # Prepare storage mapping for the next step.
    storage_mapping = {
        ("reports", ""): ["20260512_101500", "20260513_111500"],
        ("reports", "20260512_101500"): ["report.html"],
        ("reports", "20260513_111500"): ["report.html"],
        ("violation-images", ""): ["20260512_101500", "20260513_111500"],
        ("violation-images", "20260512_101500"): ["original.jpg", "annotated.jpg"],
        ("violation-images", "20260513_111500"): ["original.jpg", "annotated.jpg"],
    }

    # Prepare old db manager for the next step.
    old_db_manager = casm_app.db_manager
    old_storage_manager = casm_app.storage_manager
    old_violations_dir = casm_app.VIOLATIONS_DIR
    old_stats_ttl = casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS
    old_storage_ttl = casm_app.CLOUD_STORAGE_STATS_INDEX_TTL_SECONDS

    with tempfile.TemporaryDirectory() as tmpdir:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare db manager for the next step.
            casm_app.db_manager = _FakeStorageBackedDB()
            casm_app.storage_manager = _FakeStorageManager(storage_mapping)
            casm_app.VIOLATIONS_DIR = Path(tmpdir)
            casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS = 0.0
            casm_app.CLOUD_STORAGE_STATS_INDEX_TTL_SECONDS = 60.0
            casm_app._invalidate_dashboard_snapshot_cache()
            casm_app._invalidate_local_report_state_cache()

            with casm_app.app.test_client() as client:
                # Prepare response for the next step.
                response = client.get("/api/stats")

            # Trigger the side effect required for this stage.
            _assert(response.status_code == 200, "Storage-backed /api/stats call failed")
            payload = response.json or {}
            _assert(payload.get("cloudStorageIndexed") is True, "Expected storage metadata stats source")
            _assert(payload.get("total") == 2, f"Expected only two storage-backed artifacts, got {payload}")
            _assert(payload.get("reportsGenerated") == 2, f"Expected two generated storage reports, got {payload}")
            _assert(
                (payload.get("sourceCounts") or {}).get("synced_local") == 1,
                f"Expected valid local-synced storage artifact to be counted, got {payload}",
            )
            # Trigger the side effect required for this stage.
            _assert(payload.get("cloudStorageReports") == 2, f"Expected two report objects, got {payload}")
        finally:
            casm_app.db_manager = old_db_manager
            casm_app.storage_manager = old_storage_manager
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS = old_stats_ttl
            casm_app.CLOUD_STORAGE_STATS_INDEX_TTL_SECONDS = old_storage_ttl
            casm_app._invalidate_dashboard_snapshot_cache()
            casm_app._invalidate_local_report_state_cache()


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Trigger the side effect required for this stage.
        test_dashboard_endpoints_reuse_short_lived_snapshot_cache()
        print("PASS: test_dashboard_endpoints_reuse_short_lived_snapshot_cache")
    except Exception as exc:
        print(f"FAIL: test_dashboard_endpoints_reuse_short_lived_snapshot_cache: {exc}")
        raise SystemExit(1)

    try:
        test_stats_counts_cloud_storage_metadata_without_downloads()
        print("PASS: test_stats_counts_cloud_storage_metadata_without_downloads")
    except Exception as exc:
        # Trigger the side effect required for this stage.
        print(f"FAIL: test_stats_counts_cloud_storage_metadata_without_downloads: {exc}")
        raise SystemExit(1)

    # Trigger the side effect required for this stage.
    print("Dashboard snapshot cache contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
