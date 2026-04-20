import json
import os
import re
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
UPDATED_DIR = ROOT / "Updated_Pipeline_Supabase"
LOCAL_URL = "http://127.0.0.1:5010"
VERCEL_URL = "https://fypa-ai-model-development-integrati.vercel.app"
STARTUP_STATUS_PATH = "/api/system/startup-status"
LOCAL_RUNTIME_CONFIG_PATH = UPDATED_DIR / "frontend" / "js" / "runtime-config.js"
IMAGE_PATH = (UPDATED_DIR / "static" / "images" / "handbook-live.png").resolve()
FALLBACK_PEOPLE_IMAGE = (ROOT / "tmp_people_fallback_bus.jpg").resolve()
FALLBACK_PEOPLE_IMAGE_URL = "https://ultralytics.com/images/bus.jpg"
VENV_PYTHON = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
LOCAL_LOG_PATH = ROOT / "tmp_local_5010_ui_backend.log"
RUNTIME_CONFIG_PATH = "/js/runtime-config.js"
CLOUD_API_BASE_FALLBACKS = [
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
]
RUN_LOCK_PATH = ROOT / "tmp_ui_real_dual_report_playwright.lock"


def _pid_is_running(pid_value: int) -> bool:
    if pid_value <= 0:
        return False
    try:
        os.kill(pid_value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _acquire_single_run_lock() -> Dict[str, Any]:
    lock_payload: Dict[str, Any] = {
        "pid": os.getpid(),
        "script": Path(__file__).name,
        "started_epoch": time.time(),
    }

    for attempt in range(2):
        try:
            fd = os.open(str(RUN_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing_pid = 0
            try:
                raw = RUN_LOCK_PATH.read_text(encoding="utf-8", errors="ignore").strip()
                if raw:
                    existing_pid = int((json.loads(raw) or {}).get("pid") or 0)
            except Exception:
                existing_pid = 0

            stale_lock = False
            if existing_pid > 0:
                stale_lock = not _pid_is_running(existing_pid)
            else:
                try:
                    lock_age_seconds = time.time() - RUN_LOCK_PATH.stat().st_mtime
                    stale_lock = lock_age_seconds > 6 * 3600
                except Exception:
                    stale_lock = False

            if stale_lock and attempt == 0:
                try:
                    RUN_LOCK_PATH.unlink()
                    continue
                except Exception:
                    pass

            owner = f"pid={existing_pid}" if existing_pid > 0 else "unknown owner"
            raise RuntimeError(
                "Another tmp_ui_real_dual_report_playwright.py run appears active "
                f"(lock={RUN_LOCK_PATH}, {owner})"
            )
        except Exception as exc:
            raise RuntimeError(f"Unable to create run lock {RUN_LOCK_PATH}: {exc}") from exc

        try:
            with os.fdopen(fd, "w", encoding="utf-8", errors="ignore") as handle:
                handle.write(json.dumps(lock_payload, ensure_ascii=True))
        except Exception:
            try:
                RUN_LOCK_PATH.unlink()
            except Exception:
                pass
            raise

        return {
            "path": str(RUN_LOCK_PATH),
            "pid": int(lock_payload["pid"]),
            "acquired": True,
        }

    raise RuntimeError(f"Unable to acquire run lock {RUN_LOCK_PATH}")


def _release_single_run_lock(lock_info: Optional[Dict[str, Any]]) -> None:
    if not lock_info:
        return

    lock_path_raw = str(lock_info.get("path") or "").strip()
    lock_path = Path(lock_path_raw) if lock_path_raw else RUN_LOCK_PATH

    try:
        if not lock_path.exists():
            return

        current_pid = os.getpid()
        owner_pid = 0
        try:
            raw = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
            if raw:
                owner_pid = int((json.loads(raw) or {}).get("pid") or 0)
        except Exception:
            owner_pid = 0

        if owner_pid in (0, current_pid) or not _pid_is_running(owner_pid):
            lock_path.unlink()
    except Exception:
        pass


def _tail_text(path: Path, max_chars: int = 2200) -> str:
    if not path.exists():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return raw[-max_chars:]
    except Exception:
        return ""


def _http_ready(base_url: str, timeout_sec: int = 2) -> bool:
    try:
        r = requests.get(f"{base_url}{STARTUP_STATUS_PATH}", timeout=timeout_sec)
        return r.status_code == 200
    except Exception:
        return False


def _wait_http_ready(base_url: str, total_timeout_sec: int) -> bool:
    end = time.time() + total_timeout_sec
    while time.time() < end:
        if _http_ready(base_url, timeout_sec=2):
            return True
        time.sleep(1.5)
    return False


def _extract_host(url_value: str) -> str:
    try:
        return str(urlparse(str(url_value or "")).hostname or "").strip().lower()
    except Exception:
        return ""


def _normalize_base_url(url_value: str) -> str:
    value = str(url_value or "").strip()
    if not value:
        return ""
    return value.rstrip("/")


def _looks_placeholder_cloud_url(url_value: str) -> bool:
    normalized = _normalize_base_url(url_value).lower()
    if not normalized:
        return True
    placeholder_markers = (
        "your-backend",
        "cloud.example",
        "example.test",
        "__",
        "placeholder",
    )
    return any(marker in normalized for marker in placeholder_markers)


def _extract_js_string_value(js_text: str, key: str) -> str:
    if not js_text:
        return ""

    for pattern in (
        rf"{re.escape(key)}\s*:\s*'([^']+)'",
        rf'{re.escape(key)}\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, js_text)
        if match:
            return str(match.group(1) or "").strip()

    return ""


def _fetch_deployed_runtime_config() -> Dict[str, str]:
    runtime_url = f"{VERCEL_URL}{RUNTIME_CONFIG_PATH}"
    result: Dict[str, str] = {
        "runtime_config_url": runtime_url,
        "api_base_url": "",
        "supabase_url": "",
        "supabase_host": "",
        "error": "",
    }

    try:
        resp = requests.get(runtime_url, timeout=25)
        if resp.status_code != 200:
            result["error"] = f"runtime-config HTTP {resp.status_code}"
            return result
        js_text = str(resp.text or "")
    except Exception as exc:
        result["error"] = f"runtime-config fetch failed: {exc}"
        return result

    api_base_url = _extract_js_string_value(js_text, "API_BASE_URL")
    supabase_url = _extract_js_string_value(js_text, "SUPABASE_URL")

    result["api_base_url"] = api_base_url
    result["supabase_url"] = supabase_url
    result["supabase_host"] = _extract_host(supabase_url)
    return result


def _read_local_runtime_config_api_base() -> str:
    if not LOCAL_RUNTIME_CONFIG_PATH.exists():
        return ""
    try:
        js_text = LOCAL_RUNTIME_CONFIG_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return _extract_js_string_value(js_text, "API_BASE_URL")


def _probe_startup_status(base_url: str, timeout_sec: int = 10) -> Tuple[bool, str]:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return False, "empty"
    try:
        resp = requests.get(f"{normalized}{STARTUP_STATUS_PATH}", timeout=timeout_sec)
        if resp.status_code == 200:
            return True, "200"
        return False, f"http_{resp.status_code}"
    except Exception as exc:
        return False, str(exc)


def _resolve_cloud_api_base_url(deployed_runtime: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[str] = []

    for raw in (
        (deployed_runtime or {}).get("api_base_url"),
        _read_local_runtime_config_api_base(),
        _read_dotenv_value("CLOUD_URL"),
        *CLOUD_API_BASE_FALLBACKS,
    ):
        normalized = _normalize_base_url(str(raw or ""))
        if not normalized:
            continue
        if _looks_placeholder_cloud_url(normalized):
            continue
        if normalized in candidates:
            continue
        candidates.append(normalized)

    probes: List[Dict[str, Any]] = []
    resolved = ""
    for candidate in candidates:
        ok, status = _probe_startup_status(candidate, timeout_sec=10)
        probes.append({"base_url": candidate, "ok": ok, "status": status})
        if ok and not resolved:
            resolved = candidate

    return {
        "resolved_api_base_url": resolved,
        "candidates": candidates,
        "probes": probes,
    }


def _read_dotenv_value(key: str) -> str:
    env_path = UPDATED_DIR / ".env"
    if not env_path.exists():
        return ""

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    try:
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line)
            if not match:
                continue
            value = str(match.group(1) or "").strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value.strip()
    except Exception:
        return ""

    return ""


def ensure_local_backend_5010() -> Tuple[Optional[subprocess.Popen], Dict[str, Any]]:
    details: Dict[str, Any] = {
        "mode": "unknown",
        "url": LOCAL_URL,
        "startup_log": str(LOCAL_LOG_PATH),
    }

    deployed_runtime = _fetch_deployed_runtime_config()
    cloud_probe = _resolve_cloud_api_base_url(deployed_runtime)
    resolved_cloud_url = str(cloud_probe.get("resolved_api_base_url") or "").strip()
    local_env_supabase_host = _extract_host(_read_dotenv_value("SUPABASE_URL"))
    deployed_supabase_host = str(deployed_runtime.get("supabase_host") or "").strip().lower()

    details["deployed_runtime"] = {
        "runtime_config_url": deployed_runtime.get("runtime_config_url"),
        "configured_api_base_url": deployed_runtime.get("api_base_url"),
        "resolved_api_base_url": resolved_cloud_url,
        "supabase_host": deployed_supabase_host,
        "error": deployed_runtime.get("error"),
        "api_probe_candidates": cloud_probe.get("candidates") or [],
        "api_probe_results": cloud_probe.get("probes") or [],
    }
    details["local_env_supabase_host"] = local_env_supabase_host

    project_mismatch = bool(
        local_env_supabase_host
        and deployed_supabase_host
        and local_env_supabase_host != deployed_supabase_host
    )
    details["supabase_project_mismatch"] = project_mismatch

    if _wait_http_ready(LOCAL_URL, total_timeout_sec=5):
        details["mode"] = "reused-existing"
        details["supabase_credentials_cleared_for_reprovision"] = False
        if resolved_cloud_url:
            details["cloud_url_candidate"] = resolved_cloud_url
        details["reuse_note"] = "existing backend reused; env overrides not applied"
        return None, details

    if not VENV_PYTHON.exists():
        raise RuntimeError(f"Expected venv python not found: {VENV_PYTHON}")

    env = os.environ.copy()
    env["PORT"] = "5010"
    env["PYTHONUNBUFFERED"] = "1"

    if resolved_cloud_url:
        env["CLOUD_URL"] = resolved_cloud_url
        env["STARTUP_AUTO_PROVISION_LOCAL_MODE"] = "true"
        env.setdefault("STARTUP_AUTO_PROVISION_POLL_INTERVAL_SECONDS", "8")
        details["cloud_url_override"] = resolved_cloud_url

    if project_mismatch and resolved_cloud_url:
        # Force local runtime to re-provision credentials from cloud so reconnect sync
        # targets the same Supabase project as the deployed environment.
        env["SUPABASE_URL"] = ""
        env["SUPABASE_DB_URL"] = ""
        env["SUPABASE_SERVICE_ROLE_KEY"] = ""
        details["supabase_credentials_cleared_for_reprovision"] = True
    else:
        details["supabase_credentials_cleared_for_reprovision"] = False

    if project_mismatch and not resolved_cloud_url:
        details["supabase_reprovision_blocked_reason"] = "no_verified_cloud_url"

    log_fh = LOCAL_LOG_PATH.open("w", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "luna_app.py"],
        cwd=str(UPDATED_DIR),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    details["mode"] = "spawned-new"
    details["pid"] = proc.pid

    if not _wait_http_ready(LOCAL_URL, total_timeout_sec=180):
        proc.poll()
        exit_code = proc.returncode
        if proc.returncode is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        log_fh.close()
        tail = _tail_text(LOCAL_LOG_PATH)
        raise RuntimeError(
            "Local backend on :5010 did not become ready. "
            f"exit_code={exit_code}; log_tail={tail}"
        )

    log_fh.close()
    return proc, details


def ensure_local_provisioning_ready(
    base_url: str,
    cloud_url: str,
    timeout_sec: int = 110,
) -> Dict[str, Any]:
    cloud = _normalize_base_url(cloud_url)
    if not cloud or _looks_placeholder_cloud_url(cloud):
        return {
            "attempted": False,
            "ready": False,
            "reason": "invalid_cloud_url",
            "cloud_url": cloud,
        }

    history: List[Dict[str, Any]] = []
    deadline = time.time() + max(20, int(timeout_sec))
    ready_statuses = {"provisioned", "credentials_present"}

    while time.time() < deadline:
        auto_payload: Dict[str, Any] = {}
        status_payload: Dict[str, Any] = {}
        auto_http = -1
        status_http = -1

        try:
            auto_resp = requests.post(
                f"{base_url}/api/local-mode/provisioning/auto",
                json={"cloud_url": cloud},
                timeout=15,
            )
            auto_http = int(auto_resp.status_code)
            auto_payload = auto_resp.json() if auto_resp.content else {}
        except Exception as auto_exc:
            auto_payload = {"error": str(auto_exc)}

        try:
            status_resp = requests.get(
                f"{base_url}/api/local-mode/provisioning/status",
                timeout=12,
            )
            status_http = int(status_resp.status_code)
            status_payload = status_resp.json() if status_resp.content else {}
        except Exception as status_exc:
            status_payload = {"error": str(status_exc)}

        current_status = str(
            status_payload.get("status")
            or auto_payload.get("status")
            or ""
        ).strip().lower()
        credentials_present = bool(status_payload.get("credentials_present"))

        history.append(
            {
                "auto_http": auto_http,
                "status_http": status_http,
                "status": current_status,
                "credentials_present": credentials_present,
                "auto_error": str(auto_payload.get("error") or "")[:180],
                "status_error": str(status_payload.get("error") or "")[:180],
            }
        )

        if current_status in ready_statuses or credentials_present:
            return {
                "attempted": True,
                "ready": True,
                "status": current_status,
                "credentials_present": credentials_present,
                "attempts": len(history),
                "history": history[-12:],
            }

        if current_status in {"pending_approval", "rejected"}:
            return {
                "attempted": True,
                "ready": False,
                "status": current_status,
                "credentials_present": credentials_present,
                "attempts": len(history),
                "history": history[-12:],
            }

        time.sleep(4)

    final_entry = history[-1] if history else {}
    return {
        "attempted": True,
        "ready": False,
        "status": final_entry.get("status", "timeout"),
        "credentials_present": bool(final_entry.get("credentials_present")),
        "attempts": len(history),
        "history": history[-12:],
    }


def build_test_images() -> List[Path]:
    images: List[Path] = []

    if IMAGE_PATH.exists():
        images.append(IMAGE_PATH)

    if not FALLBACK_PEOPLE_IMAGE.exists():
        try:
            resp = requests.get(FALLBACK_PEOPLE_IMAGE_URL, timeout=20)
            if resp.status_code == 200 and resp.content:
                FALLBACK_PEOPLE_IMAGE.write_bytes(resp.content)
        except Exception:
            pass

    if FALLBACK_PEOPLE_IMAGE.exists():
        images.append(FALLBACK_PEOPLE_IMAGE)

    deduped: List[Path] = []
    seen = set()
    for p in images:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped


def wait_app_ready(page, base_url: str, timeout_ms: int = 180000) -> Dict[str, Any]:
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)

    loader_forced = False
    try:
        page.wait_for_function(
            "() => !document.body.classList.contains('startup-loading')",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        runtime_ready = page.evaluate(
            "() => typeof API !== 'undefined' && typeof Router !== 'undefined'"
        )
        if not runtime_ready:
            raise
        loader_forced = True
        page.evaluate(
            """
            () => {
                const loader = document.getElementById('startupLoader');
                if (loader) {
                    loader.style.display = 'none';
                    loader.setAttribute('aria-hidden', 'true');
                }
                document.body.classList.remove('startup-loading');
            }
            """
        )

    api_base = page.evaluate(
        """
        () => {
            if (typeof API_CONFIG === 'undefined' || !API_CONFIG) return '';
            return String(API_CONFIG.BASE_URL || '');
        }
        """
    )
    return {
        "loader_forced": loader_forced,
        "api_base_url": api_base,
    }


def ensure_nav_visible(page, page_name: str) -> None:
    nav_selector = f"[data-page='{page_name}']"
    locator = page.locator(nav_selector)
    if locator.count() == 0:
        raise RuntimeError(f"Navigation link not found for page={page_name}")

    if locator.first.is_visible():
        return

    for toggle_selector in ("#navToggle", "#navMoreToggle"):
        toggle = page.locator(toggle_selector)
        if toggle.count() > 0 and toggle.first.is_visible():
            toggle.first.click()
            page.wait_for_timeout(250)
            if locator.first.is_visible():
                return

    if not locator.first.is_visible():
        raise RuntimeError(f"Navigation link exists but is hidden for page={page_name}")


def open_settings_modal(page) -> None:
    ensure_nav_visible(page, "settings")
    page.click("[data-page='settings']")
    page.wait_for_selector("#globalSettingsModal.open", timeout=15000)


def activate_processing_settings_tab(page) -> None:
    tab = page.locator(".global-settings-tab[data-global-settings-tab='Psettings']")
    if tab.count() > 0 and tab.first.is_visible():
        tab.first.click()

    # Ensure tab activation even when UI state is partially hidden during startup/modal transitions.
    page.evaluate(
        """
        () => {
            if (window.PPEGlobalSettingsModal && typeof window.PPEGlobalSettingsModal.activateTab === 'function') {
                window.PPEGlobalSettingsModal.activateTab('Psettings');
            }
        }
        """
    )
    page.wait_for_selector("#global-settings-tab-Psettings.active", timeout=12000)


def close_settings_modal(page) -> None:
    close_btn = page.locator("#globalSettingsCloseBtn")
    if close_btn.count() > 0 and close_btn.first.is_visible():
        close_btn.first.click()
        page.wait_for_selector("#globalSettingsModal", state="hidden", timeout=10000)


def run_local_checkup_and_apply_local(page) -> Dict[str, Any]:
    open_settings_modal(page)
    activate_processing_settings_tab(page)

    page.wait_for_selector("#globalRunLocalModeCheckupBtn", state="visible", timeout=20000)

    page.locator("#globalRunLocalModeCheckupBtn").first.click(force=True)
    page.wait_for_function(
        """
        () => {
            const btn = document.querySelector('#globalRunLocalModeCheckupBtn');
            if (!btn) return false;
            return !btn.disabled && /run local mode checkup/i.test(String(btn.textContent || ''));
        }
        """,
        timeout=420000,
    )

    checkup_status = page.locator("#globalLocalModeCheckupStatus").first.inner_text().strip()
    provider_status_after_checkup = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()

    page.wait_for_selector("#globalApplyProviderRoutingBtn", state="visible", timeout=20000)
    page.locator("#globalApplyProviderRoutingBtn").first.click(force=True)
    page.wait_for_function(
        """
        () => {
            const btn = document.querySelector('#globalApplyProviderRoutingBtn');
            if (!btn) return false;
            return !btn.disabled && /apply local profile/i.test(String(btn.textContent || ''));
        }
        """,
        timeout=120000,
    )

    provider_status_after_apply = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()
    close_settings_modal(page)

    return {
        "checkup_status": checkup_status,
        "provider_status_after_checkup": provider_status_after_checkup,
        "provider_status_after_apply": provider_status_after_apply,
    }


def apply_cloud_profile(page) -> Dict[str, Any]:
    open_settings_modal(page)
    activate_processing_settings_tab(page)

    page.wait_for_selector("#globalApplyApiModeBtn", state="visible", timeout=20000)

    page.locator("#globalApplyApiModeBtn").first.click(force=True)
    page.wait_for_function(
        """
        () => {
            const btn = document.querySelector('#globalApplyApiModeBtn');
            if (!btn) return false;
            return !btn.disabled && /switch to api mode/i.test(String(btn.textContent || ''));
        }
        """,
        timeout=120000,
    )

    provider_status = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()
    close_settings_modal(page)

    return {
        "provider_status_after_apply": provider_status,
    }


def _parse_upload_response(data: Dict[str, Any]) -> Dict[str, Any]:
    report_id = str((data or {}).get("report_id") or "").strip()
    report_queued = bool((data or {}).get("report_queued"))
    violations_detected = bool((data or {}).get("violations_detected"))
    try:
        violation_count = int((data or {}).get("violation_count") or 0)
    except Exception:
        violation_count = 0

    payload_summary: Dict[str, Any] = {}
    if isinstance(data, dict):
        for key in (
            "success",
            "source",
            "message",
            "error",
            "report_id",
            "report_queued",
            "violations_detected",
            "violation_count",
            "report_queue_reason",
        ):
            if key not in data:
                continue
            value = data.get(key)
            if isinstance(value, str) and len(value) > 240:
                value = value[:240] + "..."
            payload_summary[key] = value

        if "annotated_image" in data:
            payload_summary["annotated_image_present"] = bool(data.get("annotated_image"))
        if isinstance(data.get("detections"), list):
            payload_summary["detections_count"] = len(data.get("detections") or [])

    return {
        "report_id": report_id,
        "report_queued": report_queued,
        "violations_detected": violations_detected,
        "violation_count": violation_count,
        "report_queue_reason": (data or {}).get("report_queue_reason"),
        "payload_summary": payload_summary,
    }


def _snapshot_live_upload_ui_state(page) -> Dict[str, Any]:
    try:
        return page.evaluate(
            """
            () => {
                const summarize = (id) => {
                    const el = document.getElementById(id);
                    if (!el) {
                        return { exists: false };
                    }
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return {
                        exists: true,
                        display: style.display,
                        visibility: style.visibility,
                        opacity: style.opacity,
                        disabled: !!el.disabled,
                        active: !!(el.classList && el.classList.contains('active')),
                        text: String(el.textContent || '').trim().slice(0, 120),
                        width: Math.round(rect.width || 0),
                        height: Math.round(rect.height || 0),
                    };
                };

                const input = document.getElementById('imageUpload');
                let selectedFile = '';
                try {
                    if (input && input.files && input.files.length > 0) {
                        selectedFile = String(input.files[0].name || '');
                    }
                } catch (e) {
                    selectedFile = '';
                }

                return {
                    path: String(window.location.pathname || ''),
                    hash: String(window.location.hash || ''),
                    uploadModeBtn: summarize('uploadModeBtn'),
                    liveModeBtn: summarize('liveModeBtn'),
                    uploadContainer: summarize('uploadContainer'),
                    liveStreamContainer: summarize('liveStreamContainer'),
                    analyzeBtn: summarize('analyzeBtn'),
                    imageUpload: summarize('imageUpload'),
                    uploadPreview: summarize('uploadPreview'),
                    selectedFile,
                };
            }
            """
        )
    except Exception as exc:
        return {"snapshot_error": str(exc)}


def _ensure_live_upload_mode_ready(page, timeout_ms: int = 45000) -> Dict[str, Any]:
    ensure_nav_visible(page, "live")
    page.click("[data-page='live']")
    page.wait_for_selector("#uploadModeBtn", state="visible", timeout=30000)
    page.wait_for_selector("#imageUpload", state="attached", timeout=15000)

    deadline = time.time() + (timeout_ms / 1000.0)
    attempts = 0
    last_state: Dict[str, Any] = {}

    while time.time() < deadline:
        attempts += 1
        page.click("#uploadModeBtn", force=True)
        try:
            page.wait_for_function(
                """
                () => {
                    const uploadModeBtn = document.getElementById('uploadModeBtn');
                    const uploadContainer = document.getElementById('uploadContainer');
                    const analyzeBtn = document.getElementById('analyzeBtn');
                    const imageUpload = document.getElementById('imageUpload');

                    if (!uploadModeBtn || !uploadContainer || !analyzeBtn || !imageUpload) {
                        return false;
                    }

                    const uploadStyle = window.getComputedStyle(uploadContainer);
                    const analyzeStyle = window.getComputedStyle(analyzeBtn);

                    const uploadVisible = uploadStyle.display !== 'none' && uploadStyle.visibility !== 'hidden';
                    const analyzeVisible = analyzeStyle.display !== 'none' && analyzeStyle.visibility !== 'hidden';

                    return (
                        uploadModeBtn.classList.contains('active') &&
                        uploadVisible &&
                        analyzeVisible &&
                        !analyzeBtn.disabled
                    );
                }
                """,
                timeout=3000,
            )
            return {
                "ready": True,
                "attempts": attempts,
                "ui_state": _snapshot_live_upload_ui_state(page),
            }
        except PlaywrightTimeoutError:
            last_state = _snapshot_live_upload_ui_state(page)
            page.wait_for_timeout(300)

    raise RuntimeError(
        "Upload mode did not become ready in time: "
        f"{json.dumps(last_state, ensure_ascii=True)[:1400]}"
    )


def create_report_by_live_upload(page, image_path: Path, tag: str, attempts: int = 6) -> Dict[str, Any]:
    mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=50000)

    attempt_logs: List[Dict[str, Any]] = []

    for attempt in range(1, attempts + 1):
        try:
            page.wait_for_function(
                """
                () => {
                    const btn = document.querySelector('#analyzeBtn');
                    if (!btn) return false;
                    const style = window.getComputedStyle(btn);
                    return !btn.disabled && style.display !== 'none' && style.visibility !== 'hidden';
                }
                """,
                timeout=25000,
            )
        except PlaywrightTimeoutError:
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "error": "analyze_button_not_ready",
                    "ui_state": _snapshot_live_upload_ui_state(page),
                }
            )
            mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=25000)
            continue

        page.set_input_files("#imageUpload", str(image_path))
        page.wait_for_selector("#uploadPreview", state="visible", timeout=15000)
        page.wait_for_timeout(250)

        upload_request = None
        try:
            with page.expect_request(
                lambda r: "/api/inference/upload" in r.url and r.method.upper() == "POST",
                timeout=35000,
            ) as upload_req_info:
                page.click("#analyzeBtn", force=True)
            upload_request = upload_req_info.value
        except PlaywrightTimeoutError:
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "error": "upload_request_not_dispatched",
                    "ui_state": _snapshot_live_upload_ui_state(page),
                }
            )
            mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=25000)
            continue

        response = None
        response_deadline = time.time() + 125
        while time.time() < response_deadline:
            try:
                response = upload_request.response()
            except Exception:
                response = None
            if response is not None:
                break
            page.wait_for_timeout(300)

        if response is None:
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "error": "upload_response_timeout",
                    "request_url": str(getattr(upload_request, "url", "")),
                    "ui_state": _snapshot_live_upload_ui_state(page),
                }
            )
            mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=30000)
            continue

        try:
            payload = response.json()
        except Exception:
            payload = {"success": False, "error": f"non-json response status={response.status}"}

        parsed = _parse_upload_response(payload if isinstance(payload, dict) else {})
        parsed["attempt"] = attempt
        parsed["http_status"] = response.status
        parsed["request_url"] = str(getattr(upload_request, "url", ""))
        parsed["mode_ready_attempts"] = int(mode_ready.get("attempts") or 0)
        attempt_logs.append(parsed)

        if parsed["report_id"] and parsed["report_queued"] and parsed["violations_detected"]:
            result = dict(parsed)
            result["attempt_logs"] = [dict(item) for item in attempt_logs]
            result["tag"] = tag
            return result

        clear_btn = page.locator("#clearUploadBtn")
        if clear_btn.count() > 0 and clear_btn.first.is_visible():
            clear_btn.first.click()
        mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=25000)
        page.wait_for_timeout(4200)

    raise RuntimeError(f"Failed to queue a new report from upload after {attempts} attempts: {json.dumps(attempt_logs)[:1600]}")


def create_report_with_fallback_images(page, image_paths: List[Path], tag: str) -> Dict[str, Any]:
    if not image_paths:
        raise RuntimeError("No candidate upload images available for report generation")

    failures: List[Dict[str, Any]] = []
    for idx, image_path in enumerate(image_paths):
        attempts_for_candidate = 1 if idx < (len(image_paths) - 1) else 4
        try:
            if idx > 0:
                # Reset and validate upload mode before trying fallback images.
                _ensure_live_upload_mode_ready(page, timeout_ms=35000)

            result = create_report_by_live_upload(
                page,
                image_path,
                tag=tag,
                attempts=attempts_for_candidate,
            )
            result["image_used"] = str(image_path)
            result["candidate_images"] = [str(p) for p in image_paths]
            return result
        except Exception as exc:
            failures.append({"image": str(image_path), "error": str(exc)[:900]})

    raise RuntimeError(f"Failed to queue report for tag={tag} across candidate images: {json.dumps(failures)[:1800]}")


def wait_for_report_card(page, report_id: str, timeout_ms: int = 180000) -> Dict[str, Any]:
    ensure_nav_visible(page, "reports")
    page.click("[data-page='reports']")
    page.wait_for_selector("#reports-list", timeout=30000)

    search = page.locator("#search-reports")
    if search.count() > 0 and search.first.is_visible():
        search.first.fill(report_id)
        search.first.press("Enter")

    deadline = time.time() + (timeout_ms / 1000.0)
    refresh_btn = page.get_by_role("button", name=re.compile("Refresh", re.IGNORECASE))

    while time.time() < deadline:
        card = page.locator(f"#report-{report_id}")
        if card.count() > 0:
            badges = card.locator(".badge").all_inner_texts()
            text = card.first.inner_text().strip()
            return {
                "found": True,
                "badges": badges,
                "text": text,
            }

        text_match_cards = page.locator(f".card:has-text(\"{report_id}\")")
        if text_match_cards.count() > 0:
            badges = text_match_cards.first.locator(".badge").all_inner_texts()
            text = text_match_cards.first.inner_text().strip()
            return {
                "found": True,
                "badges": badges,
                "text": text,
            }

        if refresh_btn.count() > 0 and refresh_btn.first.is_visible():
            refresh_btn.first.click()
        else:
            page.evaluate(
                """
                () => {
                    if (window.ReportsPage && typeof window.ReportsPage.refreshReports === 'function') {
                        window.ReportsPage.refreshReports();
                    }
                }
                """
            )
        page.wait_for_timeout(4500)

    return {"found": False, "badges": [], "text": ""}


def wait_for_report_settled(page, report_id: str, timeout_ms: int = 420000) -> Dict[str, Any]:
    """Wait until report card is no longer in a transient generating/queued state."""
    ensure_nav_visible(page, "reports")
    page.click("[data-page='reports']")
    page.wait_for_selector("#reports-list", timeout=30000)

    search = page.locator("#search-reports")
    if search.count() > 0 and search.first.is_visible():
        search.first.fill(report_id)
        search.first.press("Enter")

    deadline = time.time() + (timeout_ms / 1000.0)
    refresh_btn = page.get_by_role("button", name=re.compile("Refresh", re.IGNORECASE))
    last_seen: Dict[str, Any] = {"found": False, "badges": [], "text": ""}

    transient_markers = (
        "generating",
        "queued",
        "pending",
        "processing",
        "finalizing",
    )

    while time.time() < deadline:
        card = page.locator(f"#report-{report_id}")
        if card.count() == 0:
            card = page.locator(f".card:has-text(\"{report_id}\")")

        if card.count() > 0:
            badges = card.first.locator(".badge").all_inner_texts()
            text = card.first.inner_text().strip()
            joined = " ".join([str(b) for b in badges]).lower() + " " + text.lower()
            last_seen = {
                "found": True,
                "badges": badges,
                "text": text,
            }
            if not any(marker in joined for marker in transient_markers):
                last_seen["settled"] = True
                return last_seen

        if refresh_btn.count() > 0 and refresh_btn.first.is_visible():
            refresh_btn.first.click()
        page.wait_for_timeout(5000)

    last_seen["settled"] = False
    return last_seen


def trigger_local_sync_button(page) -> Dict[str, Any]:
    ensure_nav_visible(page, "live")
    page.click("[data-page='live']")
    sync_button = page.locator("#syncSupabaseFromLiveBtn")

    if sync_button.count() > 0 and sync_button.first.is_visible():
        with page.expect_response(
            lambda r: "/api/reports/sync-local-cache" in r.url and r.request.method.upper() == "POST",
            timeout=120000,
        ) as sync_resp_info:
            sync_button.first.click()

        response = sync_resp_info.value
        try:
            payload = response.json()
        except Exception:
            payload = {"success": False, "error": f"non-json response status={response.status}"}

        page.wait_for_function(
            """
            () => {
                const btn = document.querySelector('#syncSupabaseFromLiveBtn');
                if (!btn) return false;
                return !btn.disabled && String(btn.textContent || '').toLowerCase().includes('sync local cache to supabase');
            }
            """,
            timeout=120000,
        )

        return {
            "method": "live-sync-button",
            "http_status": response.status,
            "payload": payload,
        }

    attempts: List[Dict[str, Any]] = []

    for cycle in range(1, 13):
        cycle_entry: Dict[str, Any] = {"cycle": cycle}
        try:
            with page.expect_response(
                lambda r: "/api/reports/sync-local-cache" in r.url and r.request.method.upper() == "POST",
                timeout=140000,
            ) as sync_resp_info:
                page.context.set_offline(True)
                page.wait_for_timeout(1400)
                page.context.set_offline(False)
                page.evaluate("window.dispatchEvent(new Event('online'))")

            response = sync_resp_info.value
            cycle_entry["http_status"] = response.status
            try:
                payload = response.json()
            except Exception:
                payload = {"success": False, "error": f"non-json response status={response.status}"}
            cycle_entry["payload"] = payload
            attempts.append(cycle_entry)

            if not isinstance(payload, dict):
                break

            deferred = bool(payload.get("deferred"))
            queue_size = int(payload.get("queue_size") or 0)
            if deferred and queue_size > 0:
                page.wait_for_timeout(10000)
                continue

            break
        except Exception as reconnect_error:
            cycle_entry["error"] = str(reconnect_error)
            attempts.append(cycle_entry)
            break

    latest = attempts[-1] if attempts else {}
    return {
        "method": "network-reconnect-auto-sync-loop",
        "attempts": attempts,
        "http_status": latest.get("http_status", -1),
        "payload": latest.get("payload", {}),
        "attempt_count": len(attempts),
    }


def main() -> int:
    candidate_images = build_test_images()
    if not candidate_images:
        raise RuntimeError("No upload images available (default + fallback both missing)")

    started_local_proc: Optional[subprocess.Popen] = None
    run_lock: Optional[Dict[str, Any]] = None
    result: Dict[str, Any] = {
        "cloud": {},
        "local": {},
        "verification": {},
        "candidate_images": [str(p) for p in candidate_images],
    }
    exit_code = 1

    try:
        run_lock = _acquire_single_run_lock()
        result["run_lock"] = {
            "acquired": True,
            "path": run_lock.get("path"),
            "pid": run_lock.get("pid"),
        }

        started_local_proc, local_backend = ensure_local_backend_5010()
        result["local_backend"] = local_backend

        bootstrap_cloud_url = str(local_backend.get("cloud_url_override") or "").strip()
        bootstrap_source = "cloud_url_override"
        if not bootstrap_cloud_url:
            bootstrap_cloud_url = str(
                ((local_backend.get("deployed_runtime") or {}).get("resolved_api_base_url") or "")
            ).strip()
            bootstrap_source = "resolved_api_base_url"

        if bootstrap_cloud_url:
            result["local_backend"]["provisioning_bootstrap_source"] = bootstrap_source
            result["local_backend"]["provisioning_bootstrap"] = ensure_local_provisioning_ready(
                LOCAL_URL,
                bootstrap_cloud_url,
                timeout_sec=130,
            )
        else:
            result["local_backend"]["provisioning_bootstrap"] = {
                "attempted": False,
                "ready": False,
                "reason": "no_bootstrap_cloud_url",
            }

        local_candidate_images = sorted(
            candidate_images,
            key=lambda p: (
                0 if "fallback_bus" in p.name.lower() or "people" in p.name.lower() else 1,
                str(p),
            ),
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            cloud_context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            local_context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            verify_context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")

            # Cloud flow (Vercel UI -> cloud report generation)
            cloud_page = cloud_context.new_page()
            result["cloud"]["app_ready"] = wait_app_ready(cloud_page, VERCEL_URL)
            result["cloud"]["routing"] = apply_cloud_profile(cloud_page)
            cloud_report = create_report_with_fallback_images(cloud_page, candidate_images, tag="cloud")
            result["cloud"]["report"] = cloud_report
            result["cloud"]["reports_card"] = wait_for_report_card(
                cloud_page,
                cloud_report["report_id"],
                timeout_ms=180000,
            )
            cloud_context.close()

            # Local flow (local UI -> local checkup + local report generation)
            local_page = local_context.new_page()
            result["local"]["app_ready"] = wait_app_ready(local_page, LOCAL_URL)
            result["local"]["checkup_and_routing"] = run_local_checkup_and_apply_local(local_page)
            local_report = create_report_with_fallback_images(local_page, local_candidate_images, tag="local")
            result["local"]["report"] = local_report
            result["local"]["status_before_sync"] = wait_for_report_settled(
                local_page,
                local_report["report_id"],
                timeout_ms=420000,
            )
            result["local"]["reports_card_before_sync"] = wait_for_report_card(
                local_page,
                local_report["report_id"],
                timeout_ms=120000,
            )
            result["local"]["manual_sync_click"] = trigger_local_sync_button(local_page)
            local_context.close()

            # Verify local report appears in Vercel Reports after sync
            vercel_verify_page = verify_context.new_page()
            result["verification"]["vercel_ready"] = wait_app_ready(vercel_verify_page, VERCEL_URL)
            result["verification"]["local_report_in_vercel"] = wait_for_report_card(
                vercel_verify_page,
                local_report["report_id"],
                timeout_ms=600000,
            )
            verify_context.close()

            browser.close()

        cloud_id = str(result.get("cloud", {}).get("report", {}).get("report_id") or "").strip()
        local_id = str(result.get("local", {}).get("report", {}).get("report_id") or "").strip()
        local_visible = bool(
            result.get("verification", {})
            .get("local_report_in_vercel", {})
            .get("found")
        )

        result["summary"] = {
            "cloud_report_id": cloud_id,
            "local_report_id": local_id,
            "local_report_visible_in_vercel": local_visible,
            "pass": bool(cloud_id and local_id and local_visible),
        }

        exit_code = 0 if result["summary"]["pass"] else 2

    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, KeyboardInterrupt):
            result["interrupted"] = True
        result["traceback_tail"] = traceback.format_exc()[-3200:]
        if "summary" not in result:
            result["summary"] = {
                "cloud_report_id": str(result.get("cloud", {}).get("report", {}).get("report_id") or "").strip(),
                "local_report_id": str(result.get("local", {}).get("report", {}).get("report_id") or "").strip(),
                "local_report_visible_in_vercel": bool(
                    result.get("verification", {})
                    .get("local_report_in_vercel", {})
                    .get("found")
                ),
                "pass": False,
            }

    finally:
        if started_local_proc is not None:
            started_local_proc.poll()
            if started_local_proc.returncode is None:
                started_local_proc.terminate()
                try:
                    started_local_proc.wait(timeout=12)
                except Exception:
                    started_local_proc.kill()
        _release_single_run_lock(run_lock)

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
