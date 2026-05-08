"""
Offline regression tests for caption fallback contagion.

Real model captions must not be overwritten by the deterministic
detection-only template. Only hard provider failures should use that template.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_caption_contract_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_caption_contract_ultralytics")
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

from casm_app import _enforce_caption_quality_floor
from caption_image import _caption_needs_expansion, _normalize_caption_text
from pipeline.backend.integration.caption_generator import CaptionGenerator
from pipeline.backend.core.report_generator import ReportGenerator


DETECTIONS = [
    {"class_name": "Person", "confidence": 0.91, "bbox": [12, 34, 120, 240]},
    {"class_name": "NO-Hardhat", "confidence": 0.83, "bbox": [22, 40, 90, 110]},
    {"class_name": "NO-Safety Vest", "confidence": 0.76, "bbox": [18, 90, 118, 210]},
]


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_casm_caption_quality_augments_short_real_caption():
    raw_caption = "Worker beside materials without visible head protection."

    caption, applied, reason = _enforce_caption_quality_floor(
        raw_caption,
        DETECTIONS,
        violation_types=["NO-Hardhat", "NO-Safety Vest"],
    )

    _assert(applied is True, "Expected short caption to be augmented with YOLO context")
    _assert(reason == "augmented_too_short", f"Unexpected reason: {reason}")
    _assert(caption.startswith(raw_caption), "Expected original model caption to remain first")
    _assert("YOLO detection identified 1 person(s)" in caption, "Expected YOLO addendum")
    _assert("Auto-generated safety summary" not in caption, "Legacy fallback template leaked")


def test_casm_caption_quality_adds_yolo_context_to_rich_caption():
    raw_caption = (
        "One individual is visible from the chest up in an indoor office setting. "
        "The person is wearing glasses and a dark jacket while facing the camera. "
        "No compliant construction PPE is clearly visible in the frame."
    )

    caption, applied, reason = _enforce_caption_quality_floor(
        raw_caption,
        DETECTIONS,
        violation_types=["NO-Hardhat", "NO-Safety Vest"],
    )

    _assert(applied is True, "Expected rich VLM caption to receive YOLO addendum")
    _assert(reason == "augmented_yolo_context", f"Unexpected reason: {reason}")
    _assert(caption.startswith(raw_caption), "Expected original rich model caption to remain first")
    _assert(
        "YOLO detection identified 1 person(s) in the frame with the following PPE deficiencies: "
        "Missing Hard Hat, Missing Safety Vest." in caption,
        "Expected exact YOLO deficiencies addendum",
    )
    _assert(not caption.startswith("Detection-only safety summary:"), "Real caption was replaced by fallback")


def test_casm_caption_quality_does_not_duplicate_existing_yolo_context():
    raw_caption = (
        "One individual is visible in an indoor office setting. "
        "YOLO detection identified 1 person(s) in the frame with the following PPE deficiencies: "
        "Missing Hard Hat, Missing Safety Vest."
    )

    caption, applied, reason = _enforce_caption_quality_floor(
        raw_caption,
        DETECTIONS,
        violation_types=["NO-Hardhat", "NO-Safety Vest"],
    )

    _assert(applied is False, "Existing YOLO context should not be augmented again")
    _assert(reason == "", f"Unexpected reason: {reason}")
    _assert(caption.count("YOLO detection identified") == 1, "YOLO addendum was duplicated")


def test_casm_caption_quality_replaces_provider_failure_only():
    caption, applied, reason = _enforce_caption_quality_floor(
        "Image captioning not available - Gemini API key not configured",
        DETECTIONS,
        violation_types=["NO-Hardhat"],
    )

    _assert(applied is True, "Expected provider failure to use detection-only fallback")
    _assert(reason == "image captioning not available", f"Unexpected reason: {reason}")
    _assert(caption.startswith("Detection-only safety summary:"), "Expected explicit detection-only fallback")


def test_report_generator_keeps_non_placeholder_caption():
    subject = ReportGenerator.__new__(ReportGenerator)
    report_data = {
        "caption": "A worker stands beside stacked materials without visible head protection.",
        "detections": DETECTIONS,
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 1,
    }

    caption = subject._ensure_caption_quality_floor(report_data)

    _assert(caption == report_data["caption"], "ReportGenerator should not overwrite real VLM captions")


def test_caption_generator_image_path_does_not_shadow_os_module():
    subject = CaptionGenerator.__new__(CaptionGenerator)
    subject.config = {"GEMINI_CONFIG": {"enabled": False}}
    subject.backend = "none"
    subject.model_loaded = False
    subject._gemini_client = None

    caption = subject.generate_caption("nonexistent-test-image.jpg")

    _assert("Image captioning not available" in caption, "Expected graceful caption backend unavailable response")


def test_caption_cleanup_removes_model_preamble_without_forcing_expansion():
    raw = (
        "Here's a descriptive paragraph based on the image, adhering to your requirements: "
        "There is one person visible in this indoor setting. The individual is wearing glasses "
        "and a gray jacket in a room with white walls and green ceiling panels. No personal "
        "protective equipment is visible."
    )

    cleaned = _normalize_caption_text(raw)

    _assert(cleaned.startswith("There is one person visible"), "Expected model preamble to be removed")
    _assert("Here's" not in cleaned, "Caption cleanup left model preamble")
    _assert(_caption_needs_expansion(cleaned) is False, "Detailed indoor caption should not be expanded again")


def main():
    tests = [
        test_casm_caption_quality_augments_short_real_caption,
        test_casm_caption_quality_adds_yolo_context_to_rich_caption,
        test_casm_caption_quality_does_not_duplicate_existing_yolo_context,
        test_casm_caption_quality_replaces_provider_failure_only,
        test_report_generator_keeps_non_placeholder_caption,
        test_caption_generator_image_path_does_not_shadow_os_module,
        test_caption_cleanup_removes_model_preamble_without_forcing_expansion,
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
        print("Caption fallback contagion contract test failed")
        raise SystemExit(1)

    print("Caption fallback contagion contract test passed")


if __name__ == "__main__":
    main()
