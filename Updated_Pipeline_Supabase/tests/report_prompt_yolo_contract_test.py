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


def test_report_text_cleaning_does_not_split_characters():
    subject = ReportGenerator.__new__(ReportGenerator)

    cleaned = subject._to_safe_html_text("Worker -> helmet \u2022 vest")

    _assert(cleaned == "Worker to helmet, vest", f"Unexpected cleaned text: {cleaned!r}")
    _assert("to , to" not in cleaned, "Report text cleaner split text into character fragments")


def test_sanitized_report_fields_stay_word_level():
    subject = ReportGenerator.__new__(ReportGenerator)
    analysis = subject._sanitize_nlp_analysis({
        "summary": "General Workspace safety violation.",
        "hazards_detected": "Falling objects",
        "persons": [
            {
                "id": "Person 1",
                "description": "Worker missing hard hat.",
                "ppe": {"Hard Hat": "Missing"},
                "hazards_faced": ["Falling debris"],
                "risks": [{"risk": "Head injury from debris", "likelihood": "High"}],
                "corrective_actions": ["Replace hat with helmet"],
            }
        ],
    })

    rendered = subject._generate_person_cards_section(analysis, {
        "caption": "One worker is missing required PPE.",
        "violation_summary": "PPE Violation Detected: NO-Hardhat",
        "person_count": 1,
        "detections": [{"class_name": "Person"}],
    })

    _assert("Worker missing hard hat." in rendered, "Person description was not preserved")
    _assert("Falling debris" in rendered, "Hazard text was not preserved")
    _assert("to , to" not in rendered, "Rendered person HTML contains character-split text")


def test_ollama_compact_prompt_keeps_required_schema_and_yolo_ppe():
    subject = ReportGenerator.__new__(ReportGenerator)

    compact = subject._build_ollama_compact_report_prompt({
        "caption": "One worker is standing in a work area.",
        "violation_summary": "Missing Hard Hat, Missing Safety Vest",
        "person_count": 1,
        "severity": "HIGH",
        "detections": [
            {"class_name": "Person", "confidence": 0.91},
            {"class_name": "NO-Hardhat", "confidence": 0.83},
            {"class_name": "NO-Safety Vest", "confidence": 0.76},
        ],
    }, "original long prompt")

    _assert('"environment_type"' in compact, "Compact prompt missing environment_type schema")
    _assert('"persons"' in compact, "Compact prompt missing persons schema")
    _assert('"dosh_regulations_cited"' in compact, "Compact prompt missing regulation schema")
    _assert('"hardhat": "Missing"' in compact, "Compact prompt did not preserve YOLO hardhat gap")
    _assert('"safety_vest": "Missing"' in compact, "Compact prompt did not preserve YOLO vest gap")
    _assert("Do not return an empty object" in compact, "Compact prompt must reject empty JSON")

    compact_two_people = subject._build_ollama_compact_report_prompt({
        "caption": "Two workers are standing in a work area.",
        "violation_summary": "Missing Hard Hat",
        "person_count": 2,
        "severity": "HIGH",
        "detections": [
            {"class_name": "Person"},
            {"class_name": "Person"},
            {"class_name": "NO-Hardhat"},
        ],
    }, "original long prompt")
    _assert('"id": "Person 2"' in compact_two_people, "Compact prompt did not preserve multi-person schema")


def main():
    tests = [
        test_nlp_prompt_injects_yolo_payload,
        test_report_text_cleaning_does_not_split_characters,
        test_sanitized_report_fields_stay_word_level,
        test_ollama_compact_prompt_keeps_required_schema_and_yolo_ppe,
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
        print("Report prompt YOLO contract test failed")
        raise SystemExit(1)

    print("Report prompt YOLO contract test passed")


if __name__ == "__main__":
    main()
