"""
Offline contract tests for live-monitor flood backpressure.

These tests deliberately avoid Supabase, hosted endpoints, cameras, and real
model providers. They exercise the local hot paths with fakes so continuous
camera detections cannot bypass queue limits or multiply model calls.
"""

import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_live_flood_contract_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_live_flood_contract_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)
os.environ.setdefault("CASM_ROUTING_PROFILE", "local")
os.environ.setdefault("SUPABASE_DB_URL", "postgres://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://projtest123.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-test-key")
os.environ.setdefault("REPORT_GENERATION_TIMEOUT_SECONDS", "30")

import infer_image
import casm_app
from pipeline.backend.core.violation_queue import QueuedViolation, ViolationQueueManager
from threading import Semaphore


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _moving_live_detections(index: int):
    x1 = 20 + (index * 80)
    return [
        {
            "class_name": "person",
            "bbox": [x1 - 4, 18, x1 + 58, 138],
            "score": 0.98,
        },
        {
            "class_name": "NO-Hardhat",
            "bbox": [x1, 24, x1 + 42, 92],
            "score": 0.94,
            "confidence": 0.94,
        },
    ]


def test_live_capture_flood_respects_device_rate_limit_without_fallback_bypass():
    frame = np.zeros((180, 240, 3), dtype=np.uint8)
    queue = ViolationQueueManager(max_size=50, rate_limit_per_device=3, rate_limit_window=60)

    old_dir = casm_app.VIOLATIONS_DIR
    old_queue = casm_app.violation_queue
    old_db = casm_app.db_manager
    old_cooldown = casm_app.VIOLATION_COOLDOWN
    old_last_violation = casm_app.last_violation_time
    old_ensure_worker = casm_app.ensure_queue_worker_running
    old_local_runtime_fn = casm_app._is_local_pipeline_runtime_active
    old_get_local_time = casm_app.get_local_time

    base_time = datetime(2026, 5, 18, 9, 0, 0, tzinfo=timezone.utc)
    tick = {"value": 0}

    def fake_local_time():
        current = base_time + timedelta(seconds=tick["value"])
        tick["value"] += 1
        return current

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            casm_app.VIOLATIONS_DIR = Path(tmpdir)
            casm_app.violation_queue = queue
            casm_app.db_manager = None
            casm_app.VIOLATION_COOLDOWN = 0
            casm_app.last_violation_time = 0
            casm_app.ensure_queue_worker_running = lambda: True
            casm_app._is_local_pipeline_runtime_active = lambda: False
            casm_app.get_local_time = fake_local_time
            with casm_app.recent_live_violation_lock:
                casm_app.recent_live_violation_signatures.clear()

            accepted = []
            for idx in range(12):
                report_id = casm_app.enqueue_violation(
                    frame.copy(),
                    _moving_live_detections(idx),
                    trigger_source="live",
                    annotated_frame=frame.copy(),
                )
                if report_id:
                    accepted.append(str(report_id))

            stats = queue.get_stats()
            preview = queue.get_queue_preview(limit=20)
            created_dirs = [item for item in Path(tmpdir).iterdir() if item.is_dir()]

            _assert(len(accepted) == 3, f"live flood bypassed rate limit; accepted={accepted}")
            _assert(stats.get("total_enqueued") == 3, f"unexpected enqueue stats: {stats}")
            _assert(stats.get("current_size") == 3, f"unexpected queue size: {stats}")
            _assert(stats.get("total_rate_limited", 0) >= 1, f"rate limiter did not trip: {stats}")
            _assert(
                len(created_dirs) == 3,
                f"rate-limited live flood wrote extra report folders: {[p.name for p in created_dirs]}",
            )
            _assert(
                all(item.get("device_id") == "webcam_0" for item in preview),
                f"live flood used fallback device ids instead of backpressure: {preview}",
            )
        finally:
            casm_app.VIOLATIONS_DIR = old_dir
            casm_app.violation_queue = old_queue
            casm_app.db_manager = old_db
            casm_app.VIOLATION_COOLDOWN = old_cooldown
            casm_app.last_violation_time = old_last_violation
            casm_app.ensure_queue_worker_running = old_ensure_worker
            casm_app._is_local_pipeline_runtime_active = old_local_runtime_fn
            casm_app.get_local_time = old_get_local_time
            with casm_app.recent_live_violation_lock:
                casm_app.recent_live_violation_signatures.clear()


class _FakeYoloModel:
    def __init__(self):
        self.names = {}
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def predict(self, *_args, **_kwargs):
        with self.lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return []
        finally:
            with self.lock:
                self.active -= 1


def test_yolo_model_calls_are_serialized_under_local_request_flood():
    fake_model = _FakeYoloModel()
    old_resolve = infer_image.resolve_model_path
    old_ensure = infer_image._ensure_model_loaded
    old_semaphore = infer_image._yolo_predict_semaphore

    try:
        infer_image.resolve_model_path = lambda model_path=None: "fake-yolo.pt"
        infer_image._ensure_model_loaded = lambda resolved_model_path: fake_model
        infer_image._yolo_predict_semaphore = Semaphore(1)

        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(lambda _: infer_image.predict_image(frame), range(5)))

        _assert(fake_model.calls == 5, f"expected 5 fake YOLO calls, got {fake_model.calls}")
        _assert(fake_model.max_active == 1, f"YOLO calls overlapped under flood: {fake_model.max_active}")
    finally:
        infer_image.resolve_model_path = old_resolve
        infer_image._ensure_model_loaded = old_ensure
        infer_image._yolo_predict_semaphore = old_semaphore


class _FakeCaptionGenerator:
    def generate_caption(self, image_path):
        return f"Construction worker missing hardhat near equipment: {Path(image_path).name}"


class _FakeReportGenerator:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []

    def generate_report(self, report_data):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(report_data.get("report_id"))
        try:
            time.sleep(0.08)
            report_dir = Path(report_data["original_image_path"]).parent
            report_html = report_dir / "report.html"
            report_html.write_text(
                f"<html><body>offline report {report_data.get('report_id')}</body></html>",
                encoding="utf-8",
            )
            return {
                "html": str(report_html),
                "nlp_analysis": {"provider": "offline_fake", "model": "fake-report-model"},
            }
        finally:
            with self.lock:
                self.active -= 1


def _build_queued_violation(tmpdir: str, index: int) -> QueuedViolation:
    report_id = f"model-flood-{index:03d}"
    report_dir = Path(tmpdir) / report_id
    report_dir.mkdir(parents=True, exist_ok=True)

    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    original = report_dir / "original.jpg"
    annotated = report_dir / "annotated.jpg"
    cv2.imwrite(str(original), frame)
    cv2.imwrite(str(annotated), frame)

    detections = _moving_live_detections(index)
    return QueuedViolation(
        priority=0,
        timestamp=time.time(),
        data={
            "report_id": report_id,
            "timestamp": datetime(2026, 5, 18, 10, 0, index, tzinfo=timezone.utc).isoformat(),
            "detections": detections,
            "violation_types": ["NO-Hardhat"],
            "violation_count": 1,
            "original_image_path": str(original),
            "annotated_image_path": str(annotated),
            "violation_dir": str(report_dir),
            "severity": "HIGH",
            "source_scope": "cloud",
            "sync_source": "live_capture",
            "source": "live_capture",
        },
        device_id="webcam_0",
        report_id=report_id,
    )


def test_report_model_calls_are_serialized_under_parallel_queue_pressure():
    fake_caption = _FakeCaptionGenerator()
    fake_report = _FakeReportGenerator()

    old_caption = casm_app.caption_generator
    old_report = casm_app.report_generator
    old_db = casm_app.db_manager
    old_local_runtime_fn = casm_app._is_local_pipeline_runtime_active
    old_environment_validation = casm_app.ENVIRONMENT_VALIDATION_ENABLED
    old_report_semaphore = casm_app.report_generation_semaphore

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            casm_app.caption_generator = fake_caption
            casm_app.report_generator = fake_report
            casm_app.db_manager = None
            casm_app._is_local_pipeline_runtime_active = lambda: False
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = False
            casm_app.report_generation_semaphore = Semaphore(1)

            queued = [_build_queued_violation(tmpdir, idx) for idx in range(4)]
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(casm_app.process_queued_violation, queued))

            _assert(len(fake_report.calls) == 4, f"not all fake report calls ran: {fake_report.calls}")
            _assert(fake_report.max_active == 1, f"report model calls overlapped: {fake_report.max_active}")
            for item in queued:
                report_path = Path(item.data["violation_dir"]) / "report.html"
                _assert(report_path.exists(), f"report was not created: {report_path}")
        finally:
            casm_app.caption_generator = old_caption
            casm_app.report_generator = old_report
            casm_app.db_manager = old_db
            casm_app._is_local_pipeline_runtime_active = old_local_runtime_fn
            casm_app.ENVIRONMENT_VALIDATION_ENABLED = old_environment_validation
            casm_app.report_generation_semaphore = old_report_semaphore


def main():
    tests = [
        test_live_capture_flood_respects_device_rate_limit_without_fallback_bypass,
        test_yolo_model_calls_are_serialized_under_local_request_flood,
        test_report_model_calls_are_serialized_under_parallel_queue_pressure,
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

    print("Live flood backpressure contract test passed")


if __name__ == "__main__":
    main()
