#!/usr/bin/env python3
"""Run and summarize repo-standard Playwright validation scenarios."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCENARIO_SCRIPTS: Dict[str, List[str]] = {
    "local-reconnect": [
        "Updated_Pipeline_Supabase/local_mode_ui_checkup_reconnect_perf_test.py",
    ],
    "deployed-parity": [
        "Updated_Pipeline_Supabase/deployed_frontend_reports_progress_parity_test.py",
    ],
    "all": [
        "Updated_Pipeline_Supabase/local_mode_ui_checkup_reconnect_perf_test.py",
        "Updated_Pipeline_Supabase/deployed_frontend_reports_progress_parity_test.py",
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


def run_script(
    repo_root: Path,
    python_cmd: str,
    script_relative: str,
    timeout_seconds: int,
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
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root(Path(__file__).resolve())
    scripts = SCENARIO_SCRIPTS[args.scenario]

    results = [
        run_script(
            repo_root=repo_root,
            python_cmd=args.python_cmd,
            script_relative=script,
            timeout_seconds=args.timeout_seconds,
        )
        for script in scripts
    ]

    all_passed = all(item.get("passed") for item in results)
    summary = {
        "scenario": args.scenario,
        "repo_root": str(repo_root),
        "python": args.python_cmd,
        "all_passed": all_passed,
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
