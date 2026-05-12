"""
Contract test for the optimized report status bundle path.

When the DB manager can provide a combined report-status bundle, the status API
should avoid separate detection_event and violation lookups.
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_report_status_bundle_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_report_status_bundle_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)
os.environ.setdefault("CASM_ROUTING_PROFILE", "cloud")

import casm_app


class BundleOnlyDB:
    def __init__(self):
        self.bundle_calls = 0
        self.event_calls = 0
        self.violation_calls = 0

    def get_report_status_bundle(self, report_id):
        self.bundle_calls += 1
        now = datetime.now(timezone.utc)
        return {
            "report_id": report_id,
            "event_timestamp": now,
            "event_updated_at": now,
            "person_count": 1,
            "violation_count": 1,
            "severity": "HIGH",
            "event_status": "generating",
            "event_error_message": None,
            "event_device_id": "webcam_0",
            "violation_id": "vio-1",
            "violation_summary": "PPE Violation Detected: NO-Hardhat",
            "caption": "Worker missing hardhat near scaffold.",
            "nlp_analysis": None,
            "detection_data": {
                "source_scope": "cloud",
                "source": "cloud_live",
            },
            "original_image_key": f"violations/{report_id}/original.jpg",
            "annotated_image_key": None,
            "report_html_key": None,
            "report_pdf_key": None,
            "violation_device_id": "webcam_0",
        }

    def get_detection_event(self, report_id):
        self.event_calls += 1
        raise AssertionError("Separate get_detection_event should not be used when bundle is available")

    def get_violation(self, report_id):
        self.violation_calls += 1
        raise AssertionError("Separate get_violation should not be used when bundle is available")


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_report_status_prefers_combined_bundle_lookup():
    fake_db = BundleOnlyDB()
    report_id = "20260512_174500"

    old_db_manager = casm_app.db_manager
    old_violations_dir = casm_app.VIOLATIONS_DIR

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            casm_app.db_manager = fake_db
            casm_app.VIOLATIONS_DIR = Path(tmpdir)

            with casm_app.app.test_client() as client:
                response = client.get(f"/api/report/{report_id}/status")
                payload = response.get_json() or {}

            _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
            _assert(payload.get("status") == "generating", f"Unexpected payload: {payload}")
            _assert(payload.get("source_scope") == "cloud", f"Cloud source scope missing: {payload}")
            _assert(fake_db.bundle_calls == 1, f"Bundle lookup count incorrect: {fake_db.bundle_calls}")
            _assert(fake_db.event_calls == 0, f"Separate event lookups used: {fake_db.event_calls}")
            _assert(fake_db.violation_calls == 0, f"Separate violation lookups used: {fake_db.violation_calls}")
        finally:
            casm_app.db_manager = old_db_manager
            casm_app.VIOLATIONS_DIR = old_violations_dir


def main():
    try:
        test_report_status_prefers_combined_bundle_lookup()
        print("PASS: test_report_status_prefers_combined_bundle_lookup")
    except Exception as exc:
        print(f"FAIL: test_report_status_prefers_combined_bundle_lookup: {exc}")
        raise SystemExit(1)

    print("Report status bundle contract test passed")


if __name__ == "__main__":
    main()
