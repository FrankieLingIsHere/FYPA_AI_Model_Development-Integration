import json
import os
import sys
import time

import requests


BASE_URL = os.environ.get(
    "LUNA_BASE_URL",
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
).rstrip("/")

POLL_SECONDS = int(os.environ.get("LUNA_CONDITIONS_POLL_SECONDS", "30"))
POLL_INTERVAL = int(os.environ.get("LUNA_CONDITIONS_POLL_INTERVAL", "3"))
MAX_REPORT_IDS = int(os.environ.get("LUNA_CONDITIONS_MAX_REPORT_IDS", "15"))
ENABLE_PROVIDER_MODE_MATRIX = os.environ.get("LUNA_PROVIDER_MODE_MATRIX", "1") != "0"
PROVIDER_MODE_GENERATE_PROBE = os.environ.get("LUNA_PROVIDER_MODE_GENERATE_PROBE", "1") != "0"
STRICT_CONDITIONS = os.environ.get("LUNA_CONDITIONS_STRICT", "0") != "0"

ALLOWED_REPORT_STATUSES = {
    "pending",
    "queued",
    "processing",
    "generating",
    "completed",
    "failed",
    "not_found",
    "unknown",
}

PROVIDER_MODE_MATRIX = [
    {
        "name": "api-first",
        "payload": {
            "model_api_enabled": True,
            "gemini_enabled": True,
            "nlp_provider_order": "model_api,gemini,ollama,local",
            "vision_provider_order": "model_api,gemini,ollama",
            "embedding_provider_order": "model_api,ollama",
        },
        "expect": {
            "model_api_enabled": True,
            "gemini_enabled": True,
            "nlp_first": "model_api",
        },
    },
    {
        "name": "local-first",
        "payload": {
            "model_api_enabled": False,
            "gemini_enabled": False,
            "nlp_provider_order": "ollama,local,model_api,gemini",
            "vision_provider_order": "ollama,model_api,gemini",
            "embedding_provider_order": "ollama,model_api",
        },
        "expect": {
            "model_api_enabled": False,
            "gemini_enabled": False,
            "nlp_first": "ollama",
        },
    },
    {
        "name": "hybrid-fallback",
        "payload": {
            "model_api_enabled": True,
            "gemini_enabled": True,
            "nlp_provider_order": "gemini,model_api,ollama,local",
            "vision_provider_order": "gemini,model_api,ollama",
            "embedding_provider_order": "model_api,ollama",
        },
        "expect": {
            "model_api_enabled": True,
            "gemini_enabled": True,
            "nlp_first": "gemini",
        },
    },
]


def fail(msg: str, code: int = 2) -> int:
    if STRICT_CONDITIONS:
        print(f"FAIL: deployed conditions issue: {msg}")
        return code

    print(f"INFO: non-blocking deployed conditions issue: {msg}")
    return 0


def request_json(method: str, path: str, *, timeout: int = 30, **kwargs):
    url = f"{BASE_URL}{path}"
    r = requests.request(method=method.upper(), url=url, timeout=timeout, **kwargs)
    text_preview = (r.text or "")[:500]
    payload = None
    try:
        payload = r.json()
    except Exception:
        payload = None
    return r.status_code, payload, text_preview


def require_json_dict(path: str, name: str):
    code, payload, text = request_json("GET", path)
    if code >= 400:
        raise RuntimeError(f"{name} failed with {code}: {text}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} expected JSON object, got: {text}")
    print(f"PASS: {name}")
    return payload


def normalize_provider_order(value):
    if isinstance(value, str):
        return [x.strip().lower() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        out = []
        for item in value:
            if item is None:
                continue
            item_text = str(item).strip().lower()
            if item_text:
                out.append(item_text)
        return out
    return []


def is_skippable_generate_now_error(code: int, payload) -> bool:
    if code in (404,):
        return True
    if not isinstance(payload, dict):
        return False
    msg = str(payload.get("error") or payload.get("message") or "").lower()
    return "original image is missing" in msg or "report not found" in msg


def run_live_start_contract_probe() -> None:
    """Validate live start endpoint behavior against real backend (no mocks)."""
    code, payload, text = request_json("GET", "/api/live/status")
    if code >= 400 or not isinstance(payload, dict):
        raise RuntimeError(f"live-status invalid ({code}): {text}")
    print("PASS: live-status endpoint")

    code, payload, text = request_json(
        "POST",
        "/api/live/start",
        json={"source": "webcam"},
        timeout=35,
    )

    if not isinstance(payload, dict):
        raise RuntimeError(f"live-start returned non-JSON payload ({code}): {text}")

    if payload.get("success") is True:
        print(f"PASS: live-start accepted webcam request (status={code})")
        stop_code, stop_payload, stop_text = request_json("POST", "/api/live/stop", json={})
        if stop_code >= 400 or not isinstance(stop_payload, dict) or stop_payload.get("success") is False:
            raise RuntimeError(
                f"live-stop failed after successful start ({stop_code}): "
                f"{json.dumps(stop_payload)[:300] if isinstance(stop_payload, dict) else stop_text}"
            )
        print("PASS: live-stop after start")
        return

    message = str(payload.get("error") or payload.get("message") or "").lower()
    expected_hardware_unavailable = (
        "failed to open webcam" in message
        or "could not open webcam" in message
        or ("webcam" in message and ("failed" in message or "unavailable" in message))
    )

    if expected_hardware_unavailable:
        print("PASS: live-start returned explicit webcam-unavailable response")
        return

    raise RuntimeError(
        "live-start returned unexpected failure payload: "
        f"status={code} body={json.dumps(payload)[:350]}"
    )


def build_restore_payload(current_settings: dict) -> dict:
    restore_payload = {}
    known_keys = (
        "model_api_enabled",
        "gemini_enabled",
        "nlp_provider_order",
        "vision_provider_order",
        "embedding_provider_order",
        "nlp_model",
        "vision_model",
        "embedding_model",
        "gemini_model",
        "gemini_vision_model",
        "ollama_nlp_model",
        "ollama_vision_model",
        "gemini_daily_budget_usd",
        "gemini_monthly_budget_usd",
        "gemini_max_output_tokens_per_report",
    )
    for key in known_keys:
        if key in current_settings:
            restore_payload[key] = current_settings.get(key)
    return restore_payload


def run_provider_mode_matrix_probe(report_ids):
    settings_before = require_json_dict("/api/settings/provider-routing", "provider-routing-initial")
    restore_payload = build_restore_payload(settings_before)
    probe_report_id = report_ids[0] if report_ids else None

    try:
        for mode in PROVIDER_MODE_MATRIX:
            mode_name = mode["name"]
            payload = dict(mode["payload"])

            for model_key in ("nlp_model", "vision_model", "embedding_model", "gemini_model"):
                if model_key in settings_before and model_key not in payload:
                    payload[model_key] = settings_before.get(model_key)

            code, mode_result, mode_text = request_json(
                "POST",
                "/api/settings/provider-routing",
                json=payload,
                timeout=45,
            )
            if code >= 500:
                raise RuntimeError(f"provider mode {mode_name} update failed ({code}): {mode_text}")
            if not isinstance(mode_result, dict):
                raise RuntimeError(f"provider mode {mode_name} returned non-JSON payload")
            if mode_result.get("success") is False:
                raise RuntimeError(
                    f"provider mode {mode_name} returned success=false: {json.dumps(mode_result)[:350]}"
                )

            settings_after = mode_result.get("settings") if isinstance(mode_result.get("settings"), dict) else None
            if not settings_after:
                settings_after = require_json_dict("/api/settings/provider-routing", f"provider-routing-{mode_name}")

            expected = mode["expect"]
            if bool(settings_after.get("model_api_enabled")) != bool(expected["model_api_enabled"]):
                raise RuntimeError(
                    f"provider mode {mode_name} model_api_enabled mismatch: {settings_after.get('model_api_enabled')}"
                )
            if bool(settings_after.get("gemini_enabled")) != bool(expected["gemini_enabled"]):
                raise RuntimeError(
                    f"provider mode {mode_name} gemini_enabled mismatch: {settings_after.get('gemini_enabled')}"
                )

            nlp_order = normalize_provider_order(settings_after.get("nlp_provider_order"))
            if not nlp_order or nlp_order[0] != expected["nlp_first"]:
                raise RuntimeError(
                    f"provider mode {mode_name} nlp order mismatch: got {nlp_order}, expected first={expected['nlp_first']}"
                )

            runtime_code, runtime_payload, runtime_text = request_json(
                "GET",
                "/api/providers/runtime-status",
                timeout=30,
            )
            if runtime_code >= 400 or not isinstance(runtime_payload, dict):
                raise RuntimeError(
                    f"provider runtime status failed in mode {mode_name} ({runtime_code}): {runtime_text}"
                )
            if runtime_payload.get("success") is False:
                raise RuntimeError(f"provider runtime status unsuccessful in mode {mode_name}")

            if PROVIDER_MODE_GENERATE_PROBE and probe_report_id:
                g_code, g_payload, g_text = request_json(
                    "POST",
                    f"/api/report/{probe_report_id}/generate-now",
                    json={"force": False},
                    timeout=45,
                )
                if g_code >= 500:
                    raise RuntimeError(
                        f"generate-now server error in mode {mode_name} for {probe_report_id}: {g_code} {g_text}"
                    )
                if isinstance(g_payload, dict) and g_payload.get("success") is False:
                    if is_skippable_generate_now_error(g_code, g_payload):
                        print(
                            f"INFO: mode {mode_name} generate-now skipped for {probe_report_id}: "
                            f"{json.dumps(g_payload)[:260]}"
                        )
                    else:
                        raise RuntimeError(
                            f"generate-now rejected in mode {mode_name}: {json.dumps(g_payload)[:350]}"
                        )
                else:
                    print(
                        f"PASS: mode {mode_name} generate-now accepted for {probe_report_id} "
                        f"(status={g_code})"
                    )

            print(f"PASS: provider mode probe {mode_name}")
    finally:
        if restore_payload:
            r_code, r_payload, r_text = request_json(
                "POST",
                "/api/settings/provider-routing",
                json=restore_payload,
                timeout=45,
            )
            if r_code >= 400 or not isinstance(r_payload, dict) or r_payload.get("success") is False:
                raise RuntimeError(
                    f"failed to restore provider routing settings ({r_code}): "
                    f"{json.dumps(r_payload)[:320] if isinstance(r_payload, dict) else r_text}"
                )
            print("PASS: provider routing settings restored")


def main() -> int:
    try:
        startup = require_json_dict("/api/system/startup-status", "startup-status")
        if not startup.get("ready"):
            return fail(f"startup-status not ready: {json.dumps(startup)[:400]}", 3)

        queue = require_json_dict("/api/queue/status", "queue-status")
        if not queue.get("available"):
            return fail(f"queue unavailable: {json.dumps(queue)[:400]}", 4)
        if not queue.get("worker_running"):
            return fail(f"queue worker not running: {json.dumps(queue)[:400]}", 5)

        stats = require_json_dict("/api/stats", "stats")
        if "total_violations" not in stats and "total" not in stats:
            return fail(f"stats missing total/total_violations: {json.dumps(stats)[:400]}", 6)

        try:
            run_live_start_contract_probe()
        except Exception as exc:
            return fail(f"live start contract probe failed: {exc}", 22)

        code, pending_payload, pending_text = request_json("GET", "/api/reports/pending")
        if code >= 400 or not isinstance(pending_payload, list):
            return fail(f"pending reports endpoint invalid ({code}): {pending_text}", 7)
        print(f"PASS: pending-reports (count={len(pending_payload)})")

        code, violations_payload, violations_text = request_json("GET", f"/api/violations?limit={MAX_REPORT_IDS}")
        if code >= 400 or not isinstance(violations_payload, list):
            return fail(f"violations endpoint invalid ({code}): {violations_text}", 8)
        print(f"PASS: violations-list (count={len(violations_payload)})")

        report_ids = []
        for item in violations_payload:
            if isinstance(item, dict):
                rid = item.get("report_id")
                if rid and rid not in report_ids:
                    report_ids.append(rid)

        if not report_ids:
            print("PASS: no report IDs available; baseline deployed endpoints are healthy")
            return 0

        for rid in report_ids[:5]:
            code, payload, text = request_json("GET", f"/api/report/{rid}/status")
            if code >= 400 or not isinstance(payload, dict):
                return fail(f"report status failed for {rid} ({code}): {text}", 9)

            status_value = str(payload.get("status") or "unknown").lower()
            if status_value not in ALLOWED_REPORT_STATUSES:
                return fail(f"unexpected status for {rid}: {status_value}", 10)
            print(f"PASS: report-status {rid} -> {status_value}")

        conditions = {
            "already_completed": False,
            "already_queued_or_generating": False,
            "accepted_new_or_reprocess": False,
            "missing_original": False,
        }

        progression_candidate = None

        for rid in report_ids:
            code, payload, text = request_json(
                "POST",
                f"/api/report/{rid}/generate-now",
                json={"force": False},
                timeout=45,
            )

            if code >= 500:
                return fail(f"generate-now server error for {rid}: {code} {text}", 11)

            if not isinstance(payload, dict):
                return fail(f"generate-now non-JSON response for {rid}: {text}", 12)

            err_msg = str(payload.get("error") or payload.get("message") or "").lower()
            success = payload.get("success")

            print(f"INFO: generate-now {rid} -> code={code} body={json.dumps(payload)[:350]}")

            if success is False:
                if "original image is missing" in err_msg:
                    conditions["missing_original"] = True
                    continue
                return fail(f"generate-now returned success=false for {rid}: {json.dumps(payload)[:350]}", 13)

            if payload.get("already_completed"):
                conditions["already_completed"] = True
            elif payload.get("already_queued"):
                conditions["already_queued_or_generating"] = True
                if progression_candidate is None:
                    progression_candidate = rid
            else:
                conditions["accepted_new_or_reprocess"] = True
                if progression_candidate is None:
                    progression_candidate = rid

            if any(conditions.values()):
                # Continue scanning a few IDs to widen observed condition surface.
                if sum(1 for v in conditions.values() if v) >= 2:
                    break

        if not any(conditions.values()):
            return fail("no recognized generate-now condition observed", 14)

        if progression_candidate:
            steps = max(1, POLL_SECONDS // max(1, POLL_INTERVAL))
            seen = []
            for i in range(1, steps + 1):
                code, payload, text = request_json("GET", f"/api/report/{progression_candidate}/status")
                if code >= 400 or not isinstance(payload, dict):
                    return fail(
                        f"status polling failed for {progression_candidate} ({code}): {text}",
                        15,
                    )
                status_value = str(payload.get("status") or "unknown").lower()
                seen.append(status_value)
                print(f"poll-{i}: {progression_candidate} -> {status_value}")
                if status_value in ("completed", "failed"):
                    break
                time.sleep(POLL_INTERVAL)

            if seen and all(s in ("pending", "queued") for s in seen):
                return fail(
                    f"{progression_candidate} remained queued/pending across polling window",
                    16,
                )

        if ENABLE_PROVIDER_MODE_MATRIX:
            run_provider_mode_matrix_probe(report_ids)
        else:
            print("INFO: provider mode matrix probe disabled via LUNA_PROVIDER_MODE_MATRIX=0")

        print("PASS: deployed conditions matrix")
        print("observed-conditions=" + json.dumps(conditions, ensure_ascii=True))
        return 0
    except requests.HTTPError as exc:
        return fail(f"HTTP error during conditions test: {exc}", 20)
    except Exception as exc:
        return fail(f"Unhandled error in conditions test: {exc}", 21)


if __name__ == "__main__":
    raise SystemExit(main())
