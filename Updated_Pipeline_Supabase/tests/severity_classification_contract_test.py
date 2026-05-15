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
