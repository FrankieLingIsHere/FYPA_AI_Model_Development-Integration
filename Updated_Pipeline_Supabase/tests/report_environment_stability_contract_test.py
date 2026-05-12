"""
Offline contract test for report environment label stability.

The report environment badge must be decided once from visual evidence before
HTML rendering, then reused for persisted metadata. Model output may refine the
label only when the caption/detections support that refinement.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _subject():
    return ReportGenerator.__new__(ReportGenerator)


def test_residential_caption_blocks_construction_hallucination():
    subject = _subject()
    caption = (
        "A living room scene shows one person seated on a couch near a television. "
        "The person is indoors beside cushions and curtains, and no construction activity is visible."
    )
    resolved = subject._resolve_stable_environment_type(caption, [], "Construction Site")
    _assert(resolved == "Residential", f"Expected Residential, got {resolved!r}")


def test_model_can_refine_when_evidence_supports_it():
    subject = _subject()
    caption = (
        "A worker is standing on scaffolding beside an elevated platform at a building facade. "
        "The person is working near an exposed edge and fall protection is not clearly visible."
    )
    resolved = subject._resolve_stable_environment_type(caption, [], "Work at Height")
    _assert(resolved == "Work at Height", f"Expected Work at Height, got {resolved!r}")


def test_generic_caption_blocks_unsupported_roadside_label():
    subject = _subject()
    caption = (
        "An indoor office scene shows one person standing near a desk, chairs, and a computer monitor. "
        "No road, vehicle traffic, cones, or roadside work controls are visible."
    )
    resolved = subject._resolve_stable_environment_type(caption, [], "Roadside Work Zone")
    _assert(resolved == "Indoor / Office", f"Expected Indoor / Office, got {resolved!r}")


def main():
    tests = [
        test_residential_caption_blocks_construction_hallucination,
        test_model_can_refine_when_evidence_supports_it,
        test_generic_caption_blocks_unsupported_roadside_label,
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

    print("Report environment stability contract test passed")


if __name__ == "__main__":
    main()
