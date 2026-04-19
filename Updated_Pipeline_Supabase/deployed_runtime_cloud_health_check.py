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
STRICT_RUNTIME = str(os.environ.get("LUNA_RUNTIME_HEALTH_STRICT", "0")).strip().lower() in {
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


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_outage_marker(value: Any) -> bool:
    text = _as_text(value).lower()
    return any(marker in text for marker in OUTAGE_MARKERS)


def _request_json(path: str, timeout: int = 30) -> Dict[str, Any]:
    response = requests.get(f"{BASE_URL}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json() if response.content else {}


def _extract_runtime_fields(runtime_payload: Dict[str, Any], routing_payload: Dict[str, Any]) -> Dict[str, Any]:
    settings = runtime_payload.get("settings") if isinstance(runtime_payload, dict) else {}
    runtime = runtime_payload.get("runtime") if isinstance(runtime_payload, dict) else {}
    nlp_runtime = runtime.get("nlp") if isinstance(runtime, dict) else {}

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

    return {
        "routing_profile": routing_profile,
        "nlp_provider_order": nlp_provider_order,
        "last_provider": _as_text(nlp_runtime.get("last_provider")).lower() or None,
        "last_error": _as_text(nlp_runtime.get("last_error")) or None,
        "last_fallback_reason": _as_text(nlp_runtime.get("last_fallback_reason")) or None,
    }


def main() -> int:
    try:
        runtime_payload = _request_json("/api/providers/runtime-status")
        routing_payload = _request_json("/api/settings/provider-routing")
        fields = _extract_runtime_fields(runtime_payload, routing_payload)

        issues: List[str] = []

        if fields["routing_profile"] != EXPECTED_ROUTING_PROFILE:
            issues.append(
                f"routing_profile={fields['routing_profile'] or 'missing'} expected={EXPECTED_ROUTING_PROFILE}"
            )

        if EXPECTED_NLP_PROVIDER not in fields["nlp_provider_order"]:
            issues.append(
                f"nlp_provider_order={fields['nlp_provider_order']} missing={EXPECTED_NLP_PROVIDER}"
            )

        if STRICT_RUNTIME:
            if fields["last_provider"] not in {None, "", EXPECTED_NLP_PROVIDER, "fallback"}:
                issues.append(f"last_provider={fields['last_provider']} unexpected")

            if _contains_outage_marker(fields["last_error"]):
                issues.append(f"last_error contains outage marker: {fields['last_error']}")

            if _contains_outage_marker(fields["last_fallback_reason"]):
                issues.append(
                    "last_fallback_reason contains outage marker: "
                    f"{fields['last_fallback_reason']}"
                )

        status = "PASS" if not issues else "FAIL"
        summary = (
            f"{status}: profile={fields['routing_profile'] or 'missing'} "
            f"nlp_order={fields['nlp_provider_order']} "
            f"last_provider={fields['last_provider']} "
            f"last_fallback_reason={fields['last_fallback_reason']}"
        )

        if issues:
            summary += " errors=" + " | ".join(issues)
            print(summary)
            return 2

        print(summary)
        return 0
    except Exception as exc:
        print(f"FAIL: runtime cloud health check error: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
