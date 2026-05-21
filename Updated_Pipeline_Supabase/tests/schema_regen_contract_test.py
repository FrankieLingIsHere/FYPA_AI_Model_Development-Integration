"""
Schema regeneration contract test for Gemini NLP output hardening.

This test is intentionally lightweight and offline:
- It mocks Gemini client responses.
- It verifies required-field schema gating behavior in _call_gemini_api.
"""

import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator


class _FakeGeminiClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.is_available = True
        self.last_error = None

    def generate_report_json(self, prompt, image_path=None, report_id=None):
        self.calls.append(
            {
                "prompt": prompt,
                "image_path": image_path,
                "report_id": report_id,
            }
        )
        if not self._responses:
            return None
        return self._responses.pop(0)


def _new_subject(fake_client, regen_attempts=1):
    subject = ReportGenerator.__new__(ReportGenerator)
    subject.gemini_client = fake_client
    subject.gemini_schema_regen_attempts = regen_attempts
    subject.gemini_semantic_regen_attempts = regen_attempts
    subject.allow_schema_incomplete_report = False
    subject.allow_semantic_incomplete_report = False
    subject.last_nlp_error = None
    return subject


def _valid_payload():
    return {
        "environment_type": "Construction Site",
        "visual_evidence": "The scene depicts a construction site setting with one worker in an active work area beside visible construction materials.",
        "persons": [
            {
                "id": "Person 1",
                "description": "Person 1 is working in the construction frame and requires a complete PPE compliance review before the task continues.",
                "ppe": {"hardhat": "Missing", "safety_vest": "Missing"},
                "hazards_faced": [{"type": "PPE non-compliance", "source": "YOLO detected missing PPE", "severity": "HIGH"}],
                "risks": [
                    {
                        "risk_category": "PPE",
                        "risk": "The worker could sustain impact injury or reduced visibility exposure because required PPE is missing in the active work area.",
                        "likelihood": "HIGH",
                        "evidence": "YOLO detected NO-Hardhat and NO-Safety Vest for the visible person.",
                        "regulation_citation": "BOWEC 1986",
                        "mitigation_steps": [
                            "Stop the task until the worker wears a compliant hardhat and vest.",
                            "Record supervisor verification before allowing the worker to re-enter the work area.",
                        ],
                    }
                ],
                "corrective_actions": [
                    "Generate the regulatory incident report package with image evidence, detector metadata, and supervisor sign-off.",
                    "Issue compliant PPE to the worker and verify fit before work restarts.",
                    "Brief the crew on mandatory PPE checks before the next shift begins.",
                ],
            }
        ],
        "summary": "One worker is missing required PPE in a construction work area and needs immediate supervisor correction before work continues.",
        "severity_level": "HIGH",
        "dosh_regulations_cited": [
            {
                "regulation": "BOWEC 1986",
                "requirement": "Workers in construction activity must wear protective head and visibility equipment where the site exposes them to impact or movement hazards.",
                "explanation": "The detected person is in a construction setting with missing hardhat and safety vest, so the PPE control is directly relevant to this report.",
                "penalty": "DOSH may require corrective evidence, issue an improvement notice, or escalate enforcement if the breach remains unresolved.",
            }
        ],
    }


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_schema_regen_success():
    first_missing = _valid_payload()
    first_missing.pop("summary")

    second_valid = _valid_payload()
    fake = _FakeGeminiClient([first_missing, second_valid])
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path="img.jpg", report_id="r1")

    _assert(result is not None, "Expected regenerated valid JSON result")
    _assert(result.get("summary"), "Expected summary to be present after regeneration")
    _assert(len(fake.calls) == 2, "Expected two Gemini calls (initial + regeneration)")
    _assert("SCHEMA REGENERATION REQUIREMENT" in fake.calls[1]["prompt"], "Expected schema regeneration instruction in second prompt")


def test_schema_regen_failure_returns_none_when_schema_incomplete_disabled():
    first_missing = _valid_payload()
    first_missing.pop("summary")
    second_still_missing = _valid_payload()
    second_still_missing.pop("persons")
    second_still_missing.pop("summary")

    fake = _FakeGeminiClient([first_missing, second_still_missing])
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r2")

    _assert(result is None, "Expected schema-incomplete Gemini payload to be rejected by default")
    _assert(len(fake.calls) == 2, "Expected two Gemini calls (initial + regeneration)")
    _assert(subject.last_nlp_error, "Expected terminal nlp error when schema-incomplete output is rejected")


def test_schema_regen_failure_can_return_best_effort_when_opted_in():
    first_missing = _valid_payload()
    first_missing.pop("summary")
    second_still_missing = _valid_payload()
    second_still_missing.pop("persons")
    second_still_missing.pop("summary")

    fake = _FakeGeminiClient([first_missing, second_still_missing])
    subject = _new_subject(fake, regen_attempts=1)
    subject.allow_schema_incomplete_report = True
    subject.allow_semantic_incomplete_report = True

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r2b")

    _assert(result is not None, "Expected opt-in best-effort payload when schema remains incomplete")
    _assert(result.get("_schema_incomplete") is True, "Expected schema-incomplete marker on opt-in payload")
    _assert(len(fake.calls) == 3, "Expected initial, schema-regeneration, and semantic-regeneration Gemini calls")


def test_schema_no_regen_when_valid():
    fake = _FakeGeminiClient([_valid_payload()])
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r3")

    _assert(result is not None, "Expected valid payload to pass directly")
    _assert(len(fake.calls) == 1, "Expected only one Gemini call when payload is already valid")


def test_semantic_regen_rejects_missing_detector_ppe_and_actions():
    incomplete = _valid_payload()
    incomplete["persons"] = [
        {
            "id": "Person 1",
            "description": "Person observed.",
            "ppe": {"hardhat": "Mentioned"},
            "hazards_faced": [],
            "risks": [],
            "corrective_actions": ["Check PPE"],
        }
    ]
    fixed = _valid_payload()

    fake = _FakeGeminiClient([incomplete, fixed])
    subject = _new_subject(fake, regen_attempts=1)
    report_data = {
        "person_count": 1,
        "severity": "HIGH",
        "detections": [
            {"class_name": "Person"},
            {"class_name": "NO-Hardhat"},
            {"class_name": "NO-Safety Vest"},
        ],
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "caption": "One worker is visible in a construction worksite.",
    }

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="semantic1", report_data=report_data)

    _assert(result is not None, "Expected semantic regeneration to repair incomplete Gemini payload")
    _assert(len(fake.calls) == 2, "Expected initial Gemini call plus semantic regeneration")
    _assert("SEMANTIC COMPLETENESS REGENERATION REQUIREMENT" in fake.calls[1]["prompt"], "Expected semantic regeneration prompt")


def test_semantic_regen_failure_returns_none_by_default():
    incomplete = _valid_payload()
    incomplete["severity_level"] = "LOW"
    incomplete["persons"][0]["corrective_actions"] = ["Check PPE"]

    fake = _FakeGeminiClient([incomplete, incomplete])
    subject = _new_subject(fake, regen_attempts=1)
    report_data = {
        "person_count": 1,
        "severity": "HIGH",
        "detections": [{"class_name": "Person"}, {"class_name": "NO-Hardhat"}],
        "violation_summary": "PPE Violation Detected: NO-Hardhat",
        "caption": "One worker is visible in a construction worksite.",
    }

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="semantic2", report_data=report_data)

    _assert(result is None, "Expected semantically incomplete Gemini payload to be rejected by default")
    _assert(subject.last_nlp_error and "semantically incomplete" in subject.last_nlp_error, subject.last_nlp_error)


def test_schema_incomplete_payload_skips_regen_for_downstream_completion():
    partial_payload = {
        "environment_type": "Indoor / Office",
        "visual_evidence": "The image shows people in an office-like indoor setting.",
        "_schema_incomplete": True,
        "_missing_required_report_keys": ["persons", "summary", "dosh_regulations_cited"],
    }
    fake = _FakeGeminiClient([partial_payload])
    subject = _new_subject(fake, regen_attempts=2)
    subject.allow_schema_incomplete_report = True

    result = subject._call_gemini_api("base prompt", image_path="img.jpg", report_id="r4")

    _assert(result is not None, "Expected usable partial payload to be returned")
    _assert(result.get("_schema_incomplete") is True, "Expected schema-incomplete marker to be preserved")
    _assert(len(fake.calls) == 1, "Expected no schema-regeneration call for marked partial payload")


def test_strict_gate_recovers_missing_corrective_actions_with_grounded_fallback():
    old_env = {
        key: os.environ.get(key)
        for key in (
            "CASM_ROUTING_PROFILE",
            "STRICT_PROVIDER_MODE_SPLIT",
            "STRICT_REPORT_GENERATION",
            "STRICT_MODEL_REPORT_CELLS",
            "ALLOW_NLP_FALLBACK",
            "GEMINI_BUDGET_STATE_PATH",
        )
    }
    try:
        os.environ["CASM_ROUTING_PROFILE"] = "local"
        os.environ["STRICT_PROVIDER_MODE_SPLIT"] = "true"
        os.environ["STRICT_REPORT_GENERATION"] = "true"
        os.environ["STRICT_MODEL_REPORT_CELLS"] = "true"
        os.environ["ALLOW_NLP_FALLBACK"] = "false"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            os.environ["GEMINI_BUDGET_STATE_PATH"] = str(root / "gemini_budget_state.json")

            subject = ReportGenerator({
                "GEMINI_CONFIG": {"enabled": False},
                "OLLAMA_CONFIG": {"model": "gemma3:4b", "use_local_model": False},
                "MODEL_API_CONFIG": {"nlp_provider_order": ["ollama"]},
                "RAG_CONFIG": {"enabled": False, "use_chroma": False},
                "REPORT_CONFIG": {"format": "html", "enable_pdf_generation": False},
                "REPORTS_DIR": root,
                "VIOLATIONS_DIR": root,
            })

            def fake_ollama_response(*_args, **_kwargs):
                return {
                    "environment_type": "Indoor workspace",
                    "visual_evidence": (
                        "The frame shows one visible person in an indoor workspace. "
                        "YOLO detection identified missing hardhat PPE deficiencies."
                    ),
                    "persons": [
                        {
                            "id": "Person 1",
                            "description": "Person 1 is visible in the monitored work area.",
                            "ppe": {"hardhat": "Missing"},
                            "hazards_faced": [
                                {
                                    "type": "PPE non-compliance",
                                    "source": "YOLO detected missing Hardhat",
                                    "severity": "HIGH",
                                }
                            ],
                            "risks": [
                                {
                                    "risk_category": "PPE",
                                    "risk": "The person remains exposed to head-impact hazards while hardhat protection is missing.",
                                    "likelihood": "HIGH",
                                    "evidence": "YOLO detected NO-Hardhat for the visible person.",
                                    "regulation_citation": "BOWEC 1986",
                                    "mitigation_steps": ["Stop work until compliant head protection is worn."],
                                }
                            ],
                        }
                    ],
                    "summary": "One visible person is missing required hardhat protection and needs immediate correction.",
                    "severity_level": "HIGH",
                    "dosh_regulations_cited": [
                        {
                            "regulation": "BOWEC 1986",
                            "requirement": "Protective head equipment is required where workers face head-impact hazards.",
                            "explanation": "The visible person is missing hardhat protection.",
                            "penalty": "Corrective evidence and enforcement action may be required if unresolved.",
                        }
                    ],
                }

            captured = {}

            def fake_html_report(report_data, nlp_analysis):
                captured["nlp_analysis"] = nlp_analysis
                html_path = Path(report_data["violation_dir"]) / "report.html"
                html_path.write_text("<html>report complete</html>", encoding="utf-8")
                return html_path

            subject._call_ollama_api = fake_ollama_response
            subject._generate_html_report = fake_html_report
            subject._write_traceability_sidecar = lambda **_kwargs: None

            report_dir = root / "strict_action_recovery_001"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_data = {
                "report_id": "strict_action_recovery_001",
                "timestamp": "2026-05-21T11:43:36+08:00",
                "caption": (
                    "One person is visible indoors. YOLO detection identified 1 person(s) "
                    "with PPE deficiencies: Missing Hardhat."
                ),
                "detections": [
                    {"class_name": "Person", "confidence": 0.91, "bbox": [0, 0, 10, 10]},
                    {"class_name": "NO-Hardhat", "confidence": 0.88, "bbox": [1, 1, 8, 8]},
                ],
                "violation_summary": "PPE Violation Detected: Missing Hardhat",
                "violation_types": ["Missing Hardhat"],
                "person_count": 1,
                "violation_count": 1,
                "severity": "HIGH",
                "force_local_nlp": True,
                "allow_local_nlp_fallback": False,
                "violation_dir": str(report_dir),
                "original_image_path": str(report_dir / "original.jpg"),
                "annotated_image_path": str(report_dir / "annotated.jpg"),
            }

            result = subject.generate_report(report_data)

            actions = ((captured.get("nlp_analysis") or {}).get("persons") or [{}])[0].get("corrective_actions")
            _assert(result.get("html") and result["html"].exists(), "Report HTML should be generated")
            _assert(actions and len(actions) >= 1, f"Corrective actions were not recovered: {captured}")
            _assert(subject.last_nlp_provider == "ollama", f"Expected model provider to remain Ollama: {subject.last_nlp_provider}")
            _assert(not subject.last_nlp_fallback_reason, f"Recoverable action injection should not become NLP fallback: {subject.last_nlp_fallback_reason}")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    tests = [
        test_schema_regen_success,
        test_schema_regen_failure_returns_none_when_schema_incomplete_disabled,
        test_schema_regen_failure_can_return_best_effort_when_opted_in,
        test_schema_no_regen_when_valid,
        test_semantic_regen_rejects_missing_detector_ppe_and_actions,
        test_semantic_regen_failure_returns_none_by_default,
        test_schema_incomplete_payload_skips_regen_for_downstream_completion,
        test_strict_gate_recovers_missing_corrective_actions_with_grounded_fallback,
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
        print("Schema regeneration contract test failed")
        raise SystemExit(1)

    print("Schema regeneration contract test passed")


if __name__ == "__main__":
    main()
