import argparse
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from pipeline.backend.core.report_generator import _resolve_effective_nlp_provider_order


OUTAGE_MARKERS = (
    "localhost:11434",
    "nlp analysis failed",
    "max retries exceeded",
)


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_outage_marker(value: Any) -> bool:
    text = _as_text(value).lower()
    return any(marker in text for marker in OUTAGE_MARKERS)


def _request_json(base_url: str, path: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None, timeout: int = 40) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if method == "POST":
        response = requests.post(url, json=payload or {}, timeout=timeout)
    else:
        response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json() if response.content else {}


def _extract_runtime_fields(base_url: str) -> Dict[str, Any]:
    runtime_payload = _request_json(base_url, "/api/providers/runtime-status")
    routing_payload = _request_json(base_url, "/api/settings/provider-routing")

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

    nlp_provider_order = [_as_text(item).lower() for item in nlp_provider_order if _as_text(item)]

    return {
        "routing_profile": routing_profile,
        "nlp_provider_order": nlp_provider_order,
        "last_provider": _as_text(nlp_runtime.get("last_provider")).lower() or None,
        "last_model": _as_text(nlp_runtime.get("last_model")) or None,
        "last_error": _as_text(nlp_runtime.get("last_error")) or None,
        "last_fallback_reason": _as_text(nlp_runtime.get("last_fallback_reason")) or None,
    }


def _assert_mode_contract(fields: Dict[str, Any], expected_mode: str) -> List[str]:
    issues: List[str] = []
    profile = _as_text(fields.get("routing_profile")).lower()
    order = fields.get("nlp_provider_order") or []

    if profile != expected_mode:
        issues.append(f"routing_profile={profile or 'missing'} expected={expected_mode}")

    if expected_mode == "cloud":
        if "gemini" not in order:
            issues.append(f"cloud order missing gemini: {order}")
        conflicting = [provider for provider in order if provider in ("ollama", "local")]
        if conflicting:
            issues.append(f"cloud order has local providers {conflicting}: {order}")
    else:
        if "ollama" not in order and "local" not in order:
            issues.append(f"local order missing ollama/local: {order}")
        conflicting = [provider for provider in order if provider in ("gemini", "model_api")]
        if conflicting:
            issues.append(f"local order has cloud providers {conflicting}: {order}")

    return issues


def _list_violations(base_url: str, limit: int = 60) -> List[Dict[str, Any]]:
    payload = _request_json(base_url, f"/api/violations?limit={int(limit)}")
    return payload if isinstance(payload, list) else []


def _try_generate_now(base_url: str, max_candidates: int = 12) -> Dict[str, Any]:
    violations = _list_violations(base_url, limit=max(20, max_candidates * 2))
    attempts: List[Dict[str, Any]] = []

    for item in violations[:max_candidates]:
        report_id = _as_text(item.get("report_id"))
        if not report_id:
            continue

        status_code = None
        body: Dict[str, Any] = {}
        error_text = None

        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/api/report/{report_id}/generate-now",
                json={"force": False},
                timeout=45,
            )
            status_code = response.status_code
            try:
                body = response.json() if response.content else {}
            except Exception:
                body = {"raw": response.text[:500]}
        except Exception as exc:
            error_text = str(exc)

        accepted = bool(status_code is not None and 200 <= int(status_code) < 300)
        if accepted and isinstance(body, dict):
            if body.get("success") is False:
                accepted = False

        attempts.append(
            {
                "report_id": report_id,
                "status_code": status_code,
                "accepted": accepted,
                "body": body,
                "error": error_text,
            }
        )

        if accepted:
            return {
                "accepted": True,
                "report_id": report_id,
                "status_code": status_code,
                "body": body,
                "attempts": attempts,
            }

    return {
        "accepted": False,
        "report_id": None,
        "status_code": None,
        "body": {},
        "attempts": attempts,
    }


def _poll_report_status(base_url: str, report_id: str, timeout_seconds: int = 90, interval_seconds: int = 3) -> Dict[str, Any]:
    history: List[Dict[str, Any]] = []
    started = time.time()

    while time.time() - started <= timeout_seconds:
        try:
            payload = _request_json(base_url, f"/api/report/{report_id}/status")
            status = _as_text(payload.get("status")).lower() or "unknown"
            history.append(
                {
                    "status": status,
                    "has_report": bool(payload.get("has_report")),
                    "message": _as_text(payload.get("message")),
                }
            )
            if status in ("completed", "failed", "skipped", "not_found"):
                return {
                    "terminal": True,
                    "history": history,
                    "final_status": status,
                }
        except Exception as exc:
            history.append({"status": "error", "message": str(exc)})
        time.sleep(max(1, interval_seconds))

    final_status = history[-1].get("status") if history else "unknown"
    return {
        "terminal": False,
        "history": history,
        "final_status": final_status,
    }


def _static_order_contract() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def run_case(name: str, configured_order: Any, profile: str, strict: bool, expected: List[str]) -> None:
        resolved = _resolve_effective_nlp_provider_order(
            configured_order,
            routing_profile=profile,
            enforce_strict_provider_split=strict,
        )
        checks.append(
            {
                "name": name,
                "configured_order": configured_order,
                "profile": profile,
                "strict": strict,
                "expected": expected,
                "actual": resolved,
                "pass": resolved == expected,
            }
        )

    run_case(
        "strict_cloud_filters_local",
        ["ollama", "local", "gemini", "model_api"],
        "cloud",
        True,
        ["gemini", "model_api"],
    )
    run_case(
        "strict_local_filters_cloud",
        ["gemini", "model_api", "ollama", "local"],
        "local",
        True,
        ["ollama", "local"],
    )
    run_case(
        "strict_cloud_empty_defaults_gemini",
        [],
        "cloud",
        True,
        ["gemini"],
    )
    run_case(
        "strict_local_empty_defaults_ollama",
        [],
        "local",
        True,
        ["ollama"],
    )
    run_case(
        "non_strict_keeps_order",
        ["model_api", "gemini", "ollama"],
        "cloud",
        False,
        ["model_api", "gemini", "ollama"],
    )

    all_passed = all(check.get("pass") for check in checks)
    return {"all_passed": all_passed, "checks": checks}


def _run_mode_probe(base_url: str, expected_mode: str, do_generate: bool = True) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "base_url": base_url,
        "expected_mode": expected_mode,
        "switch_applied": False,
        "runtime_before": None,
        "runtime_after": None,
        "mode_contract_issues": [],
        "generation": None,
        "issues": [],
    }

    try:
        _request_json(
            base_url,
            "/api/settings/provider-routing",
            method="POST",
            payload={"routing_profile": expected_mode},
            timeout=45,
        )
        result["switch_applied"] = True
    except Exception as exc:
        result["issues"].append(f"provider switch failed: {exc}")

    try:
        runtime_before = _extract_runtime_fields(base_url)
        result["runtime_before"] = runtime_before
        result["mode_contract_issues"] = _assert_mode_contract(runtime_before, expected_mode)
        result["issues"].extend(result["mode_contract_issues"])
    except Exception as exc:
        result["issues"].append(f"runtime probe failed: {exc}")

    if do_generate:
        generation = _try_generate_now(base_url)
        result["generation"] = generation

        if generation.get("accepted") and generation.get("report_id"):
            status_poll = _poll_report_status(base_url, generation["report_id"], timeout_seconds=90)
            generation["status_poll"] = status_poll

            try:
                runtime_after = _extract_runtime_fields(base_url)
                result["runtime_after"] = runtime_after

                if expected_mode == "cloud":
                    if runtime_after.get("last_provider") not in (None, "", "gemini", "fallback"):
                        result["issues"].append(
                            f"cloud run last_provider unexpected: {runtime_after.get('last_provider')}"
                        )
                    if _contains_outage_marker(runtime_after.get("last_error")):
                        result["issues"].append(
                            f"cloud run last_error has outage marker: {runtime_after.get('last_error')}"
                        )
                    if _contains_outage_marker(runtime_after.get("last_fallback_reason")):
                        result["issues"].append(
                            "cloud run last_fallback_reason has outage marker: "
                            f"{runtime_after.get('last_fallback_reason')}"
                        )
                else:
                    if runtime_after.get("last_provider") not in (None, "", "ollama", "local", "fallback"):
                        result["issues"].append(
                            f"local run last_provider unexpected: {runtime_after.get('last_provider')}"
                        )
            except Exception as exc:
                result["issues"].append(f"runtime post-generation probe failed: {exc}")
        else:
            result["issues"].append("no generate-now candidate accepted")

    result["pass"] = len(result["issues"]) == 0
    return result


def _is_local_backend_reachable(base_url: str) -> Tuple[bool, Optional[str]]:
    try:
        _request_json(base_url, "/api/system/startup-status", timeout=10)
        return True, None
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe strict cloud/local provider isolation")
    parser.add_argument(
        "--cloud-base-url",
        default=os.environ.get("LUNA_CLOUD_BASE_URL", "https://fypaaimodeldevelopment-integration-production.up.railway.app"),
        help="Cloud backend base URL",
    )
    parser.add_argument(
        "--local-base-url",
        default=os.environ.get("LUNA_LOCAL_BASE_URL", "http://127.0.0.1:5000"),
        help="Local backend base URL",
    )
    parser.add_argument(
        "--skip-local",
        action="store_true",
        help="Skip local backend probe",
    )
    parser.add_argument(
        "--require-local",
        action="store_true",
        help="Fail if local backend is not reachable",
    )
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Skip generate-now probe and validate runtime routing only",
    )
    args = parser.parse_args()

    summary: Dict[str, Any] = {
        "static_contract": _static_order_contract(),
        "cloud_probe": None,
        "local_probe": None,
        "all_passed": False,
    }

    summary["cloud_probe"] = _run_mode_probe(
        args.cloud_base_url,
        expected_mode="cloud",
        do_generate=not args.no_generate,
    )

    local_reachable = False
    local_reach_error = None
    if not args.skip_local:
        local_reachable, local_reach_error = _is_local_backend_reachable(args.local_base_url)
        if local_reachable:
            summary["local_probe"] = _run_mode_probe(
                args.local_base_url,
                expected_mode="local",
                do_generate=not args.no_generate,
            )
        else:
            summary["local_probe"] = {
                "base_url": args.local_base_url,
                "pass": False,
                "skipped": not args.require_local,
                "issues": [f"local backend unreachable: {local_reach_error}"],
            }

    all_passed = bool(summary["static_contract"].get("all_passed")) and bool(
        (summary.get("cloud_probe") or {}).get("pass")
    )

    if not args.skip_local:
        local_probe = summary.get("local_probe") or {}
        if local_probe.get("skipped"):
            all_passed = all_passed and (not args.require_local)
        else:
            all_passed = all_passed and bool(local_probe.get("pass"))

    summary["all_passed"] = all_passed

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
