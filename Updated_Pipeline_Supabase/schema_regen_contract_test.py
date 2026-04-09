"""
Schema regeneration contract test for Gemini NLP output hardening.

This test is intentionally lightweight and offline:
- It mocks Gemini client responses.
- It verifies required-field schema gating behavior in _call_gemini_api.
"""

import sys
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
    subject.last_nlp_error = None
    return subject


def _valid_payload():
    return {
        "environment_type": "Construction Site",
        "visual_evidence": "The scene depicts a construction site setting.",
        "persons": [{"id": "Person 1"}],
        "summary": "Worker missing hard hat.",
        "dosh_regulations_cited": [{"regulation": "BOWEC 1986", "requirement": "Helmet required"}],
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


def test_schema_regen_failure_still_missing():
    first_missing = _valid_payload()
    first_missing.pop("summary")
    second_still_missing = _valid_payload()
    second_still_missing.pop("persons")

    fake = _FakeGeminiClient([first_missing, second_still_missing])
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r2")

    _assert(result is None, "Expected None when required fields still missing after regeneration")
    _assert(subject.last_nlp_error is not None, "Expected explicit last_nlp_error when schema remains invalid")


def test_schema_no_regen_when_valid():
    fake = _FakeGeminiClient([_valid_payload()])
    subject = _new_subject(fake, regen_attempts=1)

    result = subject._call_gemini_api("base prompt", image_path=None, report_id="r3")

    _assert(result is not None, "Expected valid payload to pass directly")
    _assert(len(fake.calls) == 1, "Expected only one Gemini call when payload is already valid")


def main():
    tests = [
        test_schema_regen_success,
        test_schema_regen_failure_still_missing,
        test_schema_no_regen_when_valid,
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
