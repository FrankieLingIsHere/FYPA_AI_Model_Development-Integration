"""
Offline contract test for NLP report prompt grounding.

The report prompt must carry the raw YOLO detection payload, not only the VLM
caption, so Gemini/Ollama cannot miss PPE classifier evidence.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_nlp_prompt_injects_yolo_payload():
    subject = ReportGenerator.__new__(ReportGenerator)
    report_data = {
        "caption": "One worker is standing near construction materials in an active work area.",
        "detections": [
            {
                "class_name": "Person",
                "confidence": 0.91,
                "bbox": [12, 34, 120, 240],
            },
            {
                "class_name": "NO-Hardhat",
                "score": 0.83,
                "bbox": [22, 40, 90, 110],
            },
            {
                "class_name": "NO-Safety Vest",
                "confidence": 0.76,
                "bbox": [18, 90, 118, 210],
            },
        ],
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 1,
    }

    prompt = subject._build_nlp_prompt(report_data, similar_incidents=[], dosh_context=[])

    _assert("*** YOLO DETECTION PAYLOAD" in prompt, "Prompt missing YOLO payload section")
    _assert("- Person (confidence: 0.91" in prompt, "Prompt missing person detection")
    _assert("- NO-Hardhat (confidence: 0.83" in prompt, "Prompt missing hardhat violation")
    _assert("- NO-Safety Vest (confidence: 0.76" in prompt, "Prompt missing vest violation")
    _assert("YOLO violation classes: NO-Hardhat, NO-Safety Vest" in prompt, "Prompt missing YOLO violation summary")
    _assert("CONFIRMED MISSING PPE" in prompt, "Prompt missing missing-PPE directive")
    _assert("prefer YOLO for PPE status" in prompt, "Prompt missing conflict-resolution rule")


def main():
    tests = [test_nlp_prompt_injects_yolo_payload]
    failures = []
    for test_fn in tests:
        try:
            test_fn()
            print(f"PASS: {test_fn.__name__}")
        except Exception as exc:
            failures.append((test_fn.__name__, str(exc)))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    if failures:
        print("Report prompt YOLO contract test failed")
        raise SystemExit(1)

    print("Report prompt YOLO contract test passed")


if __name__ == "__main__":
    main()
