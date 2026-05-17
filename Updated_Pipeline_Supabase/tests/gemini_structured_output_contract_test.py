"""
Offline contract checks for cloud Gemini report generation hardening.

These tests do not call Gemini. They assert that the SDK request is configured
for schema-backed JSON output and that cloud mode does not silently fall back to
rule-based reports unless explicitly enabled by environment.
"""

import inspect
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.integration.gemini_client import GeminiClient
from pipeline.backend.core import report_generator


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _new_client_for_config():
    client = GeminiClient.__new__(GeminiClient)
    client.temperature = 0.4
    client.report_temperature_cap = 0.1
    client.max_tokens = 8192
    client.report_output_max_tokens = 8192
    client.report_timeout_ms = 16000
    client.report_thinking_budget = 0
    return client


def test_gemini_report_config_uses_json_schema():
    client = _new_client_for_config()
    config = client._build_report_generation_config()
    schema = getattr(config, "response_json_schema", None)

    _assert(getattr(config, "response_mime_type", None) == "application/json", "Gemini report config must request JSON MIME output")
    _assert(isinstance(schema, dict), "Gemini report config must include response_json_schema")
    _assert(schema.get("type") == "object", "Report JSON schema must describe one object")
    required = set(schema.get("required") or [])
    for key in ("environment_type", "visual_evidence", "persons", "summary", "dosh_regulations_cited"):
        _assert(key in required, f"Report JSON schema missing required key: {key}")


def test_gemini_repair_config_uses_same_json_schema():
    source = inspect.getsource(GeminiClient._repair_json_with_gemini)
    _assert(
        "response_json_schema=self._build_report_json_schema()" in source,
        "Gemini JSON repair must also use the report JSON schema",
    )


def test_cloud_rule_based_fallback_is_opt_in():
    source = inspect.getsource(report_generator.ReportGenerator.__init__)
    _assert(
        "os.getenv('CLOUD_REPORT_FALLBACK_ENABLED', 'false')" in source,
        "Cloud rule-based report fallback must default to disabled",
    )


def main():
    tests = [
        test_gemini_report_config_uses_json_schema,
        test_gemini_repair_config_uses_same_json_schema,
        test_cloud_rule_based_fallback_is_opt_in,
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
        print("Gemini structured output contract test failed")
        raise SystemExit(1)

    print("Gemini structured output contract test passed")


if __name__ == "__main__":
    main()
