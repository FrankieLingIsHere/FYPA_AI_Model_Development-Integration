# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.
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


# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent
UPDATED_DIR = ROOT / "Updated_Pipeline_Supabase"
LOCAL_URL = "http://127.0.0.1:5010"
VERCEL_URL = "https://fypa-ai-model-development-integrati.vercel.app"
STARTUP_STATUS_PATH = "/api/system/startup-status"
LOCAL_RUNTIME_CONFIG_PATH = UPDATED_DIR / "frontend" / "js" / "runtime-config.js"
IMAGE_PATH = (UPDATED_DIR / "static" / "images" / "handbook-live.png").resolve()
FALLBACK_PEOPLE_IMAGE = (ROOT / "tmp_people_fallback_bus.jpg").resolve()
FALLBACK_PEOPLE_IMAGE_URL = "https://ultralytics.com/images/bus.jpg"
# Prepare venv python for the next step.
VENV_PYTHON = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
LOCAL_LOG_PATH = ROOT / "tmp_local_5010_ui_backend.log"
RUNTIME_CONFIG_PATH = "/js/runtime-config.js"
CLOUD_API_BASE_FALLBACKS = [
    "https://fypaaimodeldevelopment-integration-production.up.railway.app",
]
RUN_LOCK_PATH = ROOT / "tmp_ui_real_dual_report_playwright.lock"


# Section: run the pid is running workflow with clear inputs and outputs.
def _pid_is_running(pid_value: int) -> bool:
    # Choose the correct branch before the workflow continues.
    if pid_value <= 0:
        # Return the prepared result to the caller.
        return False
    try:
        os.kill(pid_value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # Return the prepared result to the caller.
    return True


# Section: run the acquire single run lock workflow with clear inputs and outputs.
def _acquire_single_run_lock() -> Dict[str, Any]:
    lock_payload: Dict[str, Any] = {
        "pid": os.getpid(),
        "script": Path(__file__).name,
        "started_epoch": time.time(),
    }

    # Process each item in this collection using the same rule set.
    for attempt in range(2):
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare fd for the next step.
            fd = os.open(str(RUN_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing_pid = 0
            try:
                # Prepare raw for the next step.
                raw = RUN_LOCK_PATH.read_text(encoding="utf-8", errors="ignore").strip()
                if raw:
                    # Prepare existing pid for the next step.
                    existing_pid = int((json.loads(raw) or {}).get("pid") or 0)
            except Exception:
                existing_pid = 0

            # Prepare stale lock for the next step.
            stale_lock = False
            if existing_pid > 0:
                stale_lock = not _pid_is_running(existing_pid)
            else:
                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Prepare lock age seconds for the next step.
                    lock_age_seconds = time.time() - RUN_LOCK_PATH.stat().st_mtime
                    stale_lock = lock_age_seconds > 6 * 3600
                except Exception:
                    stale_lock = False

            # Choose the correct branch before the workflow continues.
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
            # Surface the failure with enough context for the caller.
            raise RuntimeError(f"Unable to create run lock {RUN_LOCK_PATH}: {exc}") from exc

        # Protect this step so expected failures can fall back cleanly.
        try:
            with os.fdopen(fd, "w", encoding="utf-8", errors="ignore") as handle:
                # Trigger the side effect required for this stage.
                handle.write(json.dumps(lock_payload, ensure_ascii=True))
        except Exception:
            try:
                RUN_LOCK_PATH.unlink()
            except Exception:
                pass
            # Surface the failure with enough context for the caller.
            raise

        # Return the prepared result to the caller.
        return {
            "path": str(RUN_LOCK_PATH),
            "pid": int(lock_payload["pid"]),
            "acquired": True,
        }

    # Surface the failure with enough context for the caller.
    raise RuntimeError(f"Unable to acquire run lock {RUN_LOCK_PATH}")


# Section: run the release single run lock workflow with clear inputs and outputs.
def _release_single_run_lock(lock_info: Optional[Dict[str, Any]]) -> None:
    if not lock_info:
        # Return the prepared result to the caller.
        return

    lock_path_raw = str(lock_info.get("path") or "").strip()
    lock_path = Path(lock_path_raw) if lock_path_raw else RUN_LOCK_PATH

    # Protect this step so expected failures can fall back cleanly.
    try:
        if not lock_path.exists():
            # Return the prepared result to the caller.
            return

        # Prepare current pid for the next step.
        current_pid = os.getpid()
        owner_pid = 0
        try:
            raw = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
            if raw:
                # Prepare owner pid for the next step.
                owner_pid = int((json.loads(raw) or {}).get("pid") or 0)
        except Exception:
            # Prepare owner pid for the next step.
            owner_pid = 0

        # Choose the correct branch before the workflow continues.
        if owner_pid in (0, current_pid) or not _pid_is_running(owner_pid):
            lock_path.unlink()
    except Exception:
        pass


# Section: run the tail text workflow with clear inputs and outputs.
def _tail_text(path: Path, max_chars: int = 2200) -> str:
    # Choose the correct branch before the workflow continues.
    if not path.exists():
        return ""
    try:
        # Prepare raw for the next step.
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return raw[-max_chars:]
    except Exception:
        return ""


# Section: run the http ready workflow with clear inputs and outputs.
def _http_ready(base_url: str, timeout_sec: int = 2) -> bool:
    # Protect this step so expected failures can fall back cleanly.
    try:
        r = requests.get(f"{base_url}{STARTUP_STATUS_PATH}", timeout=timeout_sec)
        # Return the prepared result to the caller.
        return r.status_code == 200
    except Exception:
        return False


# Section: run the wait http ready workflow with clear inputs and outputs.
def _wait_http_ready(base_url: str, total_timeout_sec: int) -> bool:
    end = time.time() + total_timeout_sec
    # Keep the loop active only while the runtime condition is true.
    while time.time() < end:
        if _http_ready(base_url, timeout_sec=2):
            # Return the prepared result to the caller.
            return True
        # Trigger the side effect required for this stage.
        time.sleep(1.5)
    return False


# Section: run the extract host workflow with clear inputs and outputs.
def _extract_host(url_value: str) -> str:
    try:
        return str(urlparse(str(url_value or "")).hostname or "").strip().lower()
    except Exception:
        return ""


# Section: run the normalize base url workflow with clear inputs and outputs.
def _normalize_base_url(url_value: str) -> str:
    # Prepare value for the next step.
    value = str(url_value or "").strip()
    if not value:
        # Return the prepared result to the caller.
        return ""
    return value.rstrip("/")


# Section: run the looks placeholder cloud url workflow with clear inputs and outputs.
def _looks_placeholder_cloud_url(url_value: str) -> bool:
    normalized = _normalize_base_url(url_value).lower()
    if not normalized:
        return True
    # Prepare placeholder markers for the next step.
    placeholder_markers = (
        "your-backend",
        "cloud.example",
        "example.test",
        "__",
        "placeholder",
    )
    return any(marker in normalized for marker in placeholder_markers)


# Section: run the extract js string value workflow with clear inputs and outputs.
def _extract_js_string_value(js_text: str, key: str) -> str:
    # Choose the correct branch before the workflow continues.
    if not js_text:
        # Return the prepared result to the caller.
        return ""

    for pattern in (
        rf"{re.escape(key)}\s*:\s*'([^']+)'",
        rf'{re.escape(key)}\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, js_text)
        if match:
            # Return the prepared result to the caller.
            return str(match.group(1) or "").strip()

    # Return the prepared result to the caller.
    return ""


# Section: run the fetch deployed runtime config workflow with clear inputs and outputs.
def _fetch_deployed_runtime_config() -> Dict[str, str]:
    runtime_url = f"{VERCEL_URL}{RUNTIME_CONFIG_PATH}"
    result: Dict[str, str] = {
        "runtime_config_url": runtime_url,
        "api_base_url": "",
        "supabase_url": "",
        "supabase_host": "",
        "error": "",
    }

    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare resp for the next step.
        resp = requests.get(runtime_url, timeout=25)
        if resp.status_code != 200:
            # Prepare values needed by the next step.
            result["error"] = f"runtime-config HTTP {resp.status_code}"
            return result
        js_text = str(resp.text or "")
    except Exception as exc:
        result["error"] = f"runtime-config fetch failed: {exc}"
        return result

    # Prepare api base url for the next step.
    api_base_url = _extract_js_string_value(js_text, "API_BASE_URL")
    supabase_url = _extract_js_string_value(js_text, "SUPABASE_URL")

    result["api_base_url"] = api_base_url
    result["supabase_url"] = supabase_url
    result["supabase_host"] = _extract_host(supabase_url)
    return result


# Section: run the read local runtime config api base workflow with clear inputs and outputs.
def _read_local_runtime_config_api_base() -> str:
    # Choose the correct branch before the workflow continues.
    if not LOCAL_RUNTIME_CONFIG_PATH.exists():
        # Return the prepared result to the caller.
        return ""
    try:
        js_text = LOCAL_RUNTIME_CONFIG_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return _extract_js_string_value(js_text, "API_BASE_URL")


# Section: run the probe startup status workflow with clear inputs and outputs.
def _probe_startup_status(base_url: str, timeout_sec: int = 10) -> Tuple[bool, str]:
    # Prepare normalized for the next step.
    normalized = _normalize_base_url(base_url)
    if not normalized:
        # Return the prepared result to the caller.
        return False, "empty"
    try:
        resp = requests.get(f"{normalized}{STARTUP_STATUS_PATH}", timeout=timeout_sec)
        if resp.status_code == 200:
            # Return the prepared result to the caller.
            return True, "200"
        return False, f"http_{resp.status_code}"
    except Exception as exc:
        return False, str(exc)


# Section: run the resolve cloud api base url workflow with clear inputs and outputs.
def _resolve_cloud_api_base_url(deployed_runtime: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[str] = []

    # Process each item in this collection using the same rule set.
    for raw in (
        (deployed_runtime or {}).get("api_base_url"),
        _read_local_runtime_config_api_base(),
        _read_dotenv_value("CLOUD_URL"),
        *CLOUD_API_BASE_FALLBACKS,
    ):
        # Prepare normalized for the next step.
        normalized = _normalize_base_url(str(raw or ""))
        if not normalized:
            continue
        if _looks_placeholder_cloud_url(normalized):
            continue
        if normalized in candidates:
            continue
        candidates.append(normalized)

    probes: List[Dict[str, Any]] = []
    # Prepare resolved for the next step.
    resolved = ""
    for candidate in candidates:
        # Prepare values needed by the next step.
        ok, status = _probe_startup_status(candidate, timeout_sec=10)
        probes.append({"base_url": candidate, "ok": ok, "status": status})
        if ok and not resolved:
            # Prepare resolved for the next step.
            resolved = candidate

    return {
        "resolved_api_base_url": resolved,
        "candidates": candidates,
        "probes": probes,
    }


# Section: run the read dotenv value workflow with clear inputs and outputs.
def _read_dotenv_value(key: str) -> str:
    # Prepare env path for the next step.
    env_path = UPDATED_DIR / ".env"
    if not env_path.exists():
        # Return the prepared result to the caller.
        return ""

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    try:
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            # Prepare match for the next step.
            match = pattern.match(line)
            if not match:
                continue
            value = str(match.group(1) or "").strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                # Prepare value for the next step.
                value = value[1:-1]
            return value.strip()
    except Exception:
        # Return the prepared result to the caller.
        return ""

    # Return the prepared result to the caller.
    return ""


# Section: run the ensure local backend 5010 workflow with clear inputs and outputs.
def ensure_local_backend_5010() -> Tuple[Optional[subprocess.Popen], Dict[str, Any]]:
    details: Dict[str, Any] = {
        "mode": "unknown",
        "url": LOCAL_URL,
        "startup_log": str(LOCAL_LOG_PATH),
    }

    # Prepare deployed runtime for the next step.
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
    # Prepare values needed by the next step.
    details["local_env_supabase_host"] = local_env_supabase_host

    project_mismatch = bool(
        local_env_supabase_host
        and deployed_supabase_host
        and local_env_supabase_host != deployed_supabase_host
    )
    details["supabase_project_mismatch"] = project_mismatch

    # Choose the correct branch before the workflow continues.
    if _wait_http_ready(LOCAL_URL, total_timeout_sec=5):
        # Prepare values needed by the next step.
        details["mode"] = "reused-existing"
        details["supabase_credentials_cleared_for_reprovision"] = False
        if resolved_cloud_url:
            # Prepare values needed by the next step.
            details["cloud_url_candidate"] = resolved_cloud_url
        details["reuse_note"] = "existing backend reused; env overrides not applied"
        return None, details

    if not VENV_PYTHON.exists():
        raise RuntimeError(f"Expected venv python not found: {VENV_PYTHON}")

    # Prepare env for the next step.
    env = os.environ.copy()
    env["PORT"] = "5010"
    env["PYTHONUNBUFFERED"] = "1"

    if resolved_cloud_url:
        # Prepare values needed by the next step.
        env["CLOUD_URL"] = resolved_cloud_url
        env["STARTUP_AUTO_PROVISION_LOCAL_MODE"] = "true"
        env.setdefault("STARTUP_AUTO_PROVISION_POLL_INTERVAL_SECONDS", "8")
        details["cloud_url_override"] = resolved_cloud_url

    # Choose the correct branch before the workflow continues.
    if project_mismatch and resolved_cloud_url:
        # Force local runtime to re-provision credentials from cloud so reconnect sync
        # targets the same Supabase project as the deployed environment.
        env["SUPABASE_URL"] = ""
        env["SUPABASE_DB_URL"] = ""
        env["SUPABASE_SERVICE_ROLE_KEY"] = ""
        details["supabase_credentials_cleared_for_reprovision"] = True
    else:
        details["supabase_credentials_cleared_for_reprovision"] = False

    # Choose the correct branch before the workflow continues.
    if project_mismatch and not resolved_cloud_url:
        details["supabase_reprovision_blocked_reason"] = "no_verified_cloud_url"

    log_fh = LOCAL_LOG_PATH.open("w", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "casm_app.py"],
        cwd=str(UPDATED_DIR),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    # Prepare values needed by the next step.
    details["mode"] = "spawned-new"
    details["pid"] = proc.pid

    if not _wait_http_ready(LOCAL_URL, total_timeout_sec=180):
        # Trigger the side effect required for this stage.
        proc.poll()
        exit_code = proc.returncode
        if proc.returncode is None:
            # Trigger the side effect required for this stage.
            proc.terminate()
            try:
                # Trigger the side effect required for this stage.
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        log_fh.close()
        # Prepare tail for the next step.
        tail = _tail_text(LOCAL_LOG_PATH)
        raise RuntimeError(
            "Local backend on :5010 did not become ready. "
            f"exit_code={exit_code}; log_tail={tail}"
        )

    # Trigger the side effect required for this stage.
    log_fh.close()
    return proc, details


# Section: run the ensure local provisioning ready workflow with clear inputs and outputs.
def ensure_local_provisioning_ready(
    base_url: str,
    cloud_url: str,
    timeout_sec: int = 110,
) -> Dict[str, Any]:
    # Prepare cloud for the next step.
    cloud = _normalize_base_url(cloud_url)
    if not cloud or _looks_placeholder_cloud_url(cloud):
        # Return the prepared result to the caller.
        return {
            "attempted": False,
            "ready": False,
            "reason": "invalid_cloud_url",
            "cloud_url": cloud,
        }

    history: List[Dict[str, Any]] = []
    # Prepare deadline for the next step.
    deadline = time.time() + max(20, int(timeout_sec))
    ready_statuses = {"provisioned", "credentials_present"}

    while time.time() < deadline:
        auto_payload: Dict[str, Any] = {}
        status_payload: Dict[str, Any] = {}
        # Prepare auto http for the next step.
        auto_http = -1
        status_http = -1

        try:
            # Prepare auto resp for the next step.
            auto_resp = requests.post(
                f"{base_url}/api/local-mode/provisioning/auto",
                json={"cloud_url": cloud},
                timeout=15,
            )
            auto_http = int(auto_resp.status_code)
            auto_payload = auto_resp.json() if auto_resp.content else {}
        except Exception as auto_exc:
            auto_payload = {"error": str(auto_exc)}

        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare status resp for the next step.
            status_resp = requests.get(
                f"{base_url}/api/local-mode/provisioning/status",
                timeout=12,
            )
            status_http = int(status_resp.status_code)
            status_payload = status_resp.json() if status_resp.content else {}
        except Exception as status_exc:
            status_payload = {"error": str(status_exc)}

        # Prepare current status for the next step.
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

        # Choose the correct branch before the workflow continues.
        if current_status in ready_statuses or credentials_present:
            # Return the prepared result to the caller.
            return {
                "attempted": True,
                "ready": True,
                "status": current_status,
                "credentials_present": credentials_present,
                "attempts": len(history),
                "history": history[-12:],
            }

        # Choose the correct branch before the workflow continues.
        if current_status in {"pending_approval", "rejected"}:
            # Return the prepared result to the caller.
            return {
                "attempted": True,
                "ready": False,
                "status": current_status,
                "credentials_present": credentials_present,
                "attempts": len(history),
                "history": history[-12:],
            }

        # Trigger the side effect required for this stage.
        time.sleep(4)

    # Prepare final entry for the next step.
    final_entry = history[-1] if history else {}
    return {
        "attempted": True,
        "ready": False,
        "status": final_entry.get("status", "timeout"),
        "credentials_present": bool(final_entry.get("credentials_present")),
        "attempts": len(history),
        "history": history[-12:],
    }


# Section: run the build test images workflow with clear inputs and outputs.
def build_test_images() -> List[Path]:
    images: List[Path] = []

    # Choose the correct branch before the workflow continues.
    if IMAGE_PATH.exists():
        # Trigger the side effect required for this stage.
        images.append(IMAGE_PATH)

    if not FALLBACK_PEOPLE_IMAGE.exists():
        try:
            # Prepare resp for the next step.
            resp = requests.get(FALLBACK_PEOPLE_IMAGE_URL, timeout=20)
            if resp.status_code == 200 and resp.content:
                # Trigger the side effect required for this stage.
                FALLBACK_PEOPLE_IMAGE.write_bytes(resp.content)
        except Exception:
            pass

    # Choose the correct branch before the workflow continues.
    if FALLBACK_PEOPLE_IMAGE.exists():
        # Trigger the side effect required for this stage.
        images.append(FALLBACK_PEOPLE_IMAGE)

    deduped: List[Path] = []
    seen = set()
    for p in images:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        # Trigger the side effect required for this stage.
        deduped.append(p)
    # Return the prepared result to the caller.
    return deduped


# Section: run the wait app ready workflow with clear inputs and outputs.
def wait_app_ready(page, base_url: str, timeout_ms: int = 180000) -> Dict[str, Any]:
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)

    loader_forced = False
    try:
        # Trigger the side effect required for this stage.
        page.wait_for_function(
            "() => !document.body.classList.contains('startup-loading')",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        runtime_ready = page.evaluate(
            "() => typeof API !== 'undefined' && typeof Router !== 'undefined'"
        )
        if not runtime_ready:
            # Surface the failure with enough context for the caller.
            raise
        # Prepare loader forced for the next step.
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

    # Prepare api base for the next step.
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


# Section: run the ensure nav visible workflow with clear inputs and outputs.
def ensure_nav_visible(page, page_name: str) -> None:
    # Prepare nav selector for the next step.
    nav_selector = f"[data-page='{page_name}']"
    locator = page.locator(nav_selector)
    if locator.count() == 0:
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Navigation link not found for page={page_name}")

    if locator.first.is_visible():
        return

    for toggle_selector in ("#navToggle", "#navMoreToggle"):
        toggle = page.locator(toggle_selector)
        if toggle.count() > 0 and toggle.first.is_visible():
            # Trigger the side effect required for this stage.
            toggle.first.click()
            page.wait_for_timeout(250)
            if locator.first.is_visible():
                # Return the prepared result to the caller.
                return

    # Choose the correct branch before the workflow continues.
    if not locator.first.is_visible():
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Navigation link exists but is hidden for page={page_name}")


# Section: run the open settings modal workflow with clear inputs and outputs.
def open_settings_modal(page) -> None:
    ensure_nav_visible(page, "settings")
    page.click("[data-page='settings']")
    page.wait_for_selector("#globalSettingsModal.open", timeout=15000)


# Section: run the activate processing settings tab workflow with clear inputs and outputs.
def activate_processing_settings_tab(page) -> None:
    # Prepare tab for the next step.
    tab = page.locator(".global-settings-tab[data-global-settings-tab='Psettings']")
    if tab.count() > 0 and tab.first.is_visible():
        # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
    page.wait_for_selector("#global-settings-tab-Psettings.active", timeout=12000)


# Section: run the close settings modal workflow with clear inputs and outputs.
def close_settings_modal(page) -> None:
    close_btn = page.locator("#globalSettingsCloseBtn")
    if close_btn.count() > 0 and close_btn.first.is_visible():
        # Trigger the side effect required for this stage.
        close_btn.first.click()
        page.wait_for_selector("#globalSettingsModal", state="hidden", timeout=10000)


# Section: run the run local checkup and apply local workflow with clear inputs and outputs.
def run_local_checkup_and_apply_local(page) -> Dict[str, Any]:
    # Trigger the side effect required for this stage.
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

    # Prepare checkup status for the next step.
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

    # Prepare provider status after apply for the next step.
    provider_status_after_apply = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()
    close_settings_modal(page)

    return {
        "checkup_status": checkup_status,
        "provider_status_after_checkup": provider_status_after_checkup,
        "provider_status_after_apply": provider_status_after_apply,
    }


# Section: run the apply cloud profile workflow with clear inputs and outputs.
def apply_cloud_profile(page) -> Dict[str, Any]:
    # Trigger the side effect required for this stage.
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

    # Prepare provider status for the next step.
    provider_status = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()
    close_settings_modal(page)

    return {
        "provider_status_after_apply": provider_status,
    }


# Section: run the parse upload response workflow with clear inputs and outputs.
def _parse_upload_response(data: Dict[str, Any]) -> Dict[str, Any]:
    # Prepare report id for the next step.
    report_id = str((data or {}).get("report_id") or "").strip()
    report_queued = bool((data or {}).get("report_queued"))
    violations_detected = bool((data or {}).get("violations_detected"))
    try:
        # Prepare violation count for the next step.
        violation_count = int((data or {}).get("violation_count") or 0)
    except Exception:
        violation_count = 0

    payload_summary: Dict[str, Any] = {}
    # Choose the correct branch before the workflow continues.
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
            # Choose the correct branch before the workflow continues.
            if key not in data:
                continue
            value = data.get(key)
            if isinstance(value, str) and len(value) > 240:
                # Prepare value for the next step.
                value = value[:240] + "..."
            payload_summary[key] = value

        # Choose the correct branch before the workflow continues.
        if "annotated_image" in data:
            payload_summary["annotated_image_present"] = bool(data.get("annotated_image"))
        if isinstance(data.get("detections"), list):
            # Prepare values needed by the next step.
            payload_summary["detections_count"] = len(data.get("detections") or [])

    # Return the prepared result to the caller.
    return {
        "report_id": report_id,
        "report_queued": report_queued,
        "violations_detected": violations_detected,
        "violation_count": violation_count,
        "report_queue_reason": (data or {}).get("report_queue_reason"),
        "payload_summary": payload_summary,
    }


# Section: run the snapshot live upload ui state workflow with clear inputs and outputs.
def _snapshot_live_upload_ui_state(page) -> Dict[str, Any]:
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Return the prepared result to the caller.
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
        # Return the prepared result to the caller.
        return {"snapshot_error": str(exc)}


# Section: run the ensure live upload mode ready workflow with clear inputs and outputs.
def _ensure_live_upload_mode_ready(page, timeout_ms: int = 45000) -> Dict[str, Any]:
    # Trigger the side effect required for this stage.
    ensure_nav_visible(page, "live")
    page.click("[data-page='live']")
    page.wait_for_selector("#uploadModeBtn", state="visible", timeout=30000)
    page.wait_for_selector("#imageUpload", state="attached", timeout=15000)

    deadline = time.time() + (timeout_ms / 1000.0)
    attempts = 0
    last_state: Dict[str, Any] = {}

    # Keep the loop active only while the runtime condition is true.
    while time.time() < deadline:
        attempts += 1
        # Trigger the side effect required for this stage.
        page.click("#uploadModeBtn", force=True)
        try:
            # Trigger the side effect required for this stage.
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
            # Return the prepared result to the caller.
            return {
                "ready": True,
                "attempts": attempts,
                "ui_state": _snapshot_live_upload_ui_state(page),
            }
        except PlaywrightTimeoutError:
            last_state = _snapshot_live_upload_ui_state(page)
            page.wait_for_timeout(300)

    # Surface the failure with enough context for the caller.
    raise RuntimeError(
        "Upload mode did not become ready in time: "
        f"{json.dumps(last_state, ensure_ascii=True)[:1400]}"
    )


# Section: run the create report by live upload workflow with clear inputs and outputs.
def create_report_by_live_upload(page, image_path: Path, tag: str, attempts: int = 6) -> Dict[str, Any]:
    mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=50000)

    attempt_logs: List[Dict[str, Any]] = []

    # Process each item in this collection using the same rule set.
    for attempt in range(1, attempts + 1):
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Trigger the side effect required for this stage.
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
            # Trigger the side effect required for this stage.
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "error": "analyze_button_not_ready",
                    "ui_state": _snapshot_live_upload_ui_state(page),
                }
            )
            mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=25000)
            continue

        # Trigger the side effect required for this stage.
        page.set_input_files("#imageUpload", str(image_path))
        page.wait_for_selector("#uploadPreview", state="visible", timeout=15000)
        page.wait_for_timeout(250)

        upload_request = None
        try:
            # Open the managed resource only for the block that needs it.
            with page.expect_request(
                lambda r: "/api/inference/upload" in r.url and r.method.upper() == "POST",
                timeout=35000,
            ) as upload_req_info:
                # Trigger the side effect required for this stage.
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
            # Prepare mode ready for the next step.
            mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=25000)
            continue

        # Prepare response for the next step.
        response = None
        response_deadline = time.time() + 125
        while time.time() < response_deadline:
            try:
                # Prepare response for the next step.
                response = upload_request.response()
            except Exception:
                response = None
            # Choose the correct branch before the workflow continues.
            if response is not None:
                break
            page.wait_for_timeout(300)

        # Choose the correct branch before the workflow continues.
        if response is None:
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "error": "upload_response_timeout",
                    "request_url": str(getattr(upload_request, "url", "")),
                    "ui_state": _snapshot_live_upload_ui_state(page),
                }
            )
            # Prepare mode ready for the next step.
            mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=30000)
            continue

        # Protect this step so expected failures can fall back cleanly.
        try:
            payload = response.json()
        except Exception:
            payload = {"success": False, "error": f"non-json response status={response.status}"}

        parsed = _parse_upload_response(payload if isinstance(payload, dict) else {})
        parsed["attempt"] = attempt
        parsed["http_status"] = response.status
        parsed["request_url"] = str(getattr(upload_request, "url", ""))
        # Prepare values needed by the next step.
        parsed["mode_ready_attempts"] = int(mode_ready.get("attempts") or 0)
        attempt_logs.append(parsed)

        if parsed["report_id"] and parsed["report_queued"] and parsed["violations_detected"]:
            # Prepare result for the next step.
            result = dict(parsed)
            result["attempt_logs"] = [dict(item) for item in attempt_logs]
            result["tag"] = tag
            return result

        # Prepare clear btn for the next step.
        clear_btn = page.locator("#clearUploadBtn")
        if clear_btn.count() > 0 and clear_btn.first.is_visible():
            clear_btn.first.click()
        mode_ready = _ensure_live_upload_mode_ready(page, timeout_ms=25000)
        page.wait_for_timeout(4200)

    # Surface the failure with enough context for the caller.
    raise RuntimeError(f"Failed to queue a new report from upload after {attempts} attempts: {json.dumps(attempt_logs)[:1600]}")


# Section: run the create report with fallback images workflow with clear inputs and outputs.
def create_report_with_fallback_images(page, image_paths: List[Path], tag: str) -> Dict[str, Any]:
    if not image_paths:
        # Surface the failure with enough context for the caller.
        raise RuntimeError("No candidate upload images available for report generation")

    failures: List[Dict[str, Any]] = []
    for idx, image_path in enumerate(image_paths):
        attempts_for_candidate = 1 if idx < (len(image_paths) - 1) else 4
        try:
            # Choose the correct branch before the workflow continues.
            if idx > 0:
                # Reset and validate upload mode before trying fallback images.
                # Trigger the side effect required for this stage.
                _ensure_live_upload_mode_ready(page, timeout_ms=35000)

            result = create_report_by_live_upload(
                page,
                image_path,
                tag=tag,
                attempts=attempts_for_candidate,
            )
            # Prepare values needed by the next step.
            result["image_used"] = str(image_path)
            result["candidate_images"] = [str(p) for p in image_paths]
            return result
        except Exception as exc:
            failures.append({"image": str(image_path), "error": str(exc)[:900]})

    # Surface the failure with enough context for the caller.
    raise RuntimeError(f"Failed to queue report for tag={tag} across candidate images: {json.dumps(failures)[:1800]}")


# Section: run the wait for report card workflow with clear inputs and outputs.
def wait_for_report_card(page, report_id: str, timeout_ms: int = 180000) -> Dict[str, Any]:
    ensure_nav_visible(page, "reports")
    page.click("[data-page='reports']")
    page.wait_for_selector("#reports-list", timeout=30000)

    search = page.locator("#search-reports")
    # Choose the correct branch before the workflow continues.
    if search.count() > 0 and search.first.is_visible():
        # Trigger the side effect required for this stage.
        search.first.fill(report_id)
        search.first.press("Enter")

    deadline = time.time() + (timeout_ms / 1000.0)
    refresh_btn = page.get_by_role("button", name=re.compile("Refresh", re.IGNORECASE))

    while time.time() < deadline:
        card = page.locator(f"#report-{report_id}")
        if card.count() > 0:
            # Prepare badges for the next step.
            badges = card.locator(".badge").all_inner_texts()
            text = card.first.inner_text().strip()
            return {
                "found": True,
                "badges": badges,
                "text": text,
            }

        # Prepare text match cards for the next step.
        text_match_cards = page.locator(f".card:has-text(\"{report_id}\")")
        if text_match_cards.count() > 0:
            # Prepare badges for the next step.
            badges = text_match_cards.first.locator(".badge").all_inner_texts()
            text = text_match_cards.first.inner_text().strip()
            return {
                "found": True,
                "badges": badges,
                "text": text,
            }

        # Choose the correct branch before the workflow continues.
        if refresh_btn.count() > 0 and refresh_btn.first.is_visible():
            # Trigger the side effect required for this stage.
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
        # Trigger the side effect required for this stage.
        page.wait_for_timeout(4500)

    # Return the prepared result to the caller.
    return {"found": False, "badges": [], "text": ""}


# Section: run the wait for report settled workflow with clear inputs and outputs.
def wait_for_report_settled(page, report_id: str, timeout_ms: int = 420000) -> Dict[str, Any]:
    """Wait until report card is no longer in a transient generating/queued state."""
    ensure_nav_visible(page, "reports")
    page.click("[data-page='reports']")
    page.wait_for_selector("#reports-list", timeout=30000)

    # Prepare search for the next step.
    search = page.locator("#search-reports")
    if search.count() > 0 and search.first.is_visible():
        # Trigger the side effect required for this stage.
        search.first.fill(report_id)
        search.first.press("Enter")

    deadline = time.time() + (timeout_ms / 1000.0)
    refresh_btn = page.get_by_role("button", name=re.compile("Refresh", re.IGNORECASE))
    last_seen: Dict[str, Any] = {"found": False, "badges": [], "text": ""}

    # Prepare transient markers for the next step.
    transient_markers = (
        "generating",
        "queued",
        "pending",
        "processing",
        "finalizing",
    )

    while time.time() < deadline:
        # Prepare card for the next step.
        card = page.locator(f"#report-{report_id}")
        if card.count() == 0:
            # Prepare card for the next step.
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
            # Choose the correct branch before the workflow continues.
            if not any(marker in joined for marker in transient_markers):
                # Prepare values needed by the next step.
                last_seen["settled"] = True
                return last_seen

        # Choose the correct branch before the workflow continues.
        if refresh_btn.count() > 0 and refresh_btn.first.is_visible():
            refresh_btn.first.click()
        page.wait_for_timeout(5000)

    # Prepare values needed by the next step.
    last_seen["settled"] = False
    return last_seen


# Section: run the trigger local sync button workflow with clear inputs and outputs.
def trigger_local_sync_button(page) -> Dict[str, Any]:
    ensure_nav_visible(page, "live")
    page.click("[data-page='live']")
    sync_button = page.locator("#syncSupabaseFromLiveBtn")

    # Choose the correct branch before the workflow continues.
    if sync_button.count() > 0 and sync_button.first.is_visible():
        # Open the managed resource only for the block that needs it.
        with page.expect_response(
            lambda r: "/api/reports/sync-local-cache" in r.url and r.request.method.upper() == "POST",
            timeout=120000,
        ) as sync_resp_info:
            # Trigger the side effect required for this stage.
            sync_button.first.click()

        response = sync_resp_info.value
        try:
            payload = response.json()
        except Exception:
            payload = {"success": False, "error": f"non-json response status={response.status}"}

        # Trigger the side effect required for this stage.
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

        # Return the prepared result to the caller.
        return {
            "method": "live-sync-button",
            "http_status": response.status,
            "payload": payload,
        }

    attempts: List[Dict[str, Any]] = []

    # Process each item in this collection using the same rule set.
    for cycle in range(1, 13):
        cycle_entry: Dict[str, Any] = {"cycle": cycle}
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Open the managed resource only for the block that needs it.
            with page.expect_response(
                lambda r: "/api/reports/sync-local-cache" in r.url and r.request.method.upper() == "POST",
                timeout=140000,
            ) as sync_resp_info:
                # Trigger the side effect required for this stage.
                page.context.set_offline(True)
                page.wait_for_timeout(1400)
                page.context.set_offline(False)
                page.evaluate("window.dispatchEvent(new Event('online'))")

            # Prepare response for the next step.
            response = sync_resp_info.value
            cycle_entry["http_status"] = response.status
            try:
                payload = response.json()
            except Exception:
                # Prepare payload for the next step.
                payload = {"success": False, "error": f"non-json response status={response.status}"}
            cycle_entry["payload"] = payload
            attempts.append(cycle_entry)

            # Choose the correct branch before the workflow continues.
            if not isinstance(payload, dict):
                break

            deferred = bool(payload.get("deferred"))
            queue_size = int(payload.get("queue_size") or 0)
            if deferred and queue_size > 0:
                # Trigger the side effect required for this stage.
                page.wait_for_timeout(10000)
                continue

            break
        except Exception as reconnect_error:
            # Prepare values needed by the next step.
            cycle_entry["error"] = str(reconnect_error)
            attempts.append(cycle_entry)
            break

    # Prepare latest for the next step.
    latest = attempts[-1] if attempts else {}
    return {
        "method": "network-reconnect-auto-sync-loop",
        "attempts": attempts,
        "http_status": latest.get("http_status", -1),
        "payload": latest.get("payload", {}),
        "attempt_count": len(attempts),
    }


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare candidate images for the next step.
    candidate_images = build_test_images()
    if not candidate_images:
        # Surface the failure with enough context for the caller.
        raise RuntimeError("No upload images available (default + fallback both missing)")

    started_local_proc: Optional[subprocess.Popen] = None
    run_lock: Optional[Dict[str, Any]] = None
    result: Dict[str, Any] = {
        "cloud": {},
        "local": {},
        "verification": {},
        "candidate_images": [str(p) for p in candidate_images],
    }
    # Prepare exit code for the next step.
    exit_code = 1

    try:
        # Prepare run lock for the next step.
        run_lock = _acquire_single_run_lock()
        result["run_lock"] = {
            "acquired": True,
            "path": run_lock.get("path"),
            "pid": run_lock.get("pid"),
        }

        started_local_proc, local_backend = ensure_local_backend_5010()
        result["local_backend"] = local_backend

        # Prepare bootstrap cloud url for the next step.
        bootstrap_cloud_url = str(local_backend.get("cloud_url_override") or "").strip()
        bootstrap_source = "cloud_url_override"
        if not bootstrap_cloud_url:
            # Prepare bootstrap cloud url for the next step.
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
            # Prepare values needed by the next step.
            result["local_backend"]["provisioning_bootstrap"] = {
                "attempted": False,
                "ready": False,
                "reason": "no_bootstrap_cloud_url",
            }

        # Prepare local candidate images for the next step.
        local_candidate_images = sorted(
            candidate_images,
            key=lambda p: (
                0 if "fallback_bus" in p.name.lower() or "people" in p.name.lower() else 1,
                str(p),
            ),
        )

        with sync_playwright() as p:
            # Prepare browser for the next step.
            browser = p.chromium.launch(headless=True)
            cloud_context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            local_context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            verify_context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")

            # Cloud flow (Vercel UI -> cloud report generation)
            cloud_page = cloud_context.new_page()
            result["cloud"]["app_ready"] = wait_app_ready(cloud_page, VERCEL_URL)
            result["cloud"]["routing"] = apply_cloud_profile(cloud_page)
            # Prepare cloud report for the next step.
            cloud_report = create_report_with_fallback_images(cloud_page, candidate_images, tag="cloud")
            result["cloud"]["report"] = cloud_report
            result["cloud"]["reports_card"] = wait_for_report_card(
                cloud_page,
                cloud_report["report_id"],
                timeout_ms=180000,
            )
            cloud_context.close()

            # Local flow (local UI -> local checkup + local report generation)
            # Prepare local page for the next step.
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
            # Prepare values needed by the next step.
            result["local"]["reports_card_before_sync"] = wait_for_report_card(
                local_page,
                local_report["report_id"],
                timeout_ms=120000,
            )
            result["local"]["manual_sync_click"] = trigger_local_sync_button(local_page)
            local_context.close()

            # Verify local report appears in Vercel Reports after sync
            # Prepare vercel verify page for the next step.
            vercel_verify_page = verify_context.new_page()
            result["verification"]["vercel_ready"] = wait_app_ready(vercel_verify_page, VERCEL_URL)
            result["verification"]["local_report_in_vercel"] = wait_for_report_card(
                vercel_verify_page,
                local_report["report_id"],
                timeout_ms=600000,
            )
            verify_context.close()

            # Trigger the side effect required for this stage.
            browser.close()

        # Prepare cloud id for the next step.
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

        # Prepare exit code for the next step.
        exit_code = 0 if result["summary"]["pass"] else 2

    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, KeyboardInterrupt):
            # Prepare values needed by the next step.
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
        # Choose the correct branch before the workflow continues.
        if started_local_proc is not None:
            # Trigger the side effect required for this stage.
            started_local_proc.poll()
            if started_local_proc.returncode is None:
                # Trigger the side effect required for this stage.
                started_local_proc.terminate()
                try:
                    # Trigger the side effect required for this stage.
                    started_local_proc.wait(timeout=12)
                except Exception:
                    started_local_proc.kill()
        _release_single_run_lock(run_lock)

    # Trigger the side effect required for this stage.
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return exit_code


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    raise SystemExit(main())
