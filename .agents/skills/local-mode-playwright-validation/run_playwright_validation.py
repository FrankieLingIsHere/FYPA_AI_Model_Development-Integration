#!/usr/bin/env python3
"""Run and summarize repo-standard Playwright validation scenarios."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCENARIO_SCRIPTS: Dict[str, List[str]] = {
    "local-reconnect": [
        "Updated_Pipeline_Supabase/local_mode_ui_checkup_reconnect_perf_test.py",
    ],
    "deployed-parity": [
        "Updated_Pipeline_Supabase/deployed_frontend_reports_progress_parity_test.py",
        "Updated_Pipeline_Supabase/deployed_frontend_local_reports_label_contract_test.py",
    ],
    "all": [
        "Updated_Pipeline_Supabase/local_mode_ui_checkup_reconnect_perf_test.py",
        "Updated_Pipeline_Supabase/deployed_frontend_reports_progress_parity_test.py",
        "Updated_Pipeline_Supabase/deployed_frontend_local_reports_label_contract_test.py",
    ],
}


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "Updated_Pipeline_Supabase").exists():
            return candidate
    return start.resolve()


def extract_status_and_payload(output: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    status = "UNKNOWN"
    for line in output.splitlines():
        token = line.strip()
        if token in {"PASS", "FAIL"}:
            status = token

    parsed: Optional[Dict[str, Any]] = None
    brace_indices = [idx for idx, ch in enumerate(output) if ch == "{"]
    for idx in reversed(brace_indices):
        fragment = output[idx:].strip()
        try:
            candidate = json.loads(fragment)
            if isinstance(candidate, dict):
                parsed = candidate
                break
        except json.JSONDecodeError:
            continue
    return status, parsed


def extract_local_reconnect_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    reconnect_details: Dict[str, Any] = {}
    for item in payload.get("timeline", []) or []:
        if isinstance(item, dict) and item.get("step") == "wifi_reconnect_event_processed":
            reconnect_details = item.get("details") or {}
            break

    perf = payload.get("performance") or {}
    endpoint_summary = perf.get("endpoint_summary") or {}

    return {
        "routing_snapshot": payload.get("routing_snapshot") or {},
        "sync_started_auto_after_reconnect": reconnect_details.get("sync_started_auto_after_reconnect"),
        "sync_seen_auto_after_reconnect": reconnect_details.get("sync_seen_auto_after_reconnect"),
        "sync_seen_after_reconnect": reconnect_details.get("sync_seen_after_reconnect"),
        "manual_sync_attempt": reconnect_details.get("manual_sync_attempt"),
        "sync_local_cache_summary": endpoint_summary.get("sync_local_cache"),
        "sync_after_reconnect_started_calls_len": len(perf.get("sync_after_reconnect_started_calls") or []),
        "sync_after_reconnect_calls_len": len(perf.get("sync_after_reconnect_calls") or []),
    }


def extract_deployed_parity_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    local = payload.get("local") or {}
    cloud = payload.get("cloud") or {}
    return {
        "frontend": payload.get("frontend"),
        "local_pass": local.get("pass"),
        "cloud_pass": cloud.get("pass"),
        "local_sequence": local.get("statusSequence"),
        "cloud_sequence": cloud.get("statusSequence"),
    }


def extract_deployed_local_label_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    checks = payload.get("checks") or []
    if not isinstance(checks, list):
        checks = []

    compact_checks = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        compact_checks.append(
            {
                "reportId": item.get("reportId"),
                "expectedStatus": item.get("expectedStatus"),
                "exists": item.get("exists"),
                "sourceOk": item.get("sourceOk"),
                "statusOk": item.get("statusOk"),
                "sourceBadgeText": item.get("sourceBadgeText"),
                "statusBadgeText": item.get("statusBadgeText"),
            }
        )

    return {
        "frontend": payload.get("frontend"),
        "label_contract_pass": payload.get("pass"),
        "cardCount": payload.get("cardCount"),
        "checks": compact_checks,
    }


def probe_local_backend(local_ui_url: str, timeout_seconds: float = 4.0) -> Dict[str, Any]:
    base = str(local_ui_url or "http://127.0.0.1:5000").rstrip("/")
    checks: List[Dict[str, Any]] = []
    endpoints = [
        ("root", f"{base}/", {200}),
        ("startup_status", f"{base}/api/system/startup-status", {200, 202}),
        ("queue_status", f"{base}/api/queue/status", {200}),
    ]

    for name, url, ok_statuses in endpoints:
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                body_text = response.read().decode("utf-8", errors="ignore")
            checks.append(
                {
                    "name": name,
                    "url": url,
                    "status_code": status_code,
                    "ok": status_code in ok_statuses,
                    "body_snippet": body_text[:180],
                }
            )
        except urllib.error.HTTPError as exc:
            checks.append(
                {
                    "name": name,
                    "url": url,
                    "status_code": int(getattr(exc, "code", 0) or 0),
                    "ok": False,
                    "error": f"HTTPError: {exc}",
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": name,
                    "url": url,
                    "status_code": 0,
                    "ok": False,
                    "error": str(exc),
                }
            )

    return {
        "base_url": base,
        "ready": all(bool(item.get("ok")) for item in checks),
        "checks": checks,
    }


def run_script(
    repo_root: Path,
    python_cmd: str,
    script_relative: str,
    timeout_seconds: int,
    env_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    script_path = repo_root / script_relative
    if not script_path.exists():
        return {
            "script": script_relative,
            "status": "FAIL",
            "exit_code": 127,
            "duration_ms": 0,
            "passed": False,
            "error": f"Script not found: {script_relative}",
        }

    command = [python_cmd, str(script_path)]
    command_env = os.environ.copy()
    for key, value in (env_overrides or {}).items():
        if value is None:
            continue
        command_env[str(key)] = str(value)

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            env=command_env,
            timeout=None if timeout_seconds <= 0 else timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "script": script_relative,
            "status": "FAIL",
            "exit_code": 124,
            "duration_ms": duration_ms,
            "passed": False,
            "error": f"Timeout after {timeout_seconds}s",
            "stdout_tail": (exc.stdout or "")[-1200:],
            "stderr_tail": (exc.stderr or "")[-1200:],
        }

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    combined_output = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
    status, payload = extract_status_and_payload(combined_output)

    status_from_payload = "PASS" if isinstance(payload, dict) and payload.get("pass") is True else None
    effective_status = status_from_payload or status
    passed = bool(effective_status == "PASS" and completed.returncode == 0)

    result: Dict[str, Any] = {
        "script": script_relative,
        "status": effective_status,
        "exit_code": completed.returncode,
        "duration_ms": duration_ms,
        "passed": passed,
    }

    if isinstance(payload, dict):
        result["payload_pass"] = payload.get("pass")
        if script_relative.endswith("local_mode_ui_checkup_reconnect_perf_test.py"):
            result["metrics"] = extract_local_reconnect_metrics(payload)
        elif script_relative.endswith("deployed_frontend_reports_progress_parity_test.py"):
            result["metrics"] = extract_deployed_parity_metrics(payload)
        elif script_relative.endswith("deployed_frontend_local_reports_label_contract_test.py"):
            result["metrics"] = extract_deployed_local_label_metrics(payload)

    if not passed:
        result["stdout_tail"] = (completed.stdout or "")[-1500:]
        result["stderr_tail"] = (completed.stderr or "")[-1500:]

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run standard Playwright validation scenarios for this repository.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_SCRIPTS.keys()),
        default="all",
        help="Validation scenario to run.",
    )
    parser.add_argument(
        "--python",
        dest="python_cmd",
        default=sys.executable,
        help="Python executable used to run test scripts.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Per-script timeout in seconds (0 disables timeout).",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write summary JSON.",
    )
    parser.add_argument(
        "--frontend-url",
        default="",
        help="Override LUNA_VERCEL_URL for deployed parity/label scripts.",
    )
    parser.add_argument(
        "--local-ui-url",
        default="",
        help="Override LUNA_LOCAL_UI_URL for local reconnect script.",
    )
    parser.add_argument(
        "--check-local-backend",
        action="store_true",
        help="Run local backend endpoint preflight checks before local reconnect scenario scripts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root(Path(__file__).resolve())
    scripts = SCENARIO_SCRIPTS[args.scenario]

    env_overrides: Dict[str, str] = {}
    if args.frontend_url:
        env_overrides["LUNA_VERCEL_URL"] = str(args.frontend_url).rstrip("/")
    if args.local_ui_url:
        env_overrides["LUNA_LOCAL_UI_URL"] = str(args.local_ui_url).rstrip("/")

    local_ui_effective = (
        env_overrides.get("LUNA_LOCAL_UI_URL")
        or str(os.environ.get("LUNA_LOCAL_UI_URL", "http://127.0.0.1:5000")).rstrip("/")
    )
    preflight: Optional[Dict[str, Any]] = None

    if args.check_local_backend and any(
        script.endswith("local_mode_ui_checkup_reconnect_perf_test.py") for script in scripts
    ):
        preflight = probe_local_backend(local_ui_effective)
        if not preflight.get("ready"):
            summary = {
                "scenario": args.scenario,
                "repo_root": str(repo_root),
                "python": args.python_cmd,
                "all_passed": False,
                "env_overrides": env_overrides,
                "preflight": preflight,
                "results": [
                    {
                        "script": "Updated_Pipeline_Supabase/local_mode_ui_checkup_reconnect_perf_test.py",
                        "status": "FAIL",
                        "exit_code": 111,
                        "duration_ms": 0,
                        "passed": False,
                        "error": "Local backend preflight failed. Start local backend and retry.",
                    }
                ],
            }

            if args.json_out:
                out_path = Path(args.json_out)
                if not out_path.is_absolute():
                    out_path = repo_root / out_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

            print(json.dumps(summary, indent=2, ensure_ascii=True))
            return 2

    results = [
        run_script(
            repo_root=repo_root,
            python_cmd=args.python_cmd,
            script_relative=script,
            timeout_seconds=args.timeout_seconds,
            env_overrides=env_overrides,
        )
        for script in scripts
    ]

    all_passed = all(item.get("passed") for item in results)
    summary = {
        "scenario": args.scenario,
        "repo_root": str(repo_root),
        "python": args.python_cmd,
        "all_passed": all_passed,
        "env_overrides": env_overrides,
        "preflight": preflight,
        "results": results,
    }

    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0 if all_passed else 2


if __name__ == "__main__":
    sys.exit(main())
