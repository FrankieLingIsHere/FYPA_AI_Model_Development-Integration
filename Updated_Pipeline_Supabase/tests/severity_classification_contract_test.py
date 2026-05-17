import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("STARTUP_MODEL_WARMUP_ENABLED", "false")

import casm_app


def test_report_severity_uses_config_for_single_ppe_violations():
    assert casm_app._classify_violation_severity(violation_types=["NO-Hardhat"]) == "HIGH"
    assert casm_app._classify_violation_severity(violation_types=["NO-Safety Vest"]) == "HIGH"
    assert casm_app._classify_violation_severity(violation_types=["NO-Mask"]) == "MEDIUM"
    assert casm_app._classify_violation_severity(violation_types=["NO-Gloves"]) == "MEDIUM"
    assert casm_app._classify_violation_severity(violation_types=["NO-Safety Shoes"]) == "MEDIUM"


def test_report_severity_uses_environment_context_for_ppe_risk():
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Safety Vest"],
        context_text="Indoor office desk area with employees seated at workstations.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Safety Vest"],
        context_text="Indoor office desk area with no visible vehicles or mobile equipment.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Safety Vest"],
        context_text="Loading bay with forklift traffic and moving trucks.",
    ) == "HIGH"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Hardhat"],
        context_text="Administrative office meeting room.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Hardhat"],
        context_text="Construction worksite below overhead crane activity.",
    ) == "HIGH"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Hardhat", "NO-Safety Vest"],
        context_text="Residential living room scene with a person beside a couch and television.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Safety Vest"],
        context_text="Roadside work zone with cones, traffic control, and moving vehicles beside the worker.",
    ) == "HIGH"


def test_report_severity_escalates_medium_ppe_only_when_matching_hazard_exists():
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Mask"],
        context_text="Indoor office scene with normal administrative workstations.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Mask"],
        context_text="Indoor office scene with no visible dust, smoke, fumes, or airborne contaminants.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Mask"],
        context_text="Worker exposed to silica dust and airborne respiratory contaminants.",
    ) == "HIGH"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Goggles"],
        context_text="Grinding and cutting work producing flying particles and debris.",
    ) == "HIGH"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Mask", "NO-Gloves", "NO-Safety Shoes"],
        context_text="Administrative office room.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Mask", "NO-Gloves", "NO-Safety Shoes"],
        context_text="Ordinary public area street scene with pedestrians near a bus stop.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Hardhat", "NO-Safety Vest", "NO-Mask"],
        context_text="Indoor / Office scene with a desk and no visible traffic, machinery, dust, fumes, or overhead work.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Hardhat", "NO-Safety Vest", "NO-Mask"],
        context_text="Ordinary public area street scene with pedestrians near a bus stop.",
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Safety Vest"],
        context_text="Public street scene near a bus stop with pedestrians.",
    ) == "MEDIUM"


def test_report_severity_uses_detection_and_summary_fallbacks():
    assert casm_app._classify_violation_severity(
        detections=[{"class_name": "Person"}, {"class_name": "NO-Mask"}],
        violation_count=1,
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_summary="PPE Violation Detected: Missing Hardhat",
        violation_count=1,
    ) == "HIGH"


def test_multiple_medium_only_violations_escalate_but_generic_count_does_not_default_high():
    assert casm_app._classify_violation_severity(
        violation_types=["NO-Mask", "NO-Gloves", "NO-Safety Shoes"],
        violation_count=3,
    ) == "HIGH"
    assert casm_app._classify_violation_severity(
        violation_types=[],
        violation_count=1,
    ) == "MEDIUM"
    assert casm_app._classify_violation_severity(
        violation_types=[],
        violation_count=0,
    ) == "LOW"
