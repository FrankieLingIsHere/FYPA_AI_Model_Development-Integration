"""
Offline regression tests for caption fallback contagion.

Real model captions must not be overwritten by the deterministic
detection-only template. Only hard provider failures should use that template.
"""
# Readability: Test setup: document the contract this file protects.

import os
import sys
import tempfile
from pathlib import Path

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_caption_contract_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_caption_contract_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
# Trigger the side effect required for this stage.
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)
os.environ.setdefault("SUPABASE_DB_URL", "postgres://test:test@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://projtest123.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-test-key")

from casm_app import _caption_quality_reason_blocks_model_report, _enforce_caption_quality_floor
from caption_image import _caption_needs_expansion, _normalize_caption_text
from pipeline.backend.integration.caption_generator import CaptionGenerator
from pipeline.backend.core.report_generator import ReportGenerator


# Prepare detections for the next step.
DETECTIONS = [
    {"class_name": "Person", "confidence": 0.91, "bbox": [12, 34, 120, 240]},
    {"class_name": "NO-Hardhat", "confidence": 0.83, "bbox": [22, 40, 90, 110]},
    {"class_name": "NO-Safety Vest", "confidence": 0.76, "bbox": [18, 90, 118, 210]},
]


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test casm caption quality augments short real caption workflow with clear inputs and outputs.
def test_casm_caption_quality_augments_short_real_caption():
    raw_caption = "Worker beside materials without visible head protection."

    caption, applied, reason = _enforce_caption_quality_floor(
        raw_caption,
        DETECTIONS,
        violation_types=["NO-Hardhat", "NO-Safety Vest"],
    )

    # Trigger the side effect required for this stage.
    _assert(applied is True, "Expected short caption to be augmented with YOLO context")
    _assert(reason == "augmented_too_short", f"Unexpected reason: {reason}")
    _assert(caption.startswith(raw_caption), "Expected original model caption to remain first")
    _assert("YOLO detection identified 1 person(s)" in caption, "Expected YOLO addendum")
    _assert("Auto-generated safety summary" not in caption, "Legacy fallback template leaked")


# Section: run the test casm caption quality adds yolo context to rich caption workflow with clear inputs and outputs.
def test_casm_caption_quality_adds_yolo_context_to_rich_caption():
    raw_caption = (
        "One individual is visible from the chest up in an indoor office setting. "
        "The person is wearing glasses and a dark jacket while facing the camera. "
        "No compliant construction PPE is clearly visible in the frame."
    )

    # Prepare values needed by the next step.
    caption, applied, reason = _enforce_caption_quality_floor(
        raw_caption,
        DETECTIONS,
        violation_types=["NO-Hardhat", "NO-Safety Vest"],
    )

    _assert(applied is True, "Expected rich VLM caption to receive YOLO addendum")
    _assert(reason == "augmented_yolo_context", f"Unexpected reason: {reason}")
    _assert(caption.startswith(raw_caption), "Expected original rich model caption to remain first")
    # Trigger the side effect required for this stage.
    _assert(
        "YOLO detection identified 1 person(s) in the frame with the following PPE deficiencies: "
        "Missing Hard Hat, Missing Safety Vest." in caption,
        "Expected exact YOLO deficiencies addendum",
    )
    _assert(not caption.startswith("Detection-only safety summary:"), "Real caption was replaced by fallback")


# Section: run the test casm caption quality does not duplicate existing yolo context workflow with clear inputs and outputs.
def test_casm_caption_quality_does_not_duplicate_existing_yolo_context():
    # Prepare raw caption for the next step.
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

    # Trigger the side effect required for this stage.
    _assert(applied is False, "Existing YOLO context should not be augmented again")
    _assert(reason == "", f"Unexpected reason: {reason}")
    _assert(caption.count("YOLO detection identified") == 1, "YOLO addendum was duplicated")


# Section: run the test casm caption quality replaces provider failure only workflow with clear inputs and outputs.
def test_casm_caption_quality_replaces_provider_failure_only():
    caption, applied, reason = _enforce_caption_quality_floor(
        "Image captioning not available - Gemini API key not configured",
        DETECTIONS,
        violation_types=["NO-Hardhat"],
    )

    # Trigger the side effect required for this stage.
    _assert(applied is True, "Expected provider failure to use detection-only fallback")
    _assert(reason == "image captioning not available", f"Unexpected reason: {reason}")
    _assert(caption.startswith("Detection-only safety summary:"), "Expected explicit detection-only fallback")


# Section: run the test augmented caption reason does not block strict local report workflow with clear inputs and outputs.
def test_augmented_caption_reason_does_not_block_strict_local_report():
    _assert(
        _caption_quality_reason_blocks_model_report("augmented_yolo_context") is False,
        "YOLO addendum must not be treated as provider failure",
    )
    # Trigger the side effect required for this stage.
    _assert(
        _caption_quality_reason_blocks_model_report("augmented_too_short") is False,
        "Short real captions with YOLO context should still reach report generation",
    )


# Section: run the test provider failure caption reason blocks strict local report workflow with clear inputs and outputs.
def test_provider_failure_caption_reason_blocks_strict_local_report():
    _assert(
        _caption_quality_reason_blocks_model_report("image captioning not available") is True,
        "Provider-unavailable captions must keep blocking detection-only local reports",
    )
    # Trigger the side effect required for this stage.
    _assert(
        _caption_quality_reason_blocks_model_report("empty_caption") is True,
        "Empty captions must keep blocking strict local reports",
    )


# Section: run the test report generator keeps non placeholder caption workflow with clear inputs and outputs.
def test_report_generator_keeps_non_placeholder_caption():
    subject = ReportGenerator.__new__(ReportGenerator)
    report_data = {
        "caption": "A worker stands beside stacked materials without visible head protection.",
        "detections": DETECTIONS,
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 1,
    }

    # Prepare caption for the next step.
    caption = subject._ensure_caption_quality_floor(report_data)

    _assert(caption == report_data["caption"], "ReportGenerator should not overwrite real VLM captions")


# Section: run the test caption generator image path does not shadow os module workflow with clear inputs and outputs.
def test_caption_generator_image_path_does_not_shadow_os_module():
    subject = CaptionGenerator.__new__(CaptionGenerator)
    subject.config = {"GEMINI_CONFIG": {"enabled": False}}
    subject.backend = "none"
    # Prepare model loaded for the next step.
    subject.model_loaded = False
    subject._gemini_client = None

    caption = subject.generate_caption("nonexistent-test-image.jpg")

    _assert("Image captioning not available" in caption, "Expected graceful caption backend unavailable response")


# Section: run the test caption generator status uses active gemini vision model workflow with clear inputs and outputs.
def test_caption_generator_status_uses_active_gemini_vision_model():
    # Section: group fake gemini client state and behaviour in one readable unit.
    class _FakeGeminiClient:
        # Section: run the get status workflow with clear inputs and outputs.
        def get_status(self):
            # Return the prepared result to the caller.
            return {
                "vision_model": "gemini-flash-lite-latest",
                "model": "gemini-2.5-flash",
            }

    subject = CaptionGenerator.__new__(CaptionGenerator)
    subject.config = {"GEMINI_CONFIG": {"enabled": True}}
    # Prepare backend for the next step.
    subject.backend = "gemini"
    subject.model_loaded = True
    subject._gemini_client = _FakeGeminiClient()

    status = subject.get_status()

    _assert(status["model"] == "gemini-flash-lite-latest", status)
    _assert(status["gemini_status"]["vision_model"] == "gemini-flash-lite-latest", status)


# Section: run the test caption cleanup removes model preamble without forcing expansion workflow with clear inputs and outputs.
def test_caption_cleanup_removes_model_preamble_without_forcing_expansion():
    # Prepare raw for the next step.
    raw = (
        "Here's a descriptive paragraph based on the image, adhering to your requirements: "
        "There is one person visible in this indoor setting. The individual is wearing glasses "
        "and a gray jacket in a room with white walls and green ceiling panels. No personal "
        "protective equipment is visible."
    )

    cleaned = _normalize_caption_text(raw)

    # Trigger the side effect required for this stage.
    _assert(cleaned.startswith("There is one person visible"), "Expected model preamble to be removed")
    _assert("Here's" not in cleaned, "Caption cleanup left model preamble")
    _assert(_caption_needs_expansion(cleaned) is False, "Detailed indoor caption should not be expanded again")


# Section: run the main workflow with clear inputs and outputs.
def main():
    tests = [
        test_casm_caption_quality_augments_short_real_caption,
        test_casm_caption_quality_adds_yolo_context_to_rich_caption,
        test_casm_caption_quality_does_not_duplicate_existing_yolo_context,
        test_casm_caption_quality_replaces_provider_failure_only,
        test_augmented_caption_reason_does_not_block_strict_local_report,
        test_provider_failure_caption_reason_blocks_strict_local_report,
        test_report_generator_keeps_non_placeholder_caption,
        test_caption_generator_image_path_does_not_shadow_os_module,
        test_caption_generator_status_uses_active_gemini_vision_model,
        test_caption_cleanup_removes_model_preamble_without_forcing_expansion,
    ]
    # Prepare failures for the next step.
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
        print("Caption fallback contagion contract test failed")
        # Surface the failure with enough context for the caller.
        raise SystemExit(1)

    print("Caption fallback contagion contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
