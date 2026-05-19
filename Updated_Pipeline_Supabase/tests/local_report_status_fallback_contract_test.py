"""
Contract test for local/offline report status fallback.

When Supabase is in reconnect backoff, db_manager can still be present while
local artifacts are the only reliable source of truth. The status endpoint must
not return not_found for a local report folder that exists.
"""

import os
import sys
import tempfile
import json
import time
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


class CloudStaleSyncedLocalDB:
    def get_detection_event(self, report_id):
        return {
            "report_id": report_id,
            "status": "completed",
            "device_id": "webcam_0",
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_violation(self, report_id):
        return {
            "report_id": report_id,
            "original_image_key": f"violations/{report_id}/original.jpg",
            "annotated_image_key": f"violations/{report_id}/annotated.jpg",
            "report_html_key": f"reports/{report_id}/report.html",
            "detection_data": {
                "source_scope": "synced_local",
                "source": "cloud_pending_local_handoff",
            },
        }

    def get_all_violations_with_status(self, limit=100):
        report_id = "20260516_112819"
        event = self.get_detection_event(report_id)
        violation = self.get_violation(report_id)
        return [{
            **event,
            "person_count": 1,
            "violation_count": 2,
            "severity": "HIGH",
            "violation_summary": "Missing Mask, Missing Safety Vest",
            **violation,
        }]


class TagMatrixDB:
    def __init__(self, records):
        self.records = {record["report_id"]: record for record in records}

    def get_detection_event(self, report_id):
        record = self.records[report_id]
        return {
            "report_id": report_id,
            "status": record["status"],
            "device_id": record["device_id"],
            "sync_state": record.get("sync_state"),
            "timestamp": record.get("timestamp") or datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_violation(self, report_id):
        record = self.records[report_id]
        return {
            "report_id": report_id,
            "original_image_key": record.get("original_image_key"),
            "annotated_image_key": record.get("annotated_image_key"),
            "report_html_key": record.get("report_html_key"),
            "detection_data": dict(record.get("detection_data") or {}),
        }

    def get_all_violations_with_status(self, limit=100):
        rows = []
        for report_id, record in self.records.items():
            rows.append({
                **self.get_detection_event(report_id),
                **self.get_violation(report_id),
                "person_count": record.get("person_count", 1),
                "violation_count": record.get("violation_count", 1),
                "severity": record.get("severity", "MEDIUM"),
                "violation_summary": record.get("violation_summary", "PPE violation"),
                "missing_ppe": record.get("missing_ppe", ["Mask"]),
            })
        return rows[:limit]


class CaptureUpdateDB:
    def __init__(self):
        self.calls = []

    def update_violation(self, report_id, **kwargs):
        self.calls.append((report_id, kwargs))


class CaptureQueue:
    def __init__(self):
        self.items = []

    def enqueue(self, violation_data, device_id, report_id, severity, expedite=False):
        self.items.append({
            "violation_data": dict(violation_data),
            "device_id": device_id,
            "report_id": report_id,
            "severity": severity,
            "expedite": expedite,
        })
        return True

    def get_stats(self):
        return {"current_size": len(self.items), "capacity": 100}

    def get_queue_size(self):
        return len(self.items)


class CaptureProcessingDB:
    def __init__(self):
        self.inserts = []
        self.status_updates = []

    def insert_detection_event(self, **kwargs):
        self.inserts.append(dict(kwargs))

    def update_detection_status(self, report_id, status, error_message=None):
        self.status_updates.append((report_id, status, error_message))


class ManualReprocessStaleHandoffDB(CaptureUpdateDB):
    def __init__(self, report_id):
        super().__init__()
        self.report_id = report_id
        self.status_updates = []

    def get_detection_event(self, report_id):
        return {
            "report_id": report_id,
            "status": "completed",
            "device_id": "webcam_0",
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_violation(self, report_id):
        return {
            "report_id": report_id,
            "original_image_key": f"violations/{report_id}/original.jpg",
            "annotated_image_key": f"violations/{report_id}/annotated.jpg",
            "report_html_key": f"reports/{report_id}/report.html",
            "detection_data": {
                "source_scope": "synced_local",
                "source": "browser_local_draft_handoff",
                "caption_validation": {"is_valid": True},
            },
        }

    def update_detection_status(self, report_id, status, error_message=None):
        self.status_updates.append((report_id, status, error_message))


class PendingStaleHandoffDB:
    def __init__(self, report_id):
        self.report_id = report_id

    def get_pending_reports(self, limit=300):
        return [{
            "report_id": self.report_id,
            "status": "pending",
            "device_id": "webcam_0",
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "original_image_key": f"violations/{self.report_id}/original.jpg",
            "annotated_image_key": None,
            "report_html_key": None,
            "detection_data": {
                "source_scope": "synced_local",
                "source": "browser_local_draft_handoff",
            },
        }]


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


def test_cloud_profile_does_not_promote_backoff_to_local_pipeline():
    old_profile = os.environ.get("CASM_ROUTING_PROFILE")
    old_until = casm_app.supabase_offline_backoff_until_epoch
    old_context = casm_app.supabase_offline_backoff_context
    old_error = casm_app.supabase_offline_backoff_error
    try:
        os.environ["CASM_ROUTING_PROFILE"] = "cloud"
        with casm_app.supabase_offline_backoff_lock:
            casm_app.supabase_offline_backoff_until_epoch = 9999999999.0
            casm_app.supabase_offline_backoff_context = "contract-test"
            casm_app.supabase_offline_backoff_error = "simulated lag"

        _assert(
            casm_app._is_local_pipeline_runtime_active() is False,
            "Cloud profile should not switch report generation to local artifact mode",
        )

        os.environ["CASM_ROUTING_PROFILE"] = "local"
        _assert(
            casm_app._is_local_pipeline_runtime_active() is True,
            "Local profile should still use local artifact mode during reconnect backoff",
        )
    finally:
        if old_profile is None:
            os.environ.pop("CASM_ROUTING_PROFILE", None)
        else:
            os.environ["CASM_ROUTING_PROFILE"] = old_profile
        with casm_app.supabase_offline_backoff_lock:
            casm_app.supabase_offline_backoff_until_epoch = old_until
            casm_app.supabase_offline_backoff_context = old_context
            casm_app.supabase_offline_backoff_error = old_error


def test_cloud_status_repairs_stale_synced_local_with_cloud_artifacts_to_cloud():
    report_id = "20260516_112819"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"stale-local-original")
        (report_dir / "report.html").write_text("<html>cloud report exists</html>", encoding="utf-8")

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = CloudStaleSyncedLocalDB()

            with casm_app.app.test_client() as client:
                status_response = client.get(f"/api/report/{report_id}/status")
                status_payload = status_response.get_json() or {}
                list_response = client.get("/api/violations?limit=10")
                list_payload = list_response.get_json() or []

            _assert(status_response.status_code == 200, f"Unexpected status code: {status_response.status_code}")
            _assert(status_payload.get("source_scope") == "cloud", f"Status stayed stale local: {status_payload}")
            _assert(status_payload.get("source_label") == "Cloud", f"Status label stayed stale local: {status_payload}")

            row = next((item for item in list_payload if item.get("report_id") == report_id), None)
            _assert(row is not None, f"Report missing from list payload: {list_payload}")
            _assert(row.get("source_scope") == "cloud", f"List stayed stale local: {row}")
            _assert(row.get("source_label") == "Cloud", f"List label stayed stale local: {row}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_manual_cloud_reprocess_metadata_removes_stale_local_handoff_markers():
    payload = casm_app._build_manual_reprocess_detection_data(
        {
            "source_scope": "synced_local",
            "source": "cloud_pending_local_handoff",
            "sync_source": "browser_local_draft_handoff",
            "caption_validation": {"is_valid": True},
        },
        source_scope="cloud",
        force_reprocess=True,
    )

    _assert(payload.get("source_scope") == "cloud", f"Cloud scope not persisted: {payload}")
    _assert(payload.get("source") == "manual_cloud_reprocess", f"Cloud repair source missing: {payload}")
    _assert("sync_source" not in payload, f"Stale local sync marker survived: {payload}")
    _assert(payload.get("caption_validation") == {"is_valid": True}, "Existing detection details were lost")


def test_manual_cloud_reprocess_persists_source_scope_repair():
    report_id = "20260516_112819"
    fake_db = CaptureUpdateDB()
    old_db_manager = casm_app.db_manager
    try:
        casm_app.db_manager = fake_db
        casm_app._persist_manual_reprocess_source_scope(
            report_id,
            source_scope="cloud",
            force_reprocess=True,
            violation={
                "detection_data": {
                    "source_scope": "synced_local",
                    "source": "cloud_pending_local_handoff",
                    "sync_source": "browser_local_draft_handoff",
                    "caption_validation": {"is_valid": True},
                }
            },
        )
    finally:
        casm_app.db_manager = old_db_manager

    _assert(len(fake_db.calls) == 1, f"Expected one DB repair call, got {fake_db.calls}")
    called_report_id, kwargs = fake_db.calls[0]
    detection_data = kwargs.get("detection_data") or {}
    _assert(called_report_id == report_id, f"Wrong report id persisted: {fake_db.calls}")
    _assert(detection_data.get("source_scope") == "cloud", f"Persisted repair did not set cloud: {detection_data}")
    _assert(detection_data.get("source") == "manual_cloud_reprocess", f"Persisted source marker wrong: {detection_data}")
    _assert("sync_source" not in detection_data, f"Persisted stale sync marker: {detection_data}")
    _assert(detection_data.get("caption_validation") == {"is_valid": True}, "Persisted repair lost detection details")


def test_generate_now_repairs_stale_browser_handoff_to_cloud_queue_scope():
    report_id = "stale_handoff_route_001"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        frame = casm_app.np.zeros((8, 8, 3), dtype=casm_app.np.uint8)
        casm_app.cv2.imwrite(str(report_dir / "original.jpg"), frame)
        casm_app.cv2.imwrite(str(report_dir / "annotated.jpg"), frame)

        fake_queue = CaptureQueue()
        fake_db = ManualReprocessStaleHandoffDB(report_id)
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_violation_queue = casm_app.violation_queue
        old_ensure_queue_worker_running = casm_app.ensure_queue_worker_running
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = fake_db
            casm_app.violation_queue = fake_queue
            casm_app.ensure_queue_worker_running = lambda: True

            with casm_app.app.test_client() as client:
                response = client.post(
                    f"/api/report/{report_id}/generate-now",
                    json={
                        "force": True,
                        "source_scope": "synced_local",
                        "source": "browser_local_draft_handoff",
                    },
                )
                payload = response.get_json() or {}

            _assert(response.status_code == 200, f"generate-now failed: {response.status_code} {payload}")
            _assert(payload.get("source_scope") == "cloud", f"Response stayed local-synced: {payload}")
            _assert(fake_queue.items, "Manual reprocess did not enqueue")
            queue_payload = fake_queue.items[0]["violation_data"]
            _assert(queue_payload.get("source_scope") == "cloud", f"Queue scope drifted: {queue_payload}")
            _assert("sync_source" not in queue_payload, f"Queue kept stale sync marker: {queue_payload}")
            _assert(fake_db.calls, "Manual reprocess did not persist source repair")
            repaired_detection_data = fake_db.calls[0][1].get("detection_data") or {}
            _assert(repaired_detection_data.get("source_scope") == "cloud", f"DB repair scope drifted: {repaired_detection_data}")
            _assert(repaired_detection_data.get("source") == "manual_cloud_reprocess", f"DB repair source drifted: {repaired_detection_data}")
            _assert("sync_source" not in repaired_detection_data, f"DB repair kept stale sync marker: {repaired_detection_data}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.violation_queue = old_violation_queue
            casm_app.ensure_queue_worker_running = old_ensure_queue_worker_running
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_pending_reports_repairs_stale_browser_handoff_to_cloud_scope():
    report_id = "stale_handoff_pending_001"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = PendingStaleHandoffDB(report_id)

            with casm_app.app.test_client() as client:
                response = client.get("/api/reports/pending")
                payload = response.get_json() or []

            _assert(response.status_code == 200, f"Pending reports failed: {response.status_code} {payload}")
            row = next((item for item in payload if item.get("report_id") == report_id), None)
            _assert(row is not None, f"Missing pending row: {payload}")
            _assert(row.get("source_scope") == "cloud", f"Pending row stayed local-synced: {row}")
            _assert(row.get("source_label") == "Cloud", f"Pending row label drifted: {row}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_report_response_injects_summary_readability_styles_for_legacy_reports():
    legacy_html = """
    <html>
      <head><title>Legacy report</title></head>
      <body>
        <div class="card" style="border-left: 5px solid #e74c3c;">
          <div class="card-header">EXECUTIVE SAFETY SUMMARY (AT A GLANCE)</div>
          <div class="card-content" style="padding: 0;">
            <table style="width: 100%; border-collapse: collapse;">
              <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">WHAT</td>
                <td style="padding: 12px; white-space: normal; word-break: break-word;">Long summary text</td>
              </tr>
            </table>
          </div>
        </div>
      </body>
    </html>
    """
    response_html, status_code, _headers = casm_app._report_html_response(legacy_html)

    _assert(status_code == 200, f"Unexpected report response status: {status_code}")
    _assert(
        'id="casm-summary-readability-overrides"' in response_html,
        "Legacy report response did not inject summary readability CSS",
    )
    _assert(
        'id="casm-summary-layout-normalizer"' in response_html,
        "Legacy report response did not inject summary layout normalizer",
    )
    _assert(
        "summary-bullet-list" in response_html,
        "Summary bullet-list CSS/normalizer missing from legacy report response",
    )
    _assert(
        '.card[style*="border-left: 5px solid #e74c3c"] table' in response_html,
        "Legacy summary table selector missing from readability CSS",
    )
    _assert(
        response_html.count('id="casm-summary-readability-overrides"') == 1,
        "Summary readability CSS should be injected once",
    )


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


def test_auto_reconnect_sync_is_not_deferred_by_local_runtime_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_storage_manager = casm_app.storage_manager
        old_violation_queue = casm_app.violation_queue
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "local"
            casm_app.VIOLATIONS_DIR = Path(tmpdir)
            casm_app.db_manager = object()
            casm_app.storage_manager = object()
            casm_app.violation_queue = CaptureQueue()

            manual_result = casm_app._sync_local_cache_candidates(
                max_items=10,
                dry_run=False,
                reconcile_reason="manual_api",
                require_worker=False,
            )
            reconnect_result = casm_app._sync_local_cache_candidates(
                max_items=10,
                dry_run=False,
                reconcile_reason="reconnect_auto",
                require_worker=False,
            )

            _assert(manual_result.get("deferred_reason") == "routing_profile_local", manual_result)
            _assert(reconnect_result.get("success") is True, reconnect_result)
            _assert(reconnect_result.get("deferred") is not True, reconnect_result)
            _assert(reconnect_result.get("scanned") == 0, reconnect_result)
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.storage_manager = old_storage_manager
            casm_app.violation_queue = old_violation_queue
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile


def test_report_source_tag_matrix_preserves_local_and_synced_local_cases():
    cases = [
        {
            "report_id": "tag_cloud_inflight",
            "status": "generating",
            "device_id": "webcam_0",
            "source_scope": "cloud",
            "source_label": "Cloud",
            "original_image_key": "violations/tag_cloud_inflight/original.jpg",
            "detection_data": {
                "source_scope": "cloud",
                "source": "live_capture",
                "device_id": "webcam_0",
            },
            "local_files": ["original.jpg", "caption.txt"],
        },
        {
            "report_id": "tag_local_unsynced",
            "status": "generating",
            "device_id": "offline_local_cache",
            "source_scope": "local",
            "source_label": "Local",
            "detection_data": {
                "source_scope": "local",
                "source": "offline_local_cache",
                "device_id": "offline_local_cache",
            },
            "local_files": ["original.jpg", "metadata.json"],
        },
        {
            "report_id": "tag_local_synced",
            "status": "completed",
            "device_id": "offline_local_cache",
            "sync_state": "cloud_sync_queued",
            "source_scope": "synced_local",
            "source_label": "Local Synced",
            "original_image_key": "violations/tag_local_synced/original.jpg",
            "report_html_key": "reports/tag_local_synced/report.html",
            "detection_data": {
                "source_scope": "synced_local",
                "source": "sync_local_cache",
                "sync_source": "sync_local_cache",
                "device_id": "offline_local_cache",
                "sync_state": "cloud_sync_queued",
            },
            "local_files": ["original.jpg", "report.html"],
        },
        {
            "report_id": "tag_stale_fake_synced",
            "status": "completed",
            "device_id": "webcam_0",
            "source_scope": "cloud",
            "source_label": "Cloud",
            "original_image_key": "violations/tag_stale_fake_synced/original.jpg",
            "annotated_image_key": "violations/tag_stale_fake_synced/annotated.jpg",
            "report_html_key": "reports/tag_stale_fake_synced/report.html",
            "detection_data": {
                "source_scope": "synced_local",
                "source": "cloud_pending_local_handoff",
                "device_id": "webcam_0",
            },
            "local_files": ["original.jpg", "report.html"],
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for case in cases:
            report_dir = root / case["report_id"]
            report_dir.mkdir(parents=True, exist_ok=True)
            for filename in case.get("local_files", []):
                target = report_dir / filename
                if filename == "metadata.json":
                    target.write_text(json.dumps(case.get("detection_data") or {}), encoding="utf-8")
                else:
                    target.write_text(f"fixture for {case['report_id']} {filename}", encoding="utf-8")

        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = TagMatrixDB(cases)
            casm_app._invalidate_dashboard_snapshot_cache()

            with casm_app.app.test_client() as client:
                status_payloads = {}
                for case in cases:
                    response = client.get(f"/api/report/{case['report_id']}/status")
                    payload = response.get_json() or {}
                    _assert(response.status_code == 200, f"Unexpected status for {case['report_id']}: {payload}")
                    status_payloads[case["report_id"]] = payload

                list_response = client.get("/api/violations?limit=77")
                list_payload = list_response.get_json() or []

            list_by_id = {
                row.get("report_id"): row
                for row in list_payload
                if isinstance(row, dict) and row.get("report_id")
            }
            for case in cases:
                report_id = case["report_id"]
                expected_scope = case["source_scope"]
                expected_label = case["source_label"]
                status_payload = status_payloads[report_id]
                list_row = list_by_id.get(report_id)
                _assert(list_row is not None, f"Missing matrix row in /api/violations: {report_id}")
                _assert(
                    status_payload.get("source_scope") == expected_scope,
                    f"Status tag drifted for {report_id}: {status_payload}",
                )
                _assert(
                    status_payload.get("source_label") == expected_label,
                    f"Status label drifted for {report_id}: {status_payload}",
                )
                _assert(
                    list_row.get("source_scope") == expected_scope,
                    f"List tag drifted for {report_id}: {list_row}",
                )
                _assert(
                    list_row.get("source_label") == expected_label,
                    f"List label drifted for {report_id}: {list_row}",
                )
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app._invalidate_dashboard_snapshot_cache()
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_cloud_enqueue_payload_keeps_cloud_scope_without_browser_handoff():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fake_queue = CaptureQueue()
        fake_db = CaptureProcessingDB()
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_violation_queue = casm_app.violation_queue
        old_ensure_queue_worker_running = casm_app.ensure_queue_worker_running
        old_last_violation_time = casm_app.last_violation_time
        old_redundant_check = casm_app._is_redundant_live_violation
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        old_backoff_until = casm_app.supabase_offline_backoff_until_epoch
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.supabase_offline_backoff_until_epoch = 0.0
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = fake_db
            casm_app.violation_queue = fake_queue
            casm_app.ensure_queue_worker_running = lambda: True
            casm_app.last_violation_time = 0
            casm_app._is_redundant_live_violation = lambda *_args, **_kwargs: False

            frame = casm_app.np.zeros((8, 8, 3), dtype=casm_app.np.uint8)
            detections = [
                {"class_name": "person", "confidence": 0.91, "bbox": [0, 0, 4, 7]},
                {"class_name": "no-mask", "confidence": 0.87, "bbox": [1, 1, 5, 5]},
            ]
            report_id = casm_app.enqueue_violation(
                frame,
                detections,
                trigger_source="live",
                annotated_frame=frame.copy(),
            )

            _assert(report_id, "Cloud enqueue did not return a report id")
            _assert(len(fake_queue.items) == 1, f"Expected one queue item, got {fake_queue.items}")
            item = fake_queue.items[0]
            payload = item["violation_data"]
            _assert(item["device_id"] == "webcam_0", f"Cloud queue device drifted: {item}")
            _assert(payload.get("source_scope") == "cloud", f"Queue payload scope drifted: {payload}")
            _assert(payload.get("sync_source") == "live_capture", f"Queue payload sync marker drifted: {payload}")
            _assert(payload.get("source") == "live_capture", f"Queue payload source marker drifted: {payload}")
            _assert(fake_db.inserts, "Cloud enqueue should still insert a pending DB event through the fake DB")

            metadata_path = root / report_id / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            _assert(metadata.get("source_scope") == "cloud", f"Metadata scope drifted: {metadata}")
            _assert(metadata.get("source_label") == "Cloud", f"Metadata label drifted: {metadata}")
            _assert(metadata.get("sync_source") == "live_capture", f"Metadata sync marker drifted: {metadata}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.violation_queue = old_violation_queue
            casm_app.ensure_queue_worker_running = old_ensure_queue_worker_running
            casm_app.last_violation_time = old_last_violation_time
            casm_app._is_redundant_live_violation = old_redundant_check
            casm_app.supabase_offline_backoff_until_epoch = old_backoff_until
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile


def test_cloud_queued_generation_finishes_with_cloud_scope_without_supabase_mutation():
    class FakeCaptionGenerator:
        def generate_caption(self, _image_path):
            return "Worker is missing a mask in a monitored work area."

    class FakeReportGenerator:
        def __init__(self):
            self.calls = []

        def generate_report(self, report_data):
            self.calls.append(dict(report_data))
            report_dir = Path(report_data["original_image_path"]).parent
            (report_dir / "report.html").write_text("<html>cloud report complete</html>", encoding="utf-8")
            return {
                "html": "<html>cloud report complete</html>",
                "storage_keys": {"report_html_key": f"reports/{report_data['report_id']}/report.html"},
            }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_id = "cloud_queue_contract_001"
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        frame = casm_app.np.zeros((8, 8, 3), dtype=casm_app.np.uint8)
        original_path = report_dir / "original.jpg"
        annotated_path = report_dir / "annotated.jpg"
        casm_app.cv2.imwrite(str(original_path), frame)
        casm_app.cv2.imwrite(str(annotated_path), frame)

        fake_db = CaptureProcessingDB()
        fake_report_generator = FakeReportGenerator()
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_caption_generator = casm_app.caption_generator
        old_report_generator = casm_app.report_generator
        old_env_validation = casm_app.ENVIRONMENT_VALIDATION_ENABLED
        old_push_realtime = casm_app._push_realtime_report_event
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "cloud"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = fake_db
            casm_app.caption_generator = FakeCaptionGenerator()
            casm_app.report_generator = fake_report_generator
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = False
            casm_app._push_realtime_report_event = lambda *_args, **_kwargs: None

            queued = casm_app.QueuedViolation(
                priority=0,
                timestamp=time.time(),
                data={
                    "report_id": report_id,
                    "timestamp": datetime.now(timezone.utc),
                    "detections": [
                        {"class_name": "person", "confidence": 0.91, "bbox": [0, 0, 4, 7]},
                        {"class_name": "no-mask", "confidence": 0.87, "bbox": [1, 1, 5, 5]},
                    ],
                    "violation_types": ["no-mask"],
                    "violation_count": 1,
                    "original_image_path": str(original_path),
                    "annotated_image_path": str(annotated_path),
                    "violation_dir": str(report_dir),
                    "severity": "HIGH",
                    "source_scope": "cloud",
                    "sync_source": "live_capture",
                    "source": "live_capture",
                },
                device_id="webcam_0",
                report_id=report_id,
            )

            casm_app.process_queued_violation(queued)

            _assert((report_dir / "report.html").exists(), "Queued cloud report did not finish generation")
            _assert(fake_report_generator.calls, "Report generator was not called")
            report_call = fake_report_generator.calls[0]
            _assert(report_call.get("source_scope") == "cloud", f"Generator scope drifted: {report_call}")
            _assert(report_call.get("sync_source") == "live_capture", f"Generator sync marker drifted: {report_call}")
            statuses = [status for _rid, status, _err in fake_db.status_updates]
            _assert("generating" in statuses, f"Generating status missing: {fake_db.status_updates}")
            _assert("completed" in statuses, f"Completed status missing: {fake_db.status_updates}")

            metadata = json.loads((report_dir / "metadata.json").read_text(encoding="utf-8"))
            _assert(metadata.get("source_scope") == "cloud", f"Generated metadata scope drifted: {metadata}")
            _assert(metadata.get("source_label") == "Cloud", f"Generated metadata label drifted: {metadata}")
            _assert(metadata.get("has_report") is True, f"Generated metadata did not mark report ready: {metadata}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.caption_generator = old_caption_generator
            casm_app.report_generator = old_report_generator
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = old_env_validation
            casm_app._push_realtime_report_event = old_push_realtime
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_local_pending_recovery_preserves_metadata_ppe_labels():
    report_id = "local_recovery_metadata_contract_001"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        frame = casm_app.np.zeros((8, 8, 3), dtype=casm_app.np.uint8)
        casm_app.cv2.imwrite(str(report_dir / "original.jpg"), frame)
        casm_app.cv2.imwrite(str(report_dir / "annotated.jpg"), frame)
        (report_dir / "metadata.json").write_text(json.dumps({
            "report_id": report_id,
            "source_scope": "local",
            "sync_source": "local_pipeline",
            "device_id": "offline_local_cache",
            "violation_types": [],
            "missing_ppe": ["NO-Hardhat", "Safety Vest", "Mask"],
            "ppe_tags": [],
            "violation_summary": "PPE Violation Detected: Missing Hard Hat, Missing Safety Vest, Missing Mask",
            "violation_count": 3,
            "person_count": 1,
        }), encoding="utf-8")
        stale_epoch = time.time() - 3600
        os.utime(report_dir, (stale_epoch, stale_epoch))

        fake_queue = CaptureQueue()
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_violation_queue = casm_app.violation_queue
        old_ensure_runtime_ready = casm_app._ensure_violation_queue_runtime_ready
        old_ensure_queue_worker_running = casm_app.ensure_queue_worker_running
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        old_recovery_enabled = casm_app.LOCAL_PENDING_RECOVERY_ENABLED
        old_recovery_stale = casm_app.LOCAL_PENDING_RECOVERY_STALE_SECONDS
        old_recovery_max = casm_app.LOCAL_PENDING_RECOVERY_MAX_ENQUEUE_PER_SWEEP
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "local"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = None
            casm_app.violation_queue = fake_queue
            casm_app._ensure_violation_queue_runtime_ready = lambda reason='': True
            casm_app.ensure_queue_worker_running = lambda: True
            casm_app.LOCAL_PENDING_RECOVERY_ENABLED = True
            casm_app.LOCAL_PENDING_RECOVERY_STALE_SECONDS = 1
            casm_app.LOCAL_PENDING_RECOVERY_MAX_ENQUEUE_PER_SWEEP = 1

            summary = casm_app._run_local_pending_recovery_sweep(reason="contract")

            _assert(summary.get("enqueued") == 1, f"Recovery did not enqueue: {summary}")
            _assert(fake_queue.items, "Recovery queue did not receive item")
            payload = fake_queue.items[0]["violation_data"]
            _assert(
                payload.get("violation_types") == ["NO-Hardhat", "NO-Safety Vest", "NO-Mask"],
                f"Recovered payload lost PPE labels: {payload}",
            )
            _assert(payload.get("violation_count") == 3, f"Recovered count drifted: {payload}")
            _assert(payload.get("source_scope") == "local", f"Recovered scope drifted: {payload}")
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.violation_queue = old_violation_queue
            casm_app._ensure_violation_queue_runtime_ready = old_ensure_runtime_ready
            casm_app.ensure_queue_worker_running = old_ensure_queue_worker_running
            casm_app.LOCAL_PENDING_RECOVERY_ENABLED = old_recovery_enabled
            casm_app.LOCAL_PENDING_RECOVERY_STALE_SECONDS = old_recovery_stale
            casm_app.LOCAL_PENDING_RECOVERY_MAX_ENQUEUE_PER_SWEEP = old_recovery_max
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            casm_app.reset_report_progress()


def test_strict_local_augmented_caption_allows_model_report():
    class RealCaptionGenerator:
        def generate_caption(self, _image_path):
            return (
                "One individual is visible in a bright indoor workspace near stored materials. "
                "The person is facing the camera, and the visual scene does not clearly show "
                "compliant construction PPE from this angle."
            )

    class FakeReportGenerator:
        def __init__(self):
            self.calls = []

        def generate_report(self, report_data):
            self.calls.append(dict(report_data))
            report_dir = Path(report_data["original_image_path"]).parent
            (report_dir / "report.html").write_text("<html>local report complete</html>", encoding="utf-8")
            return {
                "html": "<html>local report complete</html>",
                "storage_keys": {},
            }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_id = "local_caption_augmented_contract_001"
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        frame = casm_app.np.zeros((8, 8, 3), dtype=casm_app.np.uint8)
        original_path = report_dir / "original.jpg"
        annotated_path = report_dir / "annotated.jpg"
        casm_app.cv2.imwrite(str(original_path), frame)
        casm_app.cv2.imwrite(str(annotated_path), frame)

        fake_db = CaptureProcessingDB()
        fake_report_generator = FakeReportGenerator()
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_caption_generator = casm_app.caption_generator
        old_report_generator = casm_app.report_generator
        old_env_validation = casm_app.ENVIRONMENT_VALIDATION_ENABLED
        old_push_realtime = casm_app._push_realtime_report_event
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        old_require_caption = os.environ.get("LOCAL_REPORT_REQUIRE_MODEL_CAPTION")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "local"
            os.environ["LOCAL_REPORT_REQUIRE_MODEL_CAPTION"] = "true"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = fake_db
            casm_app.caption_generator = RealCaptionGenerator()
            casm_app.report_generator = fake_report_generator
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = False
            casm_app._push_realtime_report_event = lambda *_args, **_kwargs: None

            queued = casm_app.QueuedViolation(
                priority=0,
                timestamp=time.time(),
                data={
                    "report_id": report_id,
                    "timestamp": datetime.now(timezone.utc),
                    "detections": [
                        {"class_name": "person", "confidence": 0.91, "bbox": [0, 0, 4, 7]},
                        {"class_name": "no-hardhat", "confidence": 0.87, "bbox": [1, 1, 5, 5]},
                    ],
                    "violation_types": ["no-hardhat"],
                    "violation_count": 1,
                    "original_image_path": str(original_path),
                    "annotated_image_path": str(annotated_path),
                    "violation_dir": str(report_dir),
                    "severity": "HIGH",
                    "source_scope": "local",
                    "sync_source": "local_pipeline",
                    "source": "local_pipeline",
                },
                device_id="offline_local_cache",
                report_id=report_id,
            )

            casm_app.process_queued_violation(queued)

            _assert(fake_report_generator.calls, "Local report generator should run for augmented real caption")
            report_call = fake_report_generator.calls[0]
            _assert(
                report_call.get("caption_quality_reason") == "augmented_yolo_context",
                f"Expected augmented context reason, got {report_call}",
            )
            _assert(
                report_call.get("caption_quality_fallback_applied") is True,
                f"Expected augmentation marker to remain available for provenance: {report_call}",
            )
            _assert(
                "YOLO detection identified" in str(report_call.get("caption") or ""),
                f"Expected YOLO context in report caption: {report_call}",
            )
            _assert((report_dir / "report.html").exists(), "Local augmented-caption report did not finish")
            metadata = json.loads((report_dir / "metadata.json").read_text(encoding="utf-8"))
            _assert(metadata.get("has_report") is True, f"Metadata should mark augmented report ready: {metadata}")
            _assert(
                metadata.get("caption_quality_reason") == "augmented_yolo_context",
                f"Metadata lost augmentation reason: {metadata}",
            )
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.caption_generator = old_caption_generator
            casm_app.report_generator = old_report_generator
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = old_env_validation
            casm_app._push_realtime_report_event = old_push_realtime
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            if old_require_caption is None:
                os.environ.pop("LOCAL_REPORT_REQUIRE_MODEL_CAPTION", None)
            else:
                os.environ["LOCAL_REPORT_REQUIRE_MODEL_CAPTION"] = old_require_caption
            casm_app.reset_report_progress()


def test_strict_local_caption_failure_blocks_detection_only_report():
    class FailingCaptionGenerator:
        def generate_caption(self, _image_path):
            return "ALERT_LOCAL_MODE_UNAVAILABLE: Ollama vision request timed out"

    class FakeReportGenerator:
        def __init__(self):
            self.calls = []

        def generate_report(self, report_data):
            self.calls.append(dict(report_data))
            return {"html": "<html>should not happen</html>"}

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_id = "local_caption_block_contract_001"
        report_dir = root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        frame = casm_app.np.zeros((8, 8, 3), dtype=casm_app.np.uint8)
        original_path = report_dir / "original.jpg"
        annotated_path = report_dir / "annotated.jpg"
        casm_app.cv2.imwrite(str(original_path), frame)
        casm_app.cv2.imwrite(str(annotated_path), frame)

        fake_db = CaptureProcessingDB()
        fake_report_generator = FakeReportGenerator()
        old_violations_dir = casm_app.VIOLATIONS_DIR
        old_db_manager = casm_app.db_manager
        old_caption_generator = casm_app.caption_generator
        old_report_generator = casm_app.report_generator
        old_env_validation = casm_app.ENVIRONMENT_VALIDATION_ENABLED
        old_push_realtime = casm_app._push_realtime_report_event
        old_profile = os.environ.get("CASM_ROUTING_PROFILE")
        old_require_caption = os.environ.get("LOCAL_REPORT_REQUIRE_MODEL_CAPTION")
        try:
            os.environ["CASM_ROUTING_PROFILE"] = "local"
            os.environ["LOCAL_REPORT_REQUIRE_MODEL_CAPTION"] = "true"
            casm_app.VIOLATIONS_DIR = root
            casm_app.db_manager = fake_db
            casm_app.caption_generator = FailingCaptionGenerator()
            casm_app.report_generator = fake_report_generator
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = False
            casm_app._push_realtime_report_event = lambda *_args, **_kwargs: None

            queued = casm_app.QueuedViolation(
                priority=0,
                timestamp=time.time(),
                data={
                    "report_id": report_id,
                    "timestamp": datetime.now(timezone.utc),
                    "detections": [
                        {"class_name": "person", "confidence": 0.91, "bbox": [0, 0, 4, 7]},
                        {"class_name": "no-hardhat", "confidence": 0.87, "bbox": [1, 1, 5, 5]},
                    ],
                    "violation_types": ["no-hardhat"],
                    "violation_count": 1,
                    "original_image_path": str(original_path),
                    "annotated_image_path": str(annotated_path),
                    "violation_dir": str(report_dir),
                    "severity": "HIGH",
                    "source_scope": "local",
                    "sync_source": "local_pipeline",
                    "source": "local_pipeline",
                },
                device_id="offline_local_cache",
                report_id=report_id,
            )

            casm_app.process_queued_violation(queued)

            _assert(not fake_report_generator.calls, "Local report generator should not run with provider-failure caption")
            _assert(not (report_dir / "report.html").exists(), "Detection-only fallback report should not be created")
            metadata = json.loads((report_dir / "metadata.json").read_text(encoding="utf-8"))
            _assert(metadata.get("has_report") is False, f"Metadata should not mark fallback report ready: {metadata}")
            _assert("Local model caption was not available" in str(metadata.get("failure_reason")), metadata)
        finally:
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.db_manager = old_db_manager
            casm_app.caption_generator = old_caption_generator
            casm_app.report_generator = old_report_generator
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = old_env_validation
            casm_app._push_realtime_report_event = old_push_realtime
            if old_profile is None:
                os.environ.pop("CASM_ROUTING_PROFILE", None)
            else:
                os.environ["CASM_ROUTING_PROFILE"] = old_profile
            if old_require_caption is None:
                os.environ.pop("LOCAL_REPORT_REQUIRE_MODEL_CAPTION", None)
            else:
                os.environ["LOCAL_REPORT_REQUIRE_MODEL_CAPTION"] = old_require_caption
            casm_app.reset_report_progress()


def main():
    tests = [
        test_status_endpoint_uses_local_artifacts_during_db_backoff,
        test_cloud_status_keeps_cloud_source_while_local_staging_files_exist,
        test_cloud_violations_list_keeps_cloud_source_while_local_staging_files_exist,
        test_cloud_profile_does_not_promote_backoff_to_local_pipeline,
        test_cloud_status_repairs_stale_synced_local_with_cloud_artifacts_to_cloud,
        test_manual_cloud_reprocess_metadata_removes_stale_local_handoff_markers,
        test_manual_cloud_reprocess_persists_source_scope_repair,
        test_generate_now_repairs_stale_browser_handoff_to_cloud_queue_scope,
        test_pending_reports_repairs_stale_browser_handoff_to_cloud_scope,
        test_report_response_injects_summary_readability_styles_for_legacy_reports,
        test_local_db_status_stays_local_until_reconnect_sync_evidence_exists,
        test_local_db_status_becomes_local_synced_after_reconnect_sync_signal,
        test_auto_reconnect_sync_is_not_deferred_by_local_runtime_profile,
        test_report_source_tag_matrix_preserves_local_and_synced_local_cases,
        test_cloud_enqueue_payload_keeps_cloud_scope_without_browser_handoff,
        test_cloud_queued_generation_finishes_with_cloud_scope_without_supabase_mutation,
        test_local_pending_recovery_preserves_metadata_ppe_labels,
        test_strict_local_augmented_caption_allows_model_report,
        test_strict_local_caption_failure_blocks_detection_only_report,
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
