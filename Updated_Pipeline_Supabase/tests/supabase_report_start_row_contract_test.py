"""
Offline contract test for cloud report start-row persistence.

Cloud reports must create or mark the Supabase detection event as generating
before expensive NLP/report rendering starts, so the frontend does not guess
the report is local while the backend is still blocked.
"""
# Readability: Test setup: document the contract this file protects.

import sys
from pathlib import Path
from unittest.mock import patch

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.supabase_report_generator import SupabaseReportGenerator


# Section: group fake db state and behaviour in one readable unit.
class _FakeDb:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self):
        # Prepare calls for the next step.
        self.calls = []
        self.conn = None

    # Section: run the get detection event workflow with clear inputs and outputs.
    def get_detection_event(self, report_id):
        self.calls.append(("get_detection_event", report_id))
        return None

    # Section: run the insert detection event workflow with clear inputs and outputs.
    def insert_detection_event(self, **kwargs):
        self.calls.append(("insert_detection_event", kwargs.get("report_id"), kwargs.get("status")))
        # Return the prepared result to the caller.
        return kwargs.get("report_id")

    # Section: run the update progress workflow with clear inputs and outputs.
    def update_progress(self, report_id, stage):
        self.calls.append(("update_progress", report_id, stage))

    # Section: run the insert violation workflow with clear inputs and outputs.
    def insert_violation(self, **kwargs):
        self.calls.append(("insert_violation", kwargs.get("report_id")))
        return 1

    # Section: run the log event workflow with clear inputs and outputs.
    def log_event(self, **kwargs):
        # Trigger the side effect required for this stage.
        self.calls.append(("log_event", kwargs.get("report_id")))


# Section: group fake storage state and behaviour in one readable unit.
class _FakeStorage:
    # Section: run the upload violation artifacts workflow with clear inputs and outputs.
    def upload_violation_artifacts(self, **kwargs):
        return {}


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test detection event created before parent generation workflow with clear inputs and outputs.
def test_detection_event_created_before_parent_generation():
    # Prepare subject for the next step.
    subject = SupabaseReportGenerator.__new__(SupabaseReportGenerator)
    subject.db_manager = _FakeDb()
    subject.storage_manager = _FakeStorage()
    subject.upload_pdf = False

    # Section: run the fake parent generate workflow with clear inputs and outputs.
    def fake_parent_generate(self, report_data):
        # Trigger the side effect required for this stage.
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

    # Prepare report data for the next step.
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

    # Open the managed resource only for the block that needs it.
    with patch.object(ReportGenerator, "generate_report", fake_parent_generate):
        # Trigger the side effect required for this stage.
        SupabaseReportGenerator.generate_report(subject, report_data)

    calls = subject.db_manager.calls
    insert_index = next(i for i, call in enumerate(calls) if call[0] == "insert_detection_event")
    parent_index = next(i for i, call in enumerate(calls) if call[0] == "parent_generate_report")

    _assert(insert_index < parent_index, f"Detection event was not inserted before parent generation: {calls}")
    _assert(calls[insert_index][2] == "generating", "Initial detection event must be generating")


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Prepare tests for the next step.
    tests = [test_detection_event_created_before_parent_generation]
    failures = []
    for test_fn in tests:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Trigger the side effect required for this stage.
            test_fn()
            print(f"PASS: {test_fn.__name__}")
        except Exception as exc:
            failures.append((test_fn.__name__, str(exc)))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    # Choose the correct branch before the workflow continues.
    if failures:
        print("Supabase report start-row contract test failed")
        # Surface the failure with enough context for the caller.
        raise SystemExit(1)

    print("Supabase report start-row contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
