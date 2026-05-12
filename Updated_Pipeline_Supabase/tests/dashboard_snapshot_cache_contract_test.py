"""
Contract test for short-lived dashboard snapshot caches.

Repeated /api/violations and /api/stats polls should be able to reuse a fresh
in-memory payload briefly instead of rebuilding from the DB every time.
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_dashboard_cache_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_dashboard_cache_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)

import casm_app


class _FakeDashboardDB:
    def __init__(self):
        self.calls = 0

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


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_dashboard_endpoints_reuse_short_lived_snapshot_cache():
    fake_db = _FakeDashboardDB()

    old_db_manager = casm_app.db_manager
    old_violations_dir = casm_app.VIOLATIONS_DIR
    old_violation_ttl = casm_app.VIOLATIONS_SNAPSHOT_CACHE_TTL_SECONDS
    old_stats_ttl = casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            casm_app.db_manager = fake_db
            casm_app.VIOLATIONS_DIR = Path(tmpdir)
            casm_app.VIOLATIONS_SNAPSHOT_CACHE_TTL_SECONDS = 60.0
            casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS = 60.0
            casm_app._invalidate_dashboard_snapshot_cache()
            casm_app._invalidate_local_report_state_cache()

            with casm_app.app.test_client() as client:
                first_violations = client.get("/api/violations?limit=50")
                second_violations = client.get("/api/violations?limit=50")
                first_stats = client.get("/api/stats")
                second_stats = client.get("/api/stats")

            _assert(first_violations.status_code == 200, "First /api/violations call failed")
            _assert(second_violations.status_code == 200, "Second /api/violations call failed")
            _assert(first_stats.status_code == 200, "First /api/stats call failed")
            _assert(second_stats.status_code == 200, "Second /api/stats call failed")
            _assert(
                fake_db.calls == 2,
                f"Expected one DB rebuild per endpoint family, got calls={fake_db.calls}",
            )
        finally:
            casm_app.db_manager = old_db_manager
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.VIOLATIONS_SNAPSHOT_CACHE_TTL_SECONDS = old_violation_ttl
            casm_app.STATS_SNAPSHOT_CACHE_TTL_SECONDS = old_stats_ttl
            casm_app._invalidate_dashboard_snapshot_cache()
            casm_app._invalidate_local_report_state_cache()


def main():
    try:
        test_dashboard_endpoints_reuse_short_lived_snapshot_cache()
        print("PASS: test_dashboard_endpoints_reuse_short_lived_snapshot_cache")
    except Exception as exc:
        print(f"FAIL: test_dashboard_endpoints_reuse_short_lived_snapshot_cache: {exc}")
        raise SystemExit(1)

    print("Dashboard snapshot cache contract test passed")


if __name__ == "__main__":
    main()
