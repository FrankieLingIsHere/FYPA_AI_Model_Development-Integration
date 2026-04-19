import os
import sys
from typing import Any, Dict, List, Optional

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

EXPECTED_ROUTING_PROFILE = os.environ.get("LUNA_EXPECT_ROUTING_PROFILE", "cloud").strip().lower()
EXPECTED_NLP_PROVIDER = os.environ.get("LUNA_EXPECT_NLP_PROVIDER", "gemini").strip().lower()
NON_BLOCKING = str(os.environ.get("LUNA_RUNTIME_NLP_CONTRACT_NON_BLOCKING", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DISALLOW_FALLBACK_PROVIDER = str(os.environ.get("LUNA_RUNTIME_DISALLOW_FALLBACK", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

OUTAGE_MARKERS = (
    "localhost:11434",
    "no provider detail",
    "nlp analysis failed",
)


def fail(message: str, code: int = 2) -> int:
    if NON_BLOCKING:
        print(f"INFO: non-blocking runtime NLP contract issue: {message}")
        return 0
    print(f"FAIL: {message}")
    return code


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _request_json(path: str, timeout: int = 30) -> Dict[str, Any]:
    response = requests.get(f"{BASE_URL}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json() if response.content else {}


def _find_markers(value: Any) -> List[str]:
    text = _as_text(value).lower()
    if not text:
        return []
    return [marker for marker in OUTAGE_MARKERS if marker in text]


def main() -> int:
    try:
        runtime_payload = _request_json("/api/providers/runtime-status")
        routing_payload = _request_json("/api/settings/provider-routing")

        settings = runtime_payload.get("settings") if isinstance(runtime_payload, dict) else {}
        runtime = runtime_payload.get("runtime") if isinstance(runtime_payload, dict) else {}
        nlp_runtime = runtime.get("nlp") if isinstance(runtime, dict) else {}

        if not isinstance(nlp_runtime, dict):
            return fail("runtime.nlp payload is missing", 3)

        routing_profile = _as_text(settings.get("routing_profile")).lower()
        if not routing_profile:
            routing_profile = _as_text((routing_payload or {}).get("routing_profile")).lower()

        nlp_provider_order = settings.get("nlp_provider_order")
        if not isinstance(nlp_provider_order, list) or not nlp_provider_order:
            nlp_provider_order = (routing_payload or {}).get("nlp_provider_order")
        if not isinstance(nlp_provider_order, list):
            nlp_provider_order = []

        nlp_provider_order = [
            _as_text(item).lower() for item in nlp_provider_order if _as_text(item)
        ]

        last_provider = _as_text(nlp_runtime.get("last_provider")).lower() or None
        last_error = _as_text(nlp_runtime.get("last_error")) or None
        last_fallback_reason = _as_text(nlp_runtime.get("last_fallback_reason")) or None

        if routing_profile != EXPECTED_ROUTING_PROFILE:
            return fail(
                f"routing profile mismatch: got={routing_profile or 'missing'} expected={EXPECTED_ROUTING_PROFILE}",
                4,
            )

        if EXPECTED_NLP_PROVIDER not in nlp_provider_order:
            return fail(
                f"nlp provider order missing {EXPECTED_NLP_PROVIDER}: {nlp_provider_order}",
                5,
            )

        if EXPECTED_ROUTING_PROFILE == "cloud":
            conflicting = [p for p in nlp_provider_order if p in {"ollama", "local"}]
            if conflicting:
                return fail(
                    f"cloud profile contains local providers: {conflicting} in nlp_provider_order={nlp_provider_order}",
                    14,
                )

        if "last_provider" not in nlp_runtime:
            return fail("runtime.nlp.last_provider key missing", 6)
        if "last_error" not in nlp_runtime:
            return fail("runtime.nlp.last_error key missing", 7)
        if "last_fallback_reason" not in nlp_runtime:
            return fail("runtime.nlp.last_fallback_reason key missing", 8)

        error_markers = _find_markers(last_error)
        fallback_markers = _find_markers(last_fallback_reason)
        if error_markers:
            return fail(
                f"last_error contains outage marker(s) {error_markers}: {last_error}",
                9,
            )
        if fallback_markers:
            return fail(
                f"last_fallback_reason contains outage marker(s) {fallback_markers}: {last_fallback_reason}",
                10,
            )

        if last_provider and last_provider not in {EXPECTED_NLP_PROVIDER, "fallback"}:
            return fail(
                f"last_provider unexpected: {last_provider}",
                11,
            )

        if last_provider == "fallback":
            if DISALLOW_FALLBACK_PROVIDER:
                return fail(
                    "last_provider=fallback is disallowed by runtime contract",
                    15,
                )
            if not last_fallback_reason:
                return fail(
                    "last_fallback_reason should be present when last_provider=fallback",
                    13,
                )

        if last_provider == "gemini" and last_fallback_reason:
            return fail(
                f"last_fallback_reason should be empty when last_provider=gemini: {last_fallback_reason}",
                12,
            )

        print(
            "PASS: runtime NLP contract verified "
            f"(profile={routing_profile}, nlp_order={nlp_provider_order}, "
            f"last_provider={last_provider}, last_fallback_reason={last_fallback_reason})"
        )
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during runtime NLP contract test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled runtime NLP contract test error: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
