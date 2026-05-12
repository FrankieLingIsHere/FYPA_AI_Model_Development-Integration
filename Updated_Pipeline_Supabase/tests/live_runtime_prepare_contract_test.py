"""
Contract tests for first-run live/runtime preparation improvements.

These tests stay lightweight:
- the live prepare endpoint must surface the backend prep payload
- enqueue_violation must persist an already-annotated frame instead of forcing
  the queue worker to rerun YOLO later
"""

import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_live_prepare_contract_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_live_prepare_contract_ultralytics")
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


class CaptureQueue:
    def __init__(self):
        self.last_payload = None

    def enqueue(self, violation_data, device_id=None, report_id=None, severity=None, expedite=False):
        self.last_payload = {
            "violation_data": violation_data,
            "device_id": device_id,
            "report_id": report_id,
            "severity": severity,
            "expedite": expedite,
        }
        return True

    def get_stats(self):
        return {"current_size": 1, "capacity": 100}


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_live_prepare_endpoint_returns_backend_prep_payload():
    old_gate = casm_app._startup_gate_response
    old_prepare = casm_app._prepare_live_runtime
    try:
        casm_app._startup_gate_response = lambda: None
        casm_app._prepare_live_runtime = lambda **kwargs: {
            "success": True,
            "pipeline_ready": True,
            "queue_worker_ready": True,
            "yolo_ready": True,
            "elapsed_ms": 12.3,
        }

        with casm_app.app.test_client() as client:
            response = client.post("/api/live/prepare", json={"reason": "contract-test"})
            payload = response.get_json() or {}

        _assert(response.status_code == 200, f"Unexpected status code: {response.status_code}")
        _assert(payload.get("success") is True, f"Prepare success missing: {payload}")
        _assert(payload.get("prepared", {}).get("yolo_ready") is True, f"YOLO warmup not surfaced: {payload}")
    finally:
        casm_app._startup_gate_response = old_gate
        casm_app._prepare_live_runtime = old_prepare


def test_enqueue_violation_persists_precomputed_annotated_frame():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    annotated = frame.copy()
    cv2.rectangle(annotated, (20, 20), (90, 100), (0, 255, 0), 2)
    detections = [
        {
            "class_name": "person",
            "bbox": [18, 18, 92, 102],
            "score": 0.98,
        },
        {
            "class_name": "NO-Hardhat",
            "bbox": [24, 22, 70, 54],
            "score": 0.93,
        },
    ]

    fake_queue = CaptureQueue()
    old_dir = casm_app.VIOLATIONS_DIR
    old_queue = casm_app.violation_queue
    old_db = casm_app.db_manager
    old_cooldown = casm_app.VIOLATION_COOLDOWN
    old_last_violation = casm_app.last_violation_time
    old_ensure_worker = casm_app.ensure_queue_worker_running
    old_local_runtime_fn = casm_app._is_local_pipeline_runtime_active

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            casm_app.VIOLATIONS_DIR = Path(tmpdir)
            casm_app.violation_queue = fake_queue
            casm_app.db_manager = None
            casm_app.VIOLATION_COOLDOWN = 0
            casm_app.last_violation_time = 0
            casm_app.ensure_queue_worker_running = lambda: True
            casm_app._is_local_pipeline_runtime_active = lambda: False

            report_id = casm_app.enqueue_violation(
                frame,
                detections,
                trigger_source="upload",
                annotated_frame=annotated,
            )

            _assert(report_id, "enqueue_violation did not return a report id")
            report_dir = Path(tmpdir) / str(report_id)
            metadata_path = report_dir / "metadata.json"
            annotated_path = report_dir / "annotated.jpg"

            _assert(annotated_path.exists(), "Annotated frame was not persisted at capture time")
            _assert(metadata_path.exists(), "Metadata file missing after enqueue")

            metadata = casm_app.json.loads(metadata_path.read_text(encoding="utf-8"))
            _assert(metadata.get("has_annotated") is True, f"Metadata did not preserve has_annotated: {metadata}")

            queued_data = (fake_queue.last_payload or {}).get("violation_data") or {}
            _assert(
                str(queued_data.get("annotated_image_path", "")).endswith("annotated.jpg"),
                f"Queued payload missing annotated path: {queued_data}",
            )
        finally:
            casm_app.VIOLATIONS_DIR = old_dir
            casm_app.violation_queue = old_queue
            casm_app.db_manager = old_db
            casm_app.VIOLATION_COOLDOWN = old_cooldown
            casm_app.last_violation_time = old_last_violation
            casm_app.ensure_queue_worker_running = old_ensure_worker
            casm_app._is_local_pipeline_runtime_active = old_local_runtime_fn


def main():
    tests = [
        test_live_prepare_endpoint_returns_backend_prep_payload,
        test_enqueue_violation_persists_precomputed_annotated_frame,
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
        raise SystemExit(1)

    print("Live runtime prepare contract test passed")


if __name__ == "__main__":
    main()
