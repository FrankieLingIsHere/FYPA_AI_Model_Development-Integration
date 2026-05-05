"""
Offline contract test for cloud report start-row persistence.

Cloud reports must create or mark the Supabase detection event as generating
before expensive NLP/report rendering starts, so the frontend does not guess
the report is local while the backend is still blocked.
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.supabase_report_generator import SupabaseReportGenerator


class _FakeDb:
    def __init__(self):
        self.calls = []
        self.conn = None

    def get_detection_event(self, report_id):
        self.calls.append(("get_detection_event", report_id))
        return None

    def insert_detection_event(self, **kwargs):
        self.calls.append(("insert_detection_event", kwargs.get("report_id"), kwargs.get("status")))
        return kwargs.get("report_id")

    def update_progress(self, report_id, stage):
        self.calls.append(("update_progress", report_id, stage))

    def insert_violation(self, **kwargs):
        self.calls.append(("insert_violation", kwargs.get("report_id")))
        return 1

    def log_event(self, **kwargs):
        self.calls.append(("log_event", kwargs.get("report_id")))


class _FakeStorage:
    def upload_violation_artifacts(self, **kwargs):
        return {}


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_detection_event_created_before_parent_generation():
    subject = SupabaseReportGenerator.__new__(SupabaseReportGenerator)
    subject.db_manager = _FakeDb()
    subject.storage_manager = _FakeStorage()
    subject.upload_pdf = False

    def fake_parent_generate(self, report_data):
        self.db_manager.calls.append(("parent_generate_report", report_data.get("report_id")))
        return {
            "html": None,
            "pdf": None,
            "nlp_analysis": {
                "environment_type": "Indoor / Office",
                "visual_evidence": "The scene depicts an indoor / office setting.",
                "provider": "gemini",
                "model": "gemini-test",
            },
        }

    report_data = {
        "report_id": "contract_cloud_001",
        "timestamp": "2026-05-05T12:00:00Z",
        "caption": "One worker is visible near stacked materials.",
        "detections": [{"class_name": "Person", "confidence": 0.91}],
        "person_count": 1,
        "violation_count": 1,
        "severity": "HIGH",
        "source_scope": "cloud",
        "device_id": "webcam_0",
    }

    with patch.object(ReportGenerator, "generate_report", fake_parent_generate):
        SupabaseReportGenerator.generate_report(subject, report_data)

    calls = subject.db_manager.calls
    insert_index = next(i for i, call in enumerate(calls) if call[0] == "insert_detection_event")
    parent_index = next(i for i, call in enumerate(calls) if call[0] == "parent_generate_report")

    _assert(insert_index < parent_index, f"Detection event was not inserted before parent generation: {calls}")
    _assert(calls[insert_index][2] == "generating", "Initial detection event must be generating")


def main():
    tests = [test_detection_event_created_before_parent_generation]
    failures = []
    for test_fn in tests:
        try:
            test_fn()
            print(f"PASS: {test_fn.__name__}")
        except Exception as exc:
            failures.append((test_fn.__name__, str(exc)))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    if failures:
        print("Supabase report start-row contract test failed")
        raise SystemExit(1)

    print("Supabase report start-row contract test passed")


if __name__ == "__main__":
    main()
