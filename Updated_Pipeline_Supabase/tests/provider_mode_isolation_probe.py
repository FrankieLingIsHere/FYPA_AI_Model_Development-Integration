# Readability: Test setup: document the contract this file protects.
import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# Add project root to path (file is in tests/, project root is parent dir)
# Trigger the side effect required for this stage.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.backend.core.report_generator import _resolve_effective_nlp_provider_order


OUTAGE_MARKERS = (
    "localhost:11434",
    "nlp analysis failed",
    "max retries exceeded",
)
# Prepare disallow fallback provider for the next step.
DISALLOW_FALLBACK_PROVIDER = str(os.environ.get("CASM_RUNTIME_DISALLOW_FALLBACK", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEFAULT_STATUS_POLL_TIMEOUT_SECONDS = max(45, int(os.environ.get("CASM_GENERATE_POLL_TIMEOUT_SECONDS", "150") or 150))


# Section: run the as text workflow with clear inputs and outputs.
def _as_text(value: Any) -> str:
    # Return the prepared result to the caller.
    return str(value or "").strip()


# Section: run the contains outage marker workflow with clear inputs and outputs.
def _contains_outage_marker(value: Any) -> bool:
    text = _as_text(value).lower()
    return any(marker in text for marker in OUTAGE_MARKERS)


# Section: run the request json workflow with clear inputs and outputs.
def _request_json(base_url: str, path: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None, timeout: int = 40) -> Dict[str, Any]:
    # Prepare url for the next step.
    url = f"{base_url.rstrip('/')}{path}"
    if method == "POST":
        # Prepare response for the next step.
        response = requests.post(url, json=payload or {}, timeout=timeout)
    else:
        response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json() if response.content else {}


# Section: run the extract runtime fields workflow with clear inputs and outputs.
def _extract_runtime_fields(base_url: str) -> Dict[str, Any]:
    # Prepare runtime payload for the next step.
    runtime_payload = _request_json(base_url, "/api/providers/runtime-status")
    routing_payload = _request_json(base_url, "/api/settings/provider-routing")

    settings = runtime_payload.get("settings") if isinstance(runtime_payload, dict) else {}
    runtime = runtime_payload.get("runtime") if isinstance(runtime_payload, dict) else {}
    nlp_runtime = runtime.get("nlp") if isinstance(runtime, dict) else {}

    routing_profile = _as_text(settings.get("routing_profile")).lower()
    if not routing_profile:
        # Prepare routing profile for the next step.
        routing_profile = _as_text((routing_payload or {}).get("routing_profile")).lower()

    # Prepare nlp provider order for the next step.
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


# Section: run the assert mode contract workflow with clear inputs and outputs.
def _assert_mode_contract(fields: Dict[str, Any], expected_mode: str) -> List[str]:
    issues: List[str] = []
    # Prepare profile for the next step.
    profile = _as_text(fields.get("routing_profile")).lower()
    order = fields.get("nlp_provider_order") or []

    if profile != expected_mode:
        # Trigger the side effect required for this stage.
        issues.append(f"routing_profile={profile or 'missing'} expected={expected_mode}")

    if expected_mode == "cloud":
        if "gemini" not in order:
            # Trigger the side effect required for this stage.
            issues.append(f"cloud order missing gemini: {order}")
        conflicting = [provider for provider in order if provider in ("ollama", "local")]
        if conflicting:
            issues.append(f"cloud order has local providers {conflicting}: {order}")
    else:
        # Choose the correct branch before the workflow continues.
        if "ollama" not in order and "local" not in order:
            issues.append(f"local order missing ollama/local: {order}")
        conflicting = [provider for provider in order if provider in ("gemini", "model_api")]
        if conflicting:
            # Trigger the side effect required for this stage.
            issues.append(f"local order has cloud providers {conflicting}: {order}")

    # Return the prepared result to the caller.
    return issues


# Section: run the list violations workflow with clear inputs and outputs.
def _list_violations(base_url: str, limit: int = 60) -> List[Dict[str, Any]]:
    payload = _request_json(base_url, f"/api/violations?limit={int(limit)}")
    return payload if isinstance(payload, list) else []


# Section: run the prioritize generate candidates workflow with clear inputs and outputs.
def _prioritize_generate_candidates(violations: List[Dict[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    # Prepare status rank for the next step.
    status_rank = {
        "pending": 0,
        "queued": 1,
        "generating": 2,
        "failed": 3,
        "unknown": 4,
        "completed": 5,
        "skipped": 6,
    }

    # Process each item in this collection using the same rule set.
    for item in violations:
        # Choose the correct branch before the workflow continues.
        if not isinstance(item, dict):
            continue
        report_id = _as_text(item.get("report_id"))
        if not report_id:
            continue

        status = _as_text(item.get("status")).lower()
        has_report = bool(item.get("has_report"))
        detection_count_raw = item.get("detection_count")
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare detection count for the next step.
            detection_count = int(detection_count_raw or 0)
        except (TypeError, ValueError):
            detection_count = 0
        is_manual_regen = report_id.startswith("manual_regenerate_")

        key = (
            1 if is_manual_regen else 0,
            1 if has_report else 0,
            status_rank.get(status, 7),
            -max(0, detection_count),
            report_id,
        )
        # Trigger the side effect required for this stage.
        ranked.append((key, item))

    # Trigger the side effect required for this stage.
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked[:max_candidates]]


# Section: run the try generate now workflow with clear inputs and outputs.
def _try_generate_now(base_url: str, max_candidates: int = 12) -> Dict[str, Any]:
    violations = _list_violations(base_url, limit=max(20, max_candidates * 2))
    candidates = _prioritize_generate_candidates(violations, max_candidates=max_candidates)
    attempts: List[Dict[str, Any]] = []

    # Process each item in this collection using the same rule set.
    for item in candidates:
        # Prepare report id for the next step.
        report_id = _as_text(item.get("report_id"))
        if not report_id:
            continue

        status_code = None
        body: Dict[str, Any] = {}
        error_text = None

        try:
            # Prepare response for the next step.
            response = requests.post(
                f"{base_url.rstrip('/')}/api/report/{report_id}/generate-now",
                json={"force": False},
                timeout=45,
            )
            status_code = response.status_code
            try:
                # Prepare body for the next step.
                body = response.json() if response.content else {}
            except Exception:
                body = {"raw": response.text[:500]}
        except Exception as exc:
            # Prepare error text for the next step.
            error_text = str(exc)

        # Prepare accepted for the next step.
        accepted = bool(status_code is not None and 200 <= int(status_code) < 300)
        if accepted and isinstance(body, dict):
            if body.get("success") is False:
                # Prepare accepted for the next step.
                accepted = False

        attempts.append(
            {
                "report_id": report_id,
                "status": _as_text(item.get("status")).lower() or None,
                "has_report": bool(item.get("has_report")),
                "detection_count": item.get("detection_count"),
                "status_code": status_code,
                "accepted": accepted,
                "body": body,
                "error": error_text,
            }
        )

        # Choose the correct branch before the workflow continues.
        if accepted:
            # Return the prepared result to the caller.
            return {
                "accepted": True,
                "report_id": report_id,
                "status_code": status_code,
                "body": body,
                "attempts": attempts,
            }

    # Return the prepared result to the caller.
    return {
        "accepted": False,
        "report_id": None,
        "status_code": None,
        "body": {},
        "attempts": attempts,
    }


# Section: run the poll report status workflow with clear inputs and outputs.
def _poll_report_status(base_url: str, report_id: str, timeout_seconds: int = 90, interval_seconds: int = 3) -> Dict[str, Any]:
    history: List[Dict[str, Any]] = []
    # Prepare started for the next step.
    started = time.time()

    while time.time() - started <= timeout_seconds:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare payload for the next step.
            payload = _request_json(base_url, f"/api/report/{report_id}/status")
            status = _as_text(payload.get("status")).lower() or "unknown"
            history.append(
                {
                    "status": status,
                    "has_report": bool(payload.get("has_report")),
                    "message": _as_text(payload.get("message")),
                }
            )
            # Choose the correct branch before the workflow continues.
            if status in ("completed", "failed", "skipped", "not_found"):
                # Return the prepared result to the caller.
                return {
                    "terminal": True,
                    "history": history,
                    "final_status": status,
                }
        except Exception as exc:
            history.append({"status": "error", "message": str(exc)})
        # Trigger the side effect required for this stage.
        time.sleep(max(1, interval_seconds))

    # Prepare final status for the next step.
    final_status = history[-1].get("status") if history else "unknown"
    return {
        "terminal": False,
        "history": history,
        "final_status": final_status,
    }


# Section: run the static order contract workflow with clear inputs and outputs.
def _static_order_contract() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    # Section: run the run case workflow with clear inputs and outputs.
    def run_case(name: str, configured_order: Any, profile: str, strict: bool, expected: List[str]) -> None:
        # Prepare resolved for the next step.
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

    # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
    run_case(
        "non_strict_keeps_order",
        ["model_api", "gemini", "ollama"],
        "cloud",
        False,
        ["model_api", "gemini", "ollama"],
    )

    all_passed = all(check.get("pass") for check in checks)
    # Return the prepared result to the caller.
    return {"all_passed": all_passed, "checks": checks}


# Section: run the run mode probe workflow with clear inputs and outputs.
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

    # Protect this step so expected failures can fall back cleanly.
    try:
        # Trigger the side effect required for this stage.
        _request_json(
            base_url,
            "/api/settings/provider-routing",
            method="POST",
            payload={"routing_profile": expected_mode},
            timeout=45,
        )
        result["switch_applied"] = True
    except Exception as exc:
        # Trigger the side effect required for this stage.
        result["issues"].append(f"provider switch failed: {exc}")

    # Protect this step so expected failures can fall back cleanly.
    try:
        runtime_before = _extract_runtime_fields(base_url)
        result["runtime_before"] = runtime_before
        result["mode_contract_issues"] = _assert_mode_contract(runtime_before, expected_mode)
        result["issues"].extend(result["mode_contract_issues"])
    except Exception as exc:
        result["issues"].append(f"runtime probe failed: {exc}")

    if do_generate:
        # Prepare generation for the next step.
        generation = _try_generate_now(base_url)
        result["generation"] = generation

        if generation.get("accepted") and generation.get("report_id"):
            # Prepare status poll for the next step.
            status_poll = _poll_report_status(
                base_url,
                generation["report_id"],
                timeout_seconds=DEFAULT_STATUS_POLL_TIMEOUT_SECONDS,
            )
            generation["status_poll"] = status_poll
            if not status_poll.get("terminal"):
                # Prepare history tail for the next step.
                history_tail = (status_poll.get("history") or [])[-3:]
                result["issues"].append(
                    "generation status did not reach terminal state "
                    f"within {DEFAULT_STATUS_POLL_TIMEOUT_SECONDS}s (final={status_poll.get('final_status')}, tail={history_tail})"
                )
            else:
                final_status = _as_text(status_poll.get("final_status")).lower()
                if final_status in ("failed", "not_found", "error", "unknown"):
                    # Trigger the side effect required for this stage.
                    result["issues"].append(
                        f"generation terminal status is non-success: {final_status}"
                    )

            # Protect this step so expected failures can fall back cleanly.
            try:
                # Prepare runtime after for the next step.
                runtime_after = _extract_runtime_fields(base_url)
                result["runtime_after"] = runtime_after

                if expected_mode == "cloud":
                    # Choose the correct branch before the workflow continues.
                    if runtime_after.get("last_provider") not in (None, "", "gemini", "fallback"):
                        # Trigger the side effect required for this stage.
                        result["issues"].append(
                            f"cloud run last_provider unexpected: {runtime_after.get('last_provider')}"
                        )
                    if DISALLOW_FALLBACK_PROVIDER and runtime_after.get("last_provider") == "fallback":
                        result["issues"].append("cloud run used fallback provider")
                    if _contains_outage_marker(runtime_after.get("last_error")):
                        result["issues"].append(
                            f"cloud run last_error has outage marker: {runtime_after.get('last_error')}"
                        )
                    # Choose the correct branch before the workflow continues.
                    if _contains_outage_marker(runtime_after.get("last_fallback_reason")):
                        # Trigger the side effect required for this stage.
                        result["issues"].append(
                            "cloud run last_fallback_reason has outage marker: "
                            f"{runtime_after.get('last_fallback_reason')}"
                        )
                else:
                    if runtime_after.get("last_provider") not in (None, "", "ollama", "local", "fallback"):
                        result["issues"].append(
                            f"local run last_provider unexpected: {runtime_after.get('last_provider')}"
                        )
                    # Choose the correct branch before the workflow continues.
                    if DISALLOW_FALLBACK_PROVIDER and runtime_after.get("last_provider") == "fallback":
                        # Trigger the side effect required for this stage.
                        result["issues"].append("local run used fallback provider")
            except Exception as exc:
                # Trigger the side effect required for this stage.
                result["issues"].append(f"runtime post-generation probe failed: {exc}")
        else:
            # Prepare attempts preview for the next step.
            attempts_preview = (generation.get("attempts") or [])[:3]
            result["issues"].append(
                "no generate-now candidate accepted"
                + (f" (attempts={attempts_preview})" if attempts_preview else "")
            )

    # Prepare values needed by the next step.
    result["pass"] = len(result["issues"]) == 0
    return result


# Section: run the is local backend reachable workflow with clear inputs and outputs.
def _is_local_backend_reachable(base_url: str) -> Tuple[bool, Optional[str]]:
    try:
        # Trigger the side effect required for this stage.
        _request_json(base_url, "/api/system/startup-status", timeout=10)
        return True, None
    except Exception as exc:
        return False, str(exc)


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare parser for the next step.
    parser = argparse.ArgumentParser(description="Probe strict cloud/local provider isolation")
    parser.add_argument(
        "--cloud-base-url",
        default=os.environ.get("CASM_CLOUD_BASE_URL", "https://fypaaimodeldevelopment-integration-production.up.railway.app"),
        help="Cloud backend base URL",
    )
    parser.add_argument(
        "--local-base-url",
        default=os.environ.get("CASM_LOCAL_BASE_URL", "http://127.0.0.1:5000"),
        help="Local backend base URL",
    )
    # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
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

    # Prepare values needed by the next step.
    summary["cloud_probe"] = _run_mode_probe(
        args.cloud_base_url,
        expected_mode="cloud",
        do_generate=not args.no_generate,
    )

    local_reachable = False
    local_reach_error = None
    if not args.skip_local:
        # Prepare values needed by the next step.
        local_reachable, local_reach_error = _is_local_backend_reachable(args.local_base_url)
        if local_reachable:
            # Prepare values needed by the next step.
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

    # Prepare all passed for the next step.
    all_passed = bool(summary["static_contract"].get("all_passed")) and bool(
        (summary.get("cloud_probe") or {}).get("pass")
    )

    if not args.skip_local:
        # Prepare local probe for the next step.
        local_probe = summary.get("local_probe") or {}
        if local_probe.get("skipped"):
            # Prepare all passed for the next step.
            all_passed = all_passed and (not args.require_local)
        else:
            all_passed = all_passed and bool(local_probe.get("pass"))

    # Prepare values needed by the next step.
    summary["all_passed"] = all_passed

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_passed else 2


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    raise SystemExit(main())
