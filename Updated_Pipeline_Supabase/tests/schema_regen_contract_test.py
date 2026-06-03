"""
Schema regeneration contract test for Gemini NLP output hardening.

This test is intentionally lightweight and offline:
- It mocks Gemini client responses.
- It verifies required-field schema gating behavior in _call_gemini_api.
"""
# Readability: Test setup: document the contract this file protects.

import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is importable
# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator


# Section: group fake gemini client state and behaviour in one readable unit.
class _FakeGeminiClient:
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, responses):
        # Prepare responses for the next step.
        self._responses = list(responses)
        self.calls = []
        self.is_available = True
        self.last_error = None

    # Section: run the generate report json workflow with clear inputs and outputs.
    def generate_report_json(self, prompt, image_path=None, report_id=None):
        self.calls.append(
            {
                "prompt": prompt,
                "image_path": image_path,
                "report_id": report_id,
            }
        )
        # Choose the correct branch before the workflow continues.
        if not self._responses:
            # Return the prepared result to the caller.
            return None
        return self._responses.pop(0)


# Section: run the new subject workflow with clear inputs and outputs.
def _new_subject(fake_client, regen_attempts=1):
    # Prepare subject for the next step.
    subject = ReportGenerator.__new__(ReportGenerator)
    subject.gemini_client = fake_client
    subject.gemini_schema_regen_attempts = regen_attempts
    subject.gemini_semantic_regen_attempts = regen_attempts
    subject.allow_schema_incomplete_report = False
    subject.allow_semantic_incomplete_report = False
    subject.last_nlp_error = None
    return subject


# Section: run the valid payload workflow with clear inputs and outputs.
def _valid_payload():
    # Return the prepared result to the caller.
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


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test schema regen success workflow with clear inputs and outputs.
def test_schema_regen_success():
    first_missing = _valid_payload()
    first_missing.pop("summary")

    second_valid = _valid_payload()
    # Prepare fake for the next step.
    fake = _FakeGeminiClient([first_missing, second_valid])
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path="img.jpg", report_id="r1")

    _assert(result is not None, "Expected regenerated valid JSON result")
    _assert(result.get("summary"), "Expected summary to be present after regeneration")
    _assert(len(fake.calls) == 2, "Expected two Gemini calls (initial + regeneration)")
    _assert("SCHEMA REGENERATION REQUIREMENT" in fake.calls[1]["prompt"], "Expected schema regeneration instruction in second prompt")


# Section: run the test schema regen failure returns none when schema incomplete disabled workflow with clear inputs and outputs.
def test_schema_regen_failure_returns_none_when_schema_incomplete_disabled():
    # Prepare first missing for the next step.
    first_missing = _valid_payload()
    first_missing.pop("summary")
    second_still_missing = _valid_payload()
    second_still_missing.pop("persons")
    second_still_missing.pop("summary")

    fake = _FakeGeminiClient([first_missing, second_still_missing])
    subject = _new_subject(fake, regen_attempts=1)

    # Prepare result for the next step.
    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r2")

    _assert(result is None, "Expected schema-incomplete Gemini payload to be rejected by default")
    _assert(len(fake.calls) == 2, "Expected two Gemini calls (initial + regeneration)")
    _assert(subject.last_nlp_error, "Expected terminal nlp error when schema-incomplete output is rejected")


# Section: run the test schema regen failure can return best effort when opted in workflow with clear inputs and outputs.
def test_schema_regen_failure_can_return_best_effort_when_opted_in():
    first_missing = _valid_payload()
    # Trigger the side effect required for this stage.
    first_missing.pop("summary")
    second_still_missing = _valid_payload()
    second_still_missing.pop("persons")
    second_still_missing.pop("summary")

    fake = _FakeGeminiClient([first_missing, second_still_missing])
    subject = _new_subject(fake, regen_attempts=1)
    subject.allow_schema_incomplete_report = True
    subject.allow_semantic_incomplete_report = True

    # Prepare result for the next step.
    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r2b")

    _assert(result is not None, "Expected opt-in best-effort payload when schema remains incomplete")
    _assert(result.get("_schema_incomplete") is True, "Expected schema-incomplete marker on opt-in payload")
    _assert(len(fake.calls) == 3, "Expected initial, schema-regeneration, and semantic-regeneration Gemini calls")


# Section: run the test schema no regen when valid workflow with clear inputs and outputs.
def test_schema_no_regen_when_valid():
    fake = _FakeGeminiClient([_valid_payload()])
    # Prepare subject for the next step.
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r3")

    _assert(result is not None, "Expected valid payload to pass directly")
    _assert(len(fake.calls) == 1, "Expected only one Gemini call when payload is already valid")


# Section: run the test semantic regen rejects missing detector ppe and actions workflow with clear inputs and outputs.
def test_semantic_regen_rejects_missing_detector_ppe_and_actions():
    # Prepare incomplete for the next step.
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
    # Prepare fixed for the next step.
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

    # Prepare result for the next step.
    result = subject._call_gemini_api("base prompt", image_path=None, report_id="semantic1", report_data=report_data)

    _assert(result is not None, "Expected semantic regeneration to repair incomplete Gemini payload")
    _assert(len(fake.calls) == 2, "Expected initial Gemini call plus semantic regeneration")
    _assert("SEMANTIC COMPLETENESS REGENERATION REQUIREMENT" in fake.calls[1]["prompt"], "Expected semantic regeneration prompt")


# Section: run the test semantic regen failure returns none by default workflow with clear inputs and outputs.
def test_semantic_regen_failure_returns_none_by_default():
    incomplete = _valid_payload()
    # Prepare values needed by the next step.
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

    # Prepare result for the next step.
    result = subject._call_gemini_api("base prompt", image_path=None, report_id="semantic2", report_data=report_data)

    _assert(result is None, "Expected semantically incomplete Gemini payload to be rejected by default")
    _assert(subject.last_nlp_error and "semantically incomplete" in subject.last_nlp_error, subject.last_nlp_error)


# Section: run the test schema incomplete payload skips regen for downstream completion workflow with clear inputs and outputs.
def test_schema_incomplete_payload_skips_regen_for_downstream_completion():
    partial_payload = {
        "environment_type": "Indoor / Office",
        "visual_evidence": "The image shows people in an office-like indoor setting.",
        "_schema_incomplete": True,
        "_missing_required_report_keys": ["persons", "summary", "dosh_regulations_cited"],
    }
    # Prepare fake for the next step.
    fake = _FakeGeminiClient([partial_payload])
    subject = _new_subject(fake, regen_attempts=2)
    subject.allow_schema_incomplete_report = True

    result = subject._call_gemini_api("base prompt", image_path="img.jpg", report_id="r4")

    _assert(result is not None, "Expected usable partial payload to be returned")
    _assert(result.get("_schema_incomplete") is True, "Expected schema-incomplete marker to be preserved")
    _assert(len(fake.calls) == 1, "Expected no schema-regeneration call for marked partial payload")


# Section: run the test strict gate recovers missing corrective actions with grounded fallback workflow with clear inputs and outputs.
def test_strict_gate_recovers_missing_corrective_actions_with_grounded_fallback():
    # Prepare old env for the next step.
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
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare values needed by the next step.
        os.environ["CASM_ROUTING_PROFILE"] = "local"
        os.environ["STRICT_PROVIDER_MODE_SPLIT"] = "true"
        os.environ["STRICT_REPORT_GENERATION"] = "true"
        os.environ["STRICT_MODEL_REPORT_CELLS"] = "true"
        os.environ["ALLOW_NLP_FALLBACK"] = "false"

        with tempfile.TemporaryDirectory() as tmpdir:
            # Prepare root for the next step.
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

            # Section: run the fake ollama response workflow with clear inputs and outputs.
            def fake_ollama_response(*_args, **_kwargs):
                # Return the prepared result to the caller.
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

            # Prepare captured for the next step.
            captured = {}

            # Section: run the fake html report workflow with clear inputs and outputs.
            def fake_html_report(report_data, nlp_analysis):
                # Prepare values needed by the next step.
                captured["nlp_analysis"] = nlp_analysis
                html_path = Path(report_data["violation_dir"]) / "report.html"
                html_path.write_text("<html>report complete</html>", encoding="utf-8")
                return html_path

            subject._call_ollama_api = fake_ollama_response
            subject._generate_html_report = fake_html_report
            subject._write_traceability_sidecar = lambda **_kwargs: None

            # Prepare report dir for the next step.
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

            # Prepare result for the next step.
            result = subject.generate_report(report_data)

            actions = ((captured.get("nlp_analysis") or {}).get("persons") or [{}])[0].get("corrective_actions")
            _assert(result.get("html") and result["html"].exists(), "Report HTML should be generated")
            _assert(actions and len(actions) >= 1, f"Corrective actions were not recovered: {captured}")
            _assert(subject.last_nlp_provider == "ollama", f"Expected model provider to remain Ollama: {subject.last_nlp_provider}")
            _assert(not subject.last_nlp_fallback_reason, f"Recoverable action injection should not become NLP fallback: {subject.last_nlp_fallback_reason}")
    finally:
        # Process each item in this collection using the same rule set.
        for key, value in old_env.items():
            # Choose the correct branch before the workflow continues.
            if value is None:
                # Trigger the side effect required for this stage.
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Prepare tests for the next step.
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
        print("Schema regeneration contract test failed")
        # Surface the failure with enough context for the caller.
        raise SystemExit(1)

    print("Schema regeneration contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
