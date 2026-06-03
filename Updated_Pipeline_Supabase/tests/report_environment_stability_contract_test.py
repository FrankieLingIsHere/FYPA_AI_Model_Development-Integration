"""
Offline contract test for report environment label stability.

The report environment badge must be decided once from visual evidence before
HTML rendering, then reused for persisted metadata. Model output may refine the
label only when the caption/detections support that refinement.
"""
# Readability: Test setup: document the contract this file protects.

import sys
from pathlib import Path

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the subject workflow with clear inputs and outputs.
def _subject():
    return ReportGenerator.__new__(ReportGenerator)


# Section: run the test residential caption blocks construction hallucination workflow with clear inputs and outputs.
def test_residential_caption_blocks_construction_hallucination():
    # Prepare subject for the next step.
    subject = _subject()
    caption = (
        "A living room scene shows one person seated on a couch near a television. "
        "The person is indoors beside cushions and curtains, and no construction activity is visible."
    )
    resolved = subject._resolve_stable_environment_type(caption, [], "Construction Site")
    _assert(resolved == "Residential", f"Expected Residential, got {resolved!r}")


# Section: run the test model can refine when evidence supports it workflow with clear inputs and outputs.
def test_model_can_refine_when_evidence_supports_it():
    # Prepare subject for the next step.
    subject = _subject()
    caption = (
        "A worker is standing on scaffolding beside an elevated platform at a building facade. "
        "The person is working near an exposed edge and fall protection is not clearly visible."
    )
    resolved = subject._resolve_stable_environment_type(caption, [], "Work at Height")
    _assert(resolved == "Work at Height", f"Expected Work at Height, got {resolved!r}")


# Section: run the test generic caption blocks unsupported roadside label workflow with clear inputs and outputs.
def test_generic_caption_blocks_unsupported_roadside_label():
    # Prepare subject for the next step.
    subject = _subject()
    caption = (
        "An indoor office scene shows one person standing near a desk, chairs, and a computer monitor. "
        "No road, vehicle traffic, cones, or roadside work controls are visible."
    )
    resolved = subject._resolve_stable_environment_type(caption, [], "Roadside Work Zone")
    _assert(resolved == "Indoor / Office", f"Expected Indoor / Office, got {resolved!r}")


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Prepare tests for the next step.
    tests = [
        test_residential_caption_blocks_construction_hallucination,
        test_model_can_refine_when_evidence_supports_it,
        test_generic_caption_blocks_unsupported_roadside_label,
    ]
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
        raise SystemExit(1)

    print("Report environment stability contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
