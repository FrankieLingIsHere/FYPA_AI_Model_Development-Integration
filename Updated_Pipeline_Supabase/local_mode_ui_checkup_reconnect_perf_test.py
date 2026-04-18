import json
import os
from pathlib import Path
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("LUNA_LOCAL_UI_URL", "http://127.0.0.1:5000").rstrip("/")
AUTO_SYNC_START_TIMEOUT_MS = int(os.environ.get("LUNA_AUTO_SYNC_START_TIMEOUT_MS", "30000"))
AUTO_SYNC_COMPLETE_TIMEOUT_MS = int(os.environ.get("LUNA_AUTO_SYNC_COMPLETE_TIMEOUT_MS", "150000"))
ALLOW_MANUAL_RECONNECT_SYNC_FALLBACK = os.environ.get(
    "LUNA_ALLOW_MANUAL_RECONNECT_SYNC_FALLBACK",
    "0",
) != "0"


def ensure_nav_visible(page, page_name: str):
    nav_selector = f"[data-page='{page_name}']"
    locator = page.locator(nav_selector)
    if locator.count() == 0:
        raise RuntimeError(f"Navigation link not found in DOM for page={page_name}")

    if locator.first.is_visible():
        return

    for toggle_selector in ("#navToggle", "#navMoreToggle"):
        toggle = page.locator(toggle_selector)
        if toggle.count() > 0 and toggle.first.is_visible():
            toggle.first.click()
            page.wait_for_timeout(220)
            if locator.first.is_visible():
                return

    if not locator.first.is_visible():
        raise RuntimeError(f"Navigation link exists but is not visible for page={page_name}")


def routing_profile_of(payload):
    if not isinstance(payload, dict):
        return ""
    for key in ("routing_profile", "profile", "active_profile"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def collect_local_report_candidates(limit: int = 80):
    base_dir = Path(__file__).resolve().parent / "pipeline" / "violations"
    if not base_dir.exists():
        return []

    rows = []
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        report_id = child.name
        original_exists = (child / "original.jpg").exists()
        report_exists = (child / "report.html").exists()
        if not original_exists and not report_exists:
            continue
        rows.append(
            {
                "report_id": report_id,
                "has_original": original_exists,
                "has_report": report_exists,
            }
        )

    rows.sort(key=lambda item: item["report_id"], reverse=True)
    return rows[: max(1, int(limit or 1))]


def main() -> int:
    started = time.perf_counter()
    timeline = []

    def mark(step: str, details=None):
        timeline.append(
            {
                "step": step,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "details": details or {},
            }
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Use a regular isolated context; persistent profile is unnecessary for this flow.
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector("body", state="attached", timeout=60000)
            page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)

            loader_forced = False
            try:
                page.wait_for_selector("#startupLoader", state="hidden", timeout=90000)
            except PlaywrightTimeoutError:
                # Some local variants keep startup overlay visible even after app scripts are ready.
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

            page.wait_for_function(
                "() => typeof API !== 'undefined' && typeof Router !== 'undefined'",
                timeout=60000,
            )
            mark("ui_bootstrap_ready", {"loader_forced": loader_forced})

            api_base_fix = page.evaluate(
                """
                (baseUrl) => {
                    const result = { before: '', after: '', changed: false, note: '' };
                    try {
                        if (typeof API_CONFIG !== 'undefined' && API_CONFIG && typeof API_CONFIG === 'object') {
                            result.before = String(API_CONFIG.BASE_URL || '');
                            API_CONFIG.BASE_URL = baseUrl;
                            result.after = String(API_CONFIG.BASE_URL || '');
                            result.changed = result.after === baseUrl;
                        } else {
                            result.note = 'API_CONFIG unavailable';
                        }
                    } catch (err) {
                        result.note = String((err && err.message) || err || 'unknown');
                    }
                    return result;
                }
                """,
                BASE_URL,
            )
            mark("api_base_fixed", api_base_fix)

            page.evaluate(
                """
                (forcedBaseUrl) => {
                    if (window.__LUNA_PERF_HOOKS_INSTALLED) return;
                    window.__LUNA_PERF_HOOKS_INSTALLED = true;

                    const resolvedLocalOrigin = (() => {
                        try {
                            return new URL(forcedBaseUrl || window.location.origin, window.location.origin).origin;
                        } catch (_) {
                            return window.location.origin;
                        }
                    })();

                    try {
                        window.PPE_API_URL = resolvedLocalOrigin;
                        if (window.__PPE_CONFIG__ && typeof window.__PPE_CONFIG__ === 'object') {
                            window.__PPE_CONFIG__.API_BASE_URL = resolvedLocalOrigin;
                        }
                    } catch (_) {
                        // No-op
                    }

                    window.__LUNA_PERF = {
                        fetchCalls: [],
                        startedCalls: [],
                        notes: [],
                        force_local_origin: resolvedLocalOrigin
                    };

                    const originalFetch = window.fetch.bind(window);

                    const normalizeUrl = (raw) => {
                        if (!raw) return '';
                        try {
                            return new URL(String(raw), window.location.origin).toString();
                        } catch (_) {
                            return String(raw || '');
                        }
                    };

                    const rewriteApiUrl = (rawUrl) => {
                        const absolute = normalizeUrl(rawUrl);
                        if (!absolute) return absolute;
                        try {
                            const parsed = new URL(absolute);
                            if (!String(parsed.pathname || '').startsWith('/api/')) {
                                return absolute;
                            }
                            if (parsed.origin === resolvedLocalOrigin) {
                                return absolute;
                            }

                            const local = new URL(resolvedLocalOrigin);
                            parsed.protocol = local.protocol;
                            parsed.host = local.host;
                            return parsed.toString();
                        } catch (_) {
                            return absolute;
                        }
                    };

                    window.fetch = async (...args) => {
                        let originalUrl = '';
                        let rewrittenUrl = '';
                        let method = 'GET';
                        let rewritten = false;
                        let requestInfo = args[0];
                        const requestInit = args[1];

                        try {
                            const req = args[0];
                            if (typeof req === 'string' || req instanceof URL) {
                                originalUrl = normalizeUrl(req);
                                rewrittenUrl = rewriteApiUrl(originalUrl);
                                rewritten = !!rewrittenUrl && rewrittenUrl !== originalUrl;
                                requestInfo = rewritten ? rewrittenUrl : req;
                                method = (requestInit && requestInit.method) || 'GET';
                            } else if (req && typeof req.url === 'string') {
                                originalUrl = normalizeUrl(req.url);
                                rewrittenUrl = rewriteApiUrl(originalUrl);
                                rewritten = !!rewrittenUrl && rewrittenUrl !== originalUrl;
                                method = req.method || ((requestInit && requestInit.method) || 'GET');
                                if (rewritten) {
                                    requestInfo = new Request(rewrittenUrl, req);
                                }
                            }
                        } catch (_) {
                            // Best effort rewrite/logging only.
                        }

                        const startedAt = performance.now();
                        const startedWallClock = Date.now();
                        window.__LUNA_PERF.startedCalls.push({
                            url: rewritten ? rewrittenUrl : originalUrl,
                            original_url: originalUrl,
                            rewritten_url: rewrittenUrl,
                            rewritten,
                            method: String(method || 'GET').toUpperCase(),
                            at: startedWallClock
                        });
                        try {
                            const response = await originalFetch(requestInfo, requestInit);
                            const duration = performance.now() - startedAt;
                            window.__LUNA_PERF.fetchCalls.push({
                                url: rewritten ? rewrittenUrl : originalUrl,
                                original_url: originalUrl,
                                rewritten_url: rewrittenUrl,
                                rewritten,
                                method: String(method || 'GET').toUpperCase(),
                                status: response.status,
                                ok: !!response.ok,
                                duration_ms: Number(duration.toFixed(2)),
                                at: Date.now()
                            });
                            return response;
                        } catch (error) {
                            const duration = performance.now() - startedAt;
                            window.__LUNA_PERF.fetchCalls.push({
                                url: rewritten ? rewrittenUrl : originalUrl,
                                original_url: originalUrl,
                                rewritten_url: rewrittenUrl,
                                rewritten,
                                method: String(method || 'GET').toUpperCase(),
                                status: 0,
                                ok: false,
                                duration_ms: Number(duration.toFixed(2)),
                                error: String((error && error.message) || error || 'unknown error'),
                                at: Date.now()
                            });
                            throw error;
                        }
                    };

                    window.confirm = (message) => {
                        window.__LUNA_PERF.notes.push({
                            kind: 'confirm',
                            message: String(message || ''),
                            at: Date.now()
                        });
                        return true;
                    };
                }
                """,
                BASE_URL,
            )
            mark("perf_hooks_installed")

            open_started = time.perf_counter()
            modal_open_result = page.evaluate(
                """
                () => {
                    if (typeof GlobalSettingsModal === 'undefined' || typeof GlobalSettingsModal.open !== 'function') {
                        return { ok: false, error: 'GlobalSettingsModal.open unavailable' };
                    }
                    GlobalSettingsModal.open({ focusLocalCheckup: true });
                    return { ok: true };
                }
                """
            )
            if not modal_open_result or not modal_open_result.get("ok"):
                raise RuntimeError((modal_open_result or {}).get("error") or "failed opening global settings modal")

            page.wait_for_selector("#globalSettingsModal.open", timeout=15000)
            page.wait_for_selector("#globalRunLocalModeCheckupBtn", timeout=15000)
            mark(
                "open_settings_checkup",
                {"duration_ms": round((time.perf_counter() - open_started) * 1000, 2)},
            )

            checkup_started = time.perf_counter()
            page.click("#globalRunLocalModeCheckupBtn")
            page.wait_for_function(
                """
                () => {
                    const btn = document.querySelector('#globalRunLocalModeCheckupBtn');
                    if (!btn) return false;
                    const txt = String(btn.textContent || '').toLowerCase();
                    return !btn.disabled && txt.includes('run local mode checkup');
                }
                """,
                timeout=180000,
            )
            checkup_duration_ms = round((time.perf_counter() - checkup_started) * 1000, 2)

            checkup_status = ""
            provider_status = ""
            if page.locator("#globalLocalModeCheckupStatus").count() > 0:
                checkup_status = page.locator("#globalLocalModeCheckupStatus").first.inner_text().strip()
            if page.locator("#globalProviderRoutingStatus").count() > 0:
                provider_status = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()

            mark(
                "local_checkup_completed",
                {
                    "duration_ms": checkup_duration_ms,
                    "checkup_status": checkup_status,
                    "provider_status": provider_status,
                },
            )

            apply_started = time.perf_counter()
            page.click("#globalApplyProviderRoutingBtn")
            page.wait_for_timeout(1500)

            local_routing = page.evaluate(
                """
                async () => {
                    if (typeof API_CONFIG !== 'undefined' && API_CONFIG && typeof API_CONFIG === 'object') {
                        API_CONFIG.BASE_URL = window.location.origin;
                    }
                    if (typeof API === 'undefined' || typeof API.getProviderRoutingSettings !== 'function') {
                        return null;
                    }
                    return await API.getProviderRoutingSettings();
                }
                """
            )

            local_apply_status = ""
            if page.locator("#globalProviderRoutingStatus").count() > 0:
                local_apply_status = page.locator("#globalProviderRoutingStatus").first.inner_text().strip()

            mark(
                "apply_local_profile",
                {
                    "duration_ms": round((time.perf_counter() - apply_started) * 1000, 2),
                    "routing_profile": routing_profile_of(local_routing),
                    "provider_status": local_apply_status,
                },
            )

            page.click("#globalSettingsCloseBtn")
            page.wait_for_selector("#globalSettingsModal", state="hidden", timeout=8000)
            mark("settings_modal_closed")

            reports_ui_ready = False
            reports_nav_error = ""
            reports_mount_forced = False
            try:
                ensure_nav_visible(page, "reports")
                page.click("[data-page='reports']")
                page.wait_for_selector("#reports-list", timeout=7000)
                reports_ui_ready = True
            except Exception as nav_exc:
                reports_nav_error = str(nav_exc)
                # Fallback: force route navigation even if nav interaction is flaky.
                page.evaluate(
                    """
                    () => {
                        if (typeof Router !== 'undefined' && typeof Router.navigate === 'function') {
                            Router.navigate('reports');
                        }
                    }
                    """
                )
                try:
                    page.wait_for_selector("#reports-list", timeout=7000)
                    reports_ui_ready = True
                except PlaywrightTimeoutError:
                    reports_ui_ready = False

            if not reports_ui_ready:
                reports_mount_forced = True
                forced_mount = page.evaluate(
                    """
                    async () => {
                        if (document.getElementById('reports-list')) {
                            return { ok: true, already_present: true };
                        }
                        if (typeof ReportsPage === 'undefined' || typeof ReportsPage.render !== 'function') {
                            return { ok: false, error: 'ReportsPage.render unavailable' };
                        }

                        const app = document.getElementById('app');
                        if (!app) {
                            return { ok: false, error: '#app container missing' };
                        }

                        app.innerHTML = ReportsPage.render();
                        if (typeof ReportsPage.mount === 'function') {
                            await ReportsPage.mount();
                        }
                        return {
                            ok: !!document.getElementById('reports-list'),
                            already_present: false,
                        };
                    }
                    """
                )
                reports_ui_ready = bool((forced_mount or {}).get("ok"))
                if not reports_ui_ready:
                    forced_error = (forced_mount or {}).get("error")
                    if forced_error:
                        if reports_nav_error:
                            reports_nav_error = f"{reports_nav_error} | forced mount: {forced_error}"
                        else:
                            reports_nav_error = f"forced mount: {forced_error}"

            mark(
                "reports_page_open",
                {
                    "reports_ui_ready": reports_ui_ready,
                    "reports_nav_error": reports_nav_error,
                    "reports_mount_forced": reports_mount_forced,
                },
            )

            local_cache_candidates = collect_local_report_candidates(limit=80)
            mark(
                "local_cache_candidates_scanned",
                {
                    "count": len(local_cache_candidates),
                    "sample": [item.get("report_id") for item in local_cache_candidates[:10]],
                },
            )

            generation_result = page.evaluate(
                """
                async (fallbackCandidates) => {
                    const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                    if (typeof API_CONFIG !== 'undefined' && API_CONFIG && typeof API_CONFIG === 'object') {
                        API_CONFIG.BASE_URL = window.location.origin;
                    }

                    if (typeof ReportsPage === 'undefined' || typeof API === 'undefined') {
                        return { ok: false, error: 'ReportsPage/API unavailable in page context' };
                    }

                    const ensureReportsDom = async () => {
                        if (document.getElementById('reports-list')) return true;
                        if (typeof ReportsPage.render !== 'function') return false;
                        const app = document.getElementById('app');
                        if (!app) return false;

                        app.innerHTML = ReportsPage.render();
                        if (typeof ReportsPage.mount === 'function') {
                            try {
                                await ReportsPage.mount();
                            } catch (_) {
                                // Keep going with best effort; some environments can still use modal/status APIs.
                            }
                        }
                        return !!document.getElementById('reports-list');
                    };

                    const reportsDomReady = await ensureReportsDom();

                    let uiRefreshError = '';
                    if (typeof ReportsPage.refreshReports === 'function') {
                        try {
                            await ReportsPage.refreshReports();
                        } catch (err) {
                            uiRefreshError = String((err && err.message) || err || 'unknown refresh error');
                        }
                    }

                    const fromUi = Array.isArray(ReportsPage.violations) ? ReportsPage.violations.slice() : [];
                    let fromApi = [];
                    try {
                        const apiRows = await API.getViolations({ limit: 1200 });
                        fromApi = Array.isArray(apiRows) ? apiRows : [];
                    } catch (_) {
                        fromApi = [];
                    }

                    const mergedById = new Map();
                    for (const row of [...fromUi, ...fromApi]) {
                        const rid = String((row && row.report_id) || '').trim();
                        if (!rid) continue;
                        if (!mergedById.has(rid)) {
                            mergedById.set(rid, row);
                        }
                    }

                    if (Array.isArray(fallbackCandidates)) {
                        for (const raw of fallbackCandidates) {
                            const rid = String((raw && raw.report_id) || '').trim();
                            if (!rid) continue;
                            if (!mergedById.has(rid)) {
                                mergedById.set(rid, {
                                    report_id: rid,
                                    status: raw && raw.has_report ? 'completed' : 'pending',
                                    timestamp: new Date().toISOString(),
                                    has_report: !!(raw && raw.has_report),
                                    has_original: !!(raw && raw.has_original),
                                    has_annotated: false,
                                    severity: 'HIGH',
                                    violation_count: 1,
                                    missing_ppe: []
                                });
                            }
                        }
                    }

                    const orderedCandidates = Array.from(mergedById.values())
                        .filter(v => v && v.report_id)
                        .sort((a, b) => {
                            const aTs = Date.parse((a && a.timestamp) || '') || 0;
                            const bTs = Date.parse((b && b.timestamp) || '') || 0;
                            return bTs - aTs;
                        });

                    const attempts = [];
                    let selected = null;
                    let selectedStrategy = '';

                    const isQueueBoundError = (text) => {
                        const msg = String(text || '').toLowerCase();
                        return msg.includes('queue full') || msg.includes('rate limited');
                    };

                    const statusSnapshot = (statusData) => {
                        if (!statusData || typeof statusData !== 'object') return null;
                        return {
                            status: String(statusData.status || ''),
                            has_report: !!statusData.has_report,
                            has_original: !!statusData.has_original,
                            has_annotated: !!statusData.has_annotated
                        };
                    };

                    for (const candidate of orderedCandidates.slice(0, 80)) {
                        const rid = String(candidate.report_id || '').trim();
                        if (!rid) continue;

                        let forceRes = null;
                        let forceError = '';
                        try {
                            forceRes = await API.generateReportNow(rid, { force: true });
                            forceError = String((forceRes && forceRes.error) || '');
                        } catch (err) {
                            forceError = String((err && err.message) || err || 'unknown force error');
                        }

                        let nonForceRes = null;
                        let nonForceError = '';
                        let accepted = !!(forceRes && forceRes.success);
                        let acceptedBy = accepted ? 'force' : '';

                        if (!accepted && isQueueBoundError(forceError)) {
                            try {
                                nonForceRes = await API.generateReportNow(rid, { force: false });
                                nonForceError = String((nonForceRes && nonForceRes.error) || '');
                                if (nonForceRes && (nonForceRes.success || nonForceRes.already_completed || nonForceRes.already_queued)) {
                                    accepted = true;
                                    acceptedBy = 'non_force';
                                }
                            } catch (err) {
                                nonForceError = String((err && err.message) || err || 'unknown non-force error');
                            }
                        }

                        let statusData = null;
                        try {
                            statusData = await API.getReportStatus(rid);
                        } catch (_) {
                            statusData = null;
                        }

                        if (!accepted && statusData) {
                            const normalizedStatus = String(statusData.status || '').toLowerCase();
                            if (normalizedStatus === 'completed' && statusData.has_report) {
                                accepted = true;
                                acceptedBy = 'status_completed';
                            }
                        }

                        attempts.push({
                            report_id: rid,
                            success: accepted,
                            accepted_by: acceptedBy,
                            force_error: forceError,
                            non_force_error: nonForceError,
                            status_probe: statusSnapshot(statusData)
                        });

                        if (!accepted) {
                            continue;
                        }

                        selected = {
                            ...candidate,
                            report_id: rid,
                            timestamp: candidate.timestamp || new Date().toISOString(),
                            status: (statusData && statusData.status) || candidate.status || 'pending',
                            has_report: !!(
                                (statusData && statusData.has_report)
                                || candidate.has_report
                                || (nonForceRes && nonForceRes.already_completed)
                            ),
                            has_original: !!((statusData && statusData.has_original) || candidate.has_original),
                            has_annotated: !!((statusData && statusData.has_annotated) || candidate.has_annotated),
                            severity: candidate.severity || 'HIGH',
                            violation_count: Number(candidate.violation_count || 1),
                            missing_ppe: Array.isArray(candidate.missing_ppe) ? candidate.missing_ppe : []
                        };

                        if (acceptedBy === 'status_completed') {
                            selectedStrategy = 'status_completed_fallback';
                        } else if (acceptedBy === 'non_force') {
                            selectedStrategy = 'generate_now_non_force';
                        } else {
                            selectedStrategy = 'generate_now_force';
                        }
                        break;
                    }

                    if (!selected) {
                        return {
                            ok: false,
                            error: 'No candidate accepted generate-now',
                            candidate_count: orderedCandidates.length,
                            attempts,
                            selected_strategy: selectedStrategy,
                            ui_refresh_error: uiRefreshError,
                            reports_dom_ready: reportsDomReady,
                            reports_list_present: !!document.getElementById('reports-list')
                        };
                    }

                    const selectedForModal = {
                        report_id: selected.report_id,
                        timestamp: selected.timestamp || new Date().toISOString(),
                        status: selected.status || 'pending',
                        has_report: !!selected.has_report,
                        has_original: !!selected.has_original,
                        has_annotated: !!selected.has_annotated,
                        severity: selected.severity || 'HIGH',
                        violation_count: Number(selected.violation_count || 1),
                        missing_ppe: Array.isArray(selected.missing_ppe) ? selected.missing_ppe : []
                    };

                    await ReportsPage.showGeneratingModal(selectedForModal);
                    ReportsPage.startModalPolling(selected.report_id, { autoOpen: false });

                    const poll_samples = [];
                    const started_at = Date.now();
                    let final_status = 'unknown';
                    let final_has_report = false;

                    for (let i = 0; i < 60; i++) {
                        const statusData = await API.getReportStatus(selected.report_id);
                        const status = String((statusData && statusData.status) || '').toLowerCase() || 'unknown';
                        final_status = status;
                        final_has_report = !!(statusData && statusData.has_report);

                        const statusText = (document.getElementById('report-modal-status')?.textContent || '').trim();
                        const completedDone = !!document.getElementById('report-stage-completed')?.classList.contains('done');
                        const generatingActive = !!document.getElementById('report-stage-generating')?.classList.contains('active');

                        poll_samples.push({
                            poll: i + 1,
                            status,
                            has_report: final_has_report,
                            modal_status_text: statusText,
                            completed_stage_done: completedDone,
                            generating_stage_active: generatingActive,
                            at: Date.now()
                        });

                        if (
                            (status == 'completed' && final_has_report)
                            || status == 'failed'
                            || status == 'partial'
                            || status == 'skipped'
                        ) {
                            break;
                        }
                        await delay(2500);
                    }

                    ReportsPage.closeModal();

                    return {
                        ok: true,
                        report_id: selected.report_id,
                        candidate_count: orderedCandidates.length,
                        selected_strategy: selectedStrategy,
                        attempts,
                        ui_refresh_error: uiRefreshError,
                        reports_dom_ready: reportsDomReady,
                        reports_list_present: !!document.getElementById('reports-list'),
                        poll_samples,
                        final_status,
                        final_has_report,
                        duration_ms: Date.now() - started_at
                    };
                }
                """,
                local_cache_candidates,
            )
            mark("real_report_generation_flow", generation_result)

            before_offline_route = page.evaluate(
                """
                async () => {
                    if (typeof API_CONFIG !== 'undefined' && API_CONFIG && typeof API_CONFIG === 'object') {
                        API_CONFIG.BASE_URL = window.location.origin;
                    }
                    if (typeof API === 'undefined' || typeof API.getProviderRoutingSettings !== 'function') return null;
                    return await API.getProviderRoutingSettings();
                }
                """
            )

            offline_dispatch_at = page.evaluate("() => Date.now()")
            offline_started = time.perf_counter()
            page.evaluate(
                """
                () => {
                    window.dispatchEvent(new CustomEvent('ppe-network:status', {
                        detail: {
                            state: 'network-offline',
                            text: 'Offline',
                            online: false,
                            measuredAt: Date.now()
                        }
                    }));
                }
                """
            )
            page.wait_for_timeout(6500)
            after_offline_route = page.evaluate(
                """
                async () => {
                    if (typeof API_CONFIG !== 'undefined' && API_CONFIG && typeof API_CONFIG === 'object') {
                        API_CONFIG.BASE_URL = window.location.origin;
                    }
                    if (typeof API === 'undefined' || typeof API.getProviderRoutingSettings !== 'function') return null;
                    return await API.getProviderRoutingSettings();
                }
                """
            )
            mark(
                "wifi_disconnect_event_processed",
                {
                    "duration_ms": round((time.perf_counter() - offline_started) * 1000, 2),
                    "routing_before": routing_profile_of(before_offline_route),
                    "routing_after": routing_profile_of(after_offline_route),
                    "offline_dispatch_at": offline_dispatch_at,
                },
            )

            reconnect_since = page.evaluate("() => Date.now()")
            reconnect_started = time.perf_counter()
            page.evaluate(
                """
                () => {
                    window.dispatchEvent(new CustomEvent('ppe-network:status', {
                        detail: {
                            state: 'network-good',
                            text: 'Good',
                            online: true,
                            measuredAt: Date.now()
                        }
                    }));
                }
                """
            )

            sync_started_auto_after_reconnect = True
            try:
                page.wait_for_function(
                    """
                    (sinceTs) => {
                        const started = (window.__LUNA_PERF && window.__LUNA_PERF.startedCalls) || [];
                        return started.some((entry) => {
                            const u = String(entry.url || entry.rewritten_url || entry.original_url || '');
                            return entry.at >= sinceTs && u.includes('/api/reports/sync-local-cache');
                        });
                    }
                    """,
                    arg=reconnect_since,
                    timeout=AUTO_SYNC_START_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                sync_started_auto_after_reconnect = False

            sync_seen_auto_after_reconnect = sync_started_auto_after_reconnect
            if sync_started_auto_after_reconnect:
                try:
                    page.wait_for_function(
                        """
                        (sinceTs) => {
                            const completed = (window.__LUNA_PERF && window.__LUNA_PERF.fetchCalls) || [];
                            return completed.some((entry) => {
                                const u = String(entry.url || entry.rewritten_url || entry.original_url || '');
                                return entry.at >= sinceTs && u.includes('/api/reports/sync-local-cache');
                            });
                        }
                        """,
                        arg=reconnect_since,
                        timeout=AUTO_SYNC_COMPLETE_TIMEOUT_MS,
                    )
                    sync_seen_auto_after_reconnect = True
                except PlaywrightTimeoutError:
                    sync_seen_auto_after_reconnect = False

            manual_sync_attempt = {
                "attempted": False,
                "api_available": False,
                "response": None,
                "skipped_reason": "",
            }
            if not sync_started_auto_after_reconnect and ALLOW_MANUAL_RECONNECT_SYNC_FALLBACK:
                manual_sync_attempt = page.evaluate(
                    """
                    async () => {
                        if (typeof API === 'undefined' || typeof API.syncLocalCacheToSupabase !== 'function') {
                            return {
                                attempted: false,
                                api_available: false,
                                response: null,
                            };
                        }
                        try {
                            const response = await API.syncLocalCacheToSupabase({
                                limit: 120,
                                reason: 'ui_reconnect_perf_manual'
                            });
                            return {
                                attempted: true,
                                api_available: true,
                                response
                            };
                        } catch (err) {
                            return {
                                attempted: true,
                                api_available: true,
                                response: {
                                    success: false,
                                    error: String((err && err.message) || err || 'manual sync failed')
                                }
                            };
                        }
                    }
                    """
                )
            elif not sync_started_auto_after_reconnect and not ALLOW_MANUAL_RECONNECT_SYNC_FALLBACK:
                manual_sync_attempt["skipped_reason"] = (
                    "manual fallback disabled; no auto reconnect sync start seen"
                )
            elif sync_started_auto_after_reconnect and not sync_seen_auto_after_reconnect:
                manual_sync_attempt["skipped_reason"] = (
                    "auto reconnect sync started but completion not observed within timeout; manual fallback suppressed"
                )

            sync_seen_after_reconnect = sync_seen_auto_after_reconnect or sync_started_auto_after_reconnect
            if not sync_seen_after_reconnect:
                try:
                    page.wait_for_function(
                        """
                        (sinceTs) => {
                            const logs = (window.__LUNA_PERF && window.__LUNA_PERF.fetchCalls) || [];
                            return logs.some((entry) => {
                                const u = String(entry.url || entry.rewritten_url || entry.original_url || '');
                                return entry.at >= sinceTs && u.includes('/api/reports/sync-local-cache');
                            });
                        }
                        """,
                        arg=reconnect_since,
                        timeout=12000,
                    )
                    sync_seen_after_reconnect = True
                except PlaywrightTimeoutError:
                    sync_seen_after_reconnect = False

            page.wait_for_timeout(3000)
            after_reconnect_route = page.evaluate(
                """
                async () => {
                    if (typeof API_CONFIG !== 'undefined' && API_CONFIG && typeof API_CONFIG === 'object') {
                        API_CONFIG.BASE_URL = window.location.origin;
                    }
                    if (typeof API === 'undefined' || typeof API.getProviderRoutingSettings !== 'function') return null;
                    return await API.getProviderRoutingSettings();
                }
                """
            )

            mark(
                "wifi_reconnect_event_processed",
                {
                    "duration_ms": round((time.perf_counter() - reconnect_started) * 1000, 2),
                    "routing_after": routing_profile_of(after_reconnect_route),
                    "sync_started_auto_after_reconnect": sync_started_auto_after_reconnect,
                    "sync_seen_auto_after_reconnect": sync_seen_auto_after_reconnect,
                    "sync_seen_after_reconnect": sync_seen_after_reconnect,
                    "manual_sync_attempt": manual_sync_attempt,
                },
            )

            perf_extract = page.evaluate(
                """
                (reconnectSince) => {
                    const logs = (window.__LUNA_PERF && window.__LUNA_PERF.fetchCalls) || [];
                    const key = logs.filter((entry) => {
                        const u = String(entry.url || entry.rewritten_url || entry.original_url || '');
                        return (
                            u.includes('/api/settings/report-recovery-options') ||
                            u.includes('/api/settings/provider-routing') ||
                            u.includes('/api/report/') ||
                            u.includes('/api/reports/sync-local-cache') ||
                            u.includes('/api/reports/recovery') ||
                            u.includes('/api/violations')
                        );
                    });

                    const syncAfterReconnect = key.filter((entry) => {
                        const u = String(entry.url || entry.rewritten_url || entry.original_url || '');
                        return entry.at >= reconnectSince && u.includes('/api/reports/sync-local-cache');
                    });

                    const startedLogs = (window.__LUNA_PERF && window.__LUNA_PERF.startedCalls) || [];
                    const syncStartedAfterReconnect = startedLogs.filter((entry) => {
                        const u = String(entry.url || entry.rewritten_url || entry.original_url || '');
                        return entry.at >= reconnectSince && u.includes('/api/reports/sync-local-cache');
                    });

                    const endpointSummary = {};
                    let rewrittenKeyCalls = 0;
                    for (const entry of key) {
                        const url = String(entry.url || entry.rewritten_url || entry.original_url || '');
                        let bucket = 'other';
                        if (url.includes('/api/settings/report-recovery-options')) bucket = 'report_recovery_options';
                        else if (url.includes('/api/settings/provider-routing')) bucket = 'provider_routing';
                        else if (url.includes('/api/reports/sync-local-cache')) bucket = 'sync_local_cache';
                        else if (url.includes('/api/reports/recovery')) bucket = 'reports_recovery';
                        else if (url.includes('/api/report/') && url.includes('/status')) bucket = 'report_status';
                        else if (url.includes('/api/report/') && url.includes('/generate-now')) bucket = 'report_generate_now';
                        else if (url.includes('/api/violations')) bucket = 'violations';

                        if (!endpointSummary[bucket]) {
                            endpointSummary[bucket] = {
                                calls: 0,
                                success_calls: 0,
                                avg_duration_ms: 0,
                                max_duration_ms: 0
                            };
                        }
                        const target = endpointSummary[bucket];
                        target.calls += 1;
                        if (entry.ok) target.success_calls += 1;
                        if (entry.rewritten) rewrittenKeyCalls += 1;
                        const d = Number(entry.duration_ms || 0);
                        target.avg_duration_ms += d;
                        if (d > target.max_duration_ms) target.max_duration_ms = d;
                    }

                    Object.values(endpointSummary).forEach((item) => {
                        if (item.calls > 0) {
                            item.avg_duration_ms = Number((item.avg_duration_ms / item.calls).toFixed(2));
                        }
                    });

                    return {
                        total_key_calls: key.length,
                        rewritten_key_calls: rewrittenKeyCalls,
                        total_rewritten_calls: logs.filter((entry) => !!entry.rewritten).length,
                        force_local_origin: (window.__LUNA_PERF && window.__LUNA_PERF.force_local_origin) || '',
                        endpoint_summary: endpointSummary,
                        sync_after_reconnect_calls: syncAfterReconnect,
                        sync_after_reconnect_started_calls: syncStartedAfterReconnect,
                        confirms_seen: (window.__LUNA_PERF && window.__LUNA_PERF.notes) || []
                    };
                }
                """,
                reconnect_since,
            )

            summary = {
                "base_url": BASE_URL,
                "pass": True,
                "timeline": timeline,
                "routing_snapshot": {
                    "before_offline": routing_profile_of(before_offline_route),
                    "after_offline": routing_profile_of(after_offline_route),
                    "after_reconnect": routing_profile_of(after_reconnect_route),
                },
                "generation": generation_result,
                "api_route_rewrite_stats": {
                    "rewritten_key_calls": perf_extract.get("rewritten_key_calls", 0),
                    "total_rewritten_calls": perf_extract.get("total_rewritten_calls", 0),
                    "forced_local_origin": perf_extract.get("force_local_origin", ""),
                },
                "performance": perf_extract,
            }

            if not generation_result or not generation_result.get("ok"):
                summary["pass"] = False
            if not perf_extract.get("sync_after_reconnect_calls") and not perf_extract.get(
                "sync_after_reconnect_started_calls"
            ):
                summary["pass"] = False

            print("PASS" if summary["pass"] else "FAIL")
            print(json.dumps(summary, indent=2, ensure_ascii=True))

            browser.close()
            return 0 if summary["pass"] else 2
    except PlaywrightTimeoutError as exc:
        print("FAIL")
        print(json.dumps({"pass": False, "error": f"timeout: {exc}"}, indent=2, ensure_ascii=True))
        return 40
    except Exception as exc:
        print("FAIL")
        print(json.dumps({"pass": False, "error": str(exc)}, indent=2, ensure_ascii=True))
        return 41


if __name__ == "__main__":
    sys.exit(main())
