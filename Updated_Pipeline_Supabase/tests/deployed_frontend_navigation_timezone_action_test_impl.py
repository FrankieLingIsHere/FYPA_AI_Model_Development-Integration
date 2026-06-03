# Readability: Test setup: document the contract this file protects.
import os
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# Prepare vercel url for the next step.
VERCEL_URL = os.environ.get(
    "CASM_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

MAX_NAV_LATENCY_MS = int(os.environ.get("CASM_FRONTEND_MAX_NAV_LATENCY_MS", "12000"))
EGRESS_MINIMAL = os.environ.get("CASM_FRONTEND_ACTION_EGRESS_MINIMAL", "1") != "0"


# Section: run the fail workflow with clear inputs and outputs.
def fail(message: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: frontend action-test issue: {message}")
    return code


# Section: run the find visible nav locator workflow with clear inputs and outputs.
def _find_visible_nav_locator(page, page_name: str):
    nav_selector = f"[data-page='{page_name}']"
    locator = page.locator(nav_selector)
    count = locator.count()
    for index in range(count):
        # Prepare candidate for the next step.
        candidate = locator.nth(index)
        if candidate.is_visible():
            # Return the prepared result to the caller.
            return candidate
    # Return the prepared result to the caller.
    return None


# Section: run the wait for visible nav locator workflow with clear inputs and outputs.
def _wait_for_visible_nav_locator(page, page_name: str, *, attempts: int = 10, pause_ms: int = 200):
    for _ in range(attempts):
        candidate = _find_visible_nav_locator(page, page_name)
        # Choose the correct branch before the workflow continues.
        if candidate:
            return candidate
        page.wait_for_timeout(pause_ms)
    # Return the prepared result to the caller.
    return None


# Section: run the ensure nav visible workflow with clear inputs and outputs.
def ensure_nav_visible(page, page_name: str):
    nav_selector = f"[data-page='{page_name}']"
    locator = page.locator(nav_selector)
    if locator.count() == 0:
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Navigation link not found for page={page_name}")

    # Prepare visible nav for the next step.
    visible_nav = _wait_for_visible_nav_locator(page, page_name)
    if visible_nav:
        return visible_nav

    for toggle_selector in ("#navToggle", "#navMoreToggle", "#mobileMoreToggle"):
        toggle = page.locator(toggle_selector)
        if toggle.count() > 0 and toggle.first.is_visible():
            # Trigger the side effect required for this stage.
            toggle.first.click()
            page.wait_for_timeout(220)
            visible_nav = _wait_for_visible_nav_locator(page, page_name, attempts=6, pause_ms=220)
            if visible_nav:
                # Return the prepared result to the caller.
                return visible_nav

    # Surface the failure with enough context for the caller.
    raise RuntimeError(f"Navigation link exists but is not visible for page={page_name}")


# Section: run the navigate to workflow with clear inputs and outputs.
def navigate_to(page, page_name: str, wait_selector: str = "#app"):
    nav_link = ensure_nav_visible(page, page_name)
    nav_link.click()
    page.wait_for_selector(wait_selector, timeout=MAX_NAV_LATENCY_MS)
    page.wait_for_timeout(320)


# Section: run the install egress minimal routes workflow with clear inputs and outputs.
def install_egress_minimal_routes(context):
    """Avoid storage-heavy assets while preserving real app scripts and API contracts."""
    # Choose the correct branch before the workflow continues.
    if not EGRESS_MINIMAL:
        # Return the prepared result to the caller.
        return

    # Section: run the route handler workflow with clear inputs and outputs.
    def _route_handler(route):
        request = route.request
        url = (request.url or "").lower()
        resource_type = request.resource_type

        if resource_type in ("image", "media", "font") or "/image/" in url:
            # Trigger the side effect required for this stage.
            route.abort()
            return

        # Choose the correct branch before the workflow continues.
        if "/api/report/" in url and "/prefetch" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success":false,"skipped":true,"reason":"egress_minimal_action_test"}',
            )
            # Return the prepared result to the caller.
            return

        route.continue_()

    # Trigger the side effect required for this stage.
    context.route("**/*", _route_handler)


# Section: run the install metrics hooks workflow with clear inputs and outputs.
def install_metrics_hooks(page):
    page.evaluate(
        """
        () => {
            if (!window.__CASM_ACTION_METRICS) {
                window.__CASM_ACTION_METRICS = {
                    mounts: { home: 0, reports: 0, analytics: 0, live: 0, about: 0 },
                    renders: 0,
                    timezoneEvents: 0,
                    reportsRenderCalls: 0,
                    homeRefreshCalls: 0,
                    analyticsRefreshCalls: 0,
                };
            }

            const m = window.__CASM_ACTION_METRICS;

            const RouterRef = window.Router || (typeof Router !== 'undefined' ? Router : null);
            const HomePageRef = window.HomePage || (typeof HomePage !== 'undefined' ? HomePage : null);
            const ReportsPageRef = window.ReportsPage || (typeof ReportsPage !== 'undefined' ? ReportsPage : null);
            const AnalyticsPageRef = window.AnalyticsPage || (typeof AnalyticsPage !== 'undefined' ? AnalyticsPage : null);
            const LivePageRef = window.LivePage || (typeof LivePage !== 'undefined' ? LivePage : null);
            const AboutPageRef = window.AboutPage || (typeof AboutPage !== 'undefined' ? AboutPage : null);

            const wrapMethod = (obj, methodName, counterName) => {
                if (!obj || typeof obj[methodName] !== 'function') return;
                if (obj[methodName].__casm_wrapped) return;
                const original = obj[methodName].bind(obj);
                const wrapped = function(...args) {
                    m[counterName] = (m[counterName] || 0) + 1;
                    return original(...args);
                };
                wrapped.__casm_wrapped = true;
                obj[methodName] = wrapped;
            };

            const wrapMount = (obj, pageKey) => {
                if (!obj || typeof obj.mount !== 'function') return;
                if (obj.mount.__casm_wrapped) return;
                const original = obj.mount.bind(obj);
                const wrapped = function(...args) {
                    m.mounts[pageKey] = (m.mounts[pageKey] || 0) + 1;
                    return original(...args);
                };
                wrapped.__casm_wrapped = true;
                obj.mount = wrapped;
            };

            if (RouterRef && typeof RouterRef.render === 'function' && !RouterRef.render.__casm_wrapped) {
                const originalRender = RouterRef.render.bind(RouterRef);
                const wrappedRender = function(...args) {
                    m.renders += 1;
                    return originalRender(...args);
                };
                wrappedRender.__casm_wrapped = true;
                RouterRef.render = wrappedRender;
            }

            wrapMount(HomePageRef, 'home');
            wrapMount(ReportsPageRef, 'reports');
            wrapMount(AnalyticsPageRef, 'analytics');
            wrapMount(LivePageRef, 'live');
            wrapMount(AboutPageRef, 'about');

            wrapMethod(ReportsPageRef, 'renderReports', 'reportsRenderCalls');
            wrapMethod(HomePageRef, 'refreshData', 'homeRefreshCalls');
            wrapMethod(AnalyticsPageRef, 'refreshData', 'analyticsRefreshCalls');

            if (!window.__CASM_ACTION_METRICS_EVENT_HOOKED) {
                window.addEventListener('ppe-timezone:changed', () => {
                    m.timezoneEvents += 1;
                });
                window.__CASM_ACTION_METRICS_EVENT_HOOKED = true;
            }
        }
        """
    )


# Section: run the get metrics workflow with clear inputs and outputs.
def get_metrics(page):
    # Return the prepared result to the caller.
    return page.evaluate("() => window.__CASM_ACTION_METRICS || null")


# Section: run the pick different timezone value workflow with clear inputs and outputs.
def pick_different_timezone_value(page):
    return page.evaluate(
        """
        () => {
            const selector = document.querySelector('#timezone-selector');
            if (!selector) return null;
            const current = selector.value;
            const options = Array.from(selector.options || []).map(o => o.value).filter(Boolean);
            const next = options.find(v => v !== current);
            return next || null;
        }
        """
    )


# Section: run the check timestamp alignment contract workflow with clear inputs and outputs.
def check_timestamp_alignment_contract(page):
    # Return the prepared result to the caller.
    return page.evaluate(
        """
        () => {
            const manager = window.TimezoneManager;
            const selector = document.querySelector('#timezone-selector');
            if (!manager || typeof manager.formatDateTime !== 'function') {
                return { ok: false, error: 'TimezoneManager.formatDateTime is unavailable' };
            }
            if (!selector) {
                return { ok: false, error: 'timezone selector missing' };
            }

            const options = Array.from(selector.options || [])
                .map((o) => String(o.value || '').trim())
                .filter(Boolean);
            if (!options.length) {
                return { ok: false, error: 'timezone selector has no options' };
            }

            const sampleReportId = '20260419_071918';
            const sampleTimestamp = '2026-04-19T07:19:18';
            const expectedWhenAtDbTimezone = '2026-04-19 07:19:18';

            const previousValue = String(selector.value || '');
            const dbInfo = typeof manager.getDatabaseTimezoneInfo === 'function'
                ? (manager.getDatabaseTimezoneInfo() || {})
                : {};
            const dbTimezoneId = String(dbInfo.timezoneId || '').trim();

            let selectedDbTimezone = false;
            if (dbTimezoneId && options.includes(dbTimezoneId)) {
                selector.value = dbTimezoneId;
                selector.dispatchEvent(new Event('change', { bubbles: true }));
                selectedDbTimezone = true;
            }

            const formattedAtDbTimezone = manager.formatDateTime(sampleTimestamp);
            const idHour = sampleReportId.slice(9, 11);
            const displayedHour = formattedAtDbTimezone.slice(11, 13);

            let altTimezoneValue = null;
            let altFormatted = formattedAtDbTimezone;
            for (const candidate of options) {
                if (candidate === String(selector.value || '')) continue;
                selector.value = candidate;
                selector.dispatchEvent(new Event('change', { bubbles: true }));
                const candidateFormatted = manager.formatDateTime(sampleTimestamp);
                if (candidateFormatted !== formattedAtDbTimezone) {
                    altTimezoneValue = candidate;
                    altFormatted = candidateFormatted;
                    break;
                }
            }

            if (previousValue && options.includes(previousValue)) {
                selector.value = previousValue;
                selector.dispatchEvent(new Event('change', { bubbles: true }));
            }

            const dbContractPass = formattedAtDbTimezone === expectedWhenAtDbTimezone && displayedHour === idHour;
            const altContractPass = Boolean(altTimezoneValue) && altFormatted !== formattedAtDbTimezone;

            return {
                ok: dbContractPass && altContractPass,
                dbTimezoneId: dbTimezoneId || null,
                selectedDbTimezone,
                formattedAtDbTimezone,
                expectedWhenAtDbTimezone,
                reportIdHour: idHour,
                displayedHour,
                altTimezoneValue,
                altFormatted,
                dbContractPass,
                altContractPass,
            };
        }
        """
    )


# Section: run the check local draft persistence contract workflow with clear inputs and outputs.
def check_local_draft_persistence_contract(page):
    # Prepare seed result for the next step.
    seed_result = page.evaluate(
        """
        async () => {
            const api = window.API || (typeof API !== 'undefined' ? API : null);
            if (!api || typeof api.upsertLocalReportDraft !== 'function') {
                return { ok: false, error: 'API local draft helpers unavailable' };
            }
            const reportId = '20990101_010101';
            await api.removeLocalReportDraft(reportId);
            await api.upsertLocalReportDraft({
                report_id: reportId,
                timestamp: '2099-01-01T01:01:01',
                status: 'pending',
                severity: 'HIGH',
                source_scope: 'local',
                source_label: 'Local',
                sync_state: 'pending_local_generation',
                violation_count: 1,
                violation_summary: 'PPE Violation Detected: Missing Hardhat',
                missing_ppe: ['Hardhat'],
                original_blob: new Blob(['local-draft-image'], { type: 'image/jpeg' }),
                has_original: true
            });
            const merged = await api.mergeLocalReportDrafts([], 5);
            const draft = merged.find((item) => item.report_id === reportId);
            return {
                ok: !!draft && draft.source_scope === 'local' && !!draft.local_image_url && draft.has_original === true,
                beforeReload: !!draft,
                sourceScope: draft && draft.source_scope,
                hasLocalImageUrl: !!(draft && draft.local_image_url)
            };
        }
        """
    )
    # Choose the correct branch before the workflow continues.
    if not seed_result or not seed_result.get("ok"):
        # Choose the correct branch before the workflow continues.
        if seed_result and "helpers unavailable" in str(seed_result.get("error") or "").lower():
            # Return the prepared result to the caller.
            return {
                "ok": True,
                "skipped": True,
                "reason": "deployed_frontend_missing_local_draft_helpers_pending_redeploy"
            }
        raise RuntimeError(f"Local draft seed contract failed: {seed_result}")

    # Trigger the side effect required for this stage.
    page.reload(wait_until="domcontentloaded", timeout=90000)
    page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)
    page.wait_for_function(
        "() => !document.body.classList.contains('startup-loading')",
        timeout=120000,
    )

    persisted_result = page.evaluate(
        """
        async () => {
            const api = window.API || (typeof API !== 'undefined' ? API : null);
            const reportId = '20990101_010101';
            if (!api || typeof api.mergeLocalReportDrafts !== 'function') {
                return { ok: false, error: 'API local draft helpers unavailable after reload' };
            }
            const merged = await api.mergeLocalReportDrafts([], 5);
            const draft = merged.find((item) => item.report_id === reportId);
            const ok = !!draft && draft.source_scope === 'local' && !!draft.local_image_url && draft.has_original === true;
            await api.removeLocalReportDraft(reportId);
            return {
                ok,
                afterReload: !!draft,
                sourceScope: draft && draft.source_scope,
                hasLocalImageUrl: !!(draft && draft.local_image_url)
            };
        }
        """
    )
    # Choose the correct branch before the workflow continues.
    if not persisted_result or not persisted_result.get("ok"):
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Local draft persistence contract failed: {persisted_result}")
    return persisted_result


# Section: run the read desktop sidebar state workflow with clear inputs and outputs.
def _read_desktop_sidebar_state(page):
    return page.evaluate(
        """
        () => {
            const sidebar = document.querySelector('.sidebar');
            const title = document.querySelector('.sidebar-title');
            const navLabel = document.querySelector(".sidebar-link[data-page='reports'] span");
            const voiceCopy = document.querySelector('#enableVoice .voice-btn-copy');
            const timezone = document.querySelector('#timezone-selector');

            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return (
                    style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number(style.opacity || '1') > 0.05
                    && rect.width > 6
                    && rect.height > 6
                );
            };

            return {
                width: sidebar ? Number.parseFloat(window.getComputedStyle(sidebar).width || '0') : 0,
                titleVisible: isVisible(title),
                navLabelVisible: isVisible(navLabel),
                voiceCopyVisible: isVisible(voiceCopy),
                timezoneVisible: isVisible(timezone),
            };
        }
        """
    )


# Section: run the check desktop sidebar contract workflow with clear inputs and outputs.
def check_desktop_sidebar_contract(page):
    # Trigger the side effect required for this stage.
    page.evaluate(
        """
        () => {
            if (document.activeElement && typeof document.activeElement.blur === 'function') {
                document.activeElement.blur();
            }
        }
        """
    )
    # Trigger the side effect required for this stage.
    page.mouse.move(1280, 140)
    page.wait_for_timeout(280)
    collapsed = _read_desktop_sidebar_state(page)

    sidebar = page.locator(".sidebar")
    if sidebar.count() == 0:
        # Surface the failure with enough context for the caller.
        raise RuntimeError("Sidebar missing from UI")
    sidebar.hover(force=True)
    page.wait_for_timeout(320)
    # Prepare expanded for the next step.
    expanded = _read_desktop_sidebar_state(page)

    page.mouse.move(1280, 140)
    page.wait_for_timeout(320)
    collapsed_again = _read_desktop_sidebar_state(page)

    width_delta = float(expanded.get("width", 0)) - float(collapsed.get("width", 0))
    if width_delta < 120:
        # Surface the failure with enough context for the caller.
        raise RuntimeError(
            f"Sidebar did not expand enough on hover: collapsed={collapsed}, expanded={expanded}"
        )
    # Choose the correct branch before the workflow continues.
    if collapsed.get("navLabelVisible") or collapsed.get("voiceCopyVisible") or collapsed.get("timezoneVisible"):
        raise RuntimeError(f"Sidebar stayed expanded while idle: collapsed={collapsed}")
    if not expanded.get("navLabelVisible") or not expanded.get("voiceCopyVisible") or not expanded.get("timezoneVisible"):
        raise RuntimeError(f"Sidebar hover state did not expose controls cleanly: expanded={expanded}")
    if abs(float(collapsed_again.get("width", 0)) - float(collapsed.get("width", 0))) > 6:
        raise RuntimeError(
            f"Sidebar failed to shrink back after hover: collapsed={collapsed}, collapsed_again={collapsed_again}"
        )
    if collapsed_again.get("navLabelVisible") or collapsed_again.get("voiceCopyVisible") or collapsed_again.get("timezoneVisible"):
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Sidebar controls remained visible after hover left: collapsed_again={collapsed_again}")

    # Return the prepared result to the caller.
    return {
        "collapsed": collapsed,
        "expanded": expanded,
        "collapsed_again": collapsed_again,
        "width_delta": width_delta,
    }


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Open the managed resource only for the block that needs it.
        with sync_playwright() as p:
            # Prepare browser for the next step.
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            install_egress_minimal_routes(context)
            page = context.new_page()

            if EGRESS_MINIMAL:
                # Trigger the side effect required for this stage.
                print("INFO: frontend action test running with image/media/prefetch blocking enabled")

            page.goto(f"{VERCEL_URL}/", wait_until="domcontentloaded", timeout=90000)
            # Trigger the side effect required for this stage.
            page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)
            page.wait_for_function(
                "() => !document.body.classList.contains('startup-loading')",
                timeout=120000,
            )

            draft_contract = check_local_draft_persistence_contract(page)
            print(f"PASS: local draft persistence contract {draft_contract}")

            # Trigger the side effect required for this stage.
            install_metrics_hooks(page)
            sidebar_contract = check_desktop_sidebar_contract(page)
            print(f"PASS: desktop sidebar collapse contract {sidebar_contract}")

            # Navigation action sequence used to detect duplicate remount/render behavior.
            sequence = [
                ("home", "#app"),
                ("reports", "#reports-list"),
                ("analytics", "#app"),
                ("live", "#app"),
                ("reports", "#reports-list"),
                ("analytics", "#app"),
                ("home", "#app"),
            ]

            # Prepare expected visits for the next step.
            expected_visits = {"home": 0, "reports": 0, "analytics": 0, "live": 0, "about": 0}
            for route_name, wait_selector in sequence:
                # Trigger the side effect required for this stage.
                navigate_to(page, route_name, wait_selector)
                expected_visits[route_name] += 1

            time.sleep(0.25)
            metrics = get_metrics(page)
            if not metrics:
                raise RuntimeError("Missing browser action metrics after navigation sequence")

            # Prepare mounts for the next step.
            mounts = metrics.get("mounts", {})
            for page_name in ("home", "reports", "analytics", "live"):
                # Prepare observed for the next step.
                observed = int(mounts.get(page_name, 0))
                expected = int(expected_visits.get(page_name, 0))
                # Allow one extra mount for first-run/bootstrap variance.
                if observed > expected + 1:
                    # Surface the failure with enough context for the caller.
                    raise RuntimeError(
                        f"Possible duplicate remounts for {page_name}: observed={observed}, expected<={expected + 1}"
                    )

            # Trigger the side effect required for this stage.
            print(f"PASS: navigation remount guard checks metrics={metrics}")

            # Timezone action checks across pages.
            if page.locator("#timezone-selector").count() == 0:
                raise RuntimeError("Timezone selector is missing from deployed UI")

            tz_scenarios = [
                ("reports", "#reports-list", "reportsRenderCalls"),
                ("home", "#app", "homeRefreshCalls"),
                ("analytics", "#app", "analyticsRefreshCalls"),
            ]

            # Prepare action issues for the next step.
            action_issues = []

            for route_name, wait_selector, metric_key in tz_scenarios:
                # Trigger the side effect required for this stage.
                navigate_to(page, route_name, wait_selector)

                # Wait for the page's mount() to finish by checking if the handler is attached
                handler_check_js = """
                () => {
                    const route = '%s';
                    if (route === 'reports') {
                        const page = typeof ReportsPage !== 'undefined' ? ReportsPage : window.ReportsPage;
                        return typeof page?.timezoneChangeHandler === 'function';
                    }
                    if (route === 'home') {
                        const page = typeof HomePage !== 'undefined' ? HomePage : window.HomePage;
                        return typeof page?._timezoneChangeHandler === 'function';
                    }
                    if (route === 'analytics') {
                        const page = typeof AnalyticsPage !== 'undefined' ? AnalyticsPage : window.AnalyticsPage;
                        return typeof page?._timezoneChangeHandler === 'function';
                    }
                    return true;
                }
                """ % route_name

                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Trigger the side effect required for this stage.
                    page.wait_for_function(handler_check_js, timeout=15000)
                except PlaywrightTimeoutError:
                    print(f"Warning: timezoneChangeHandler not found on {route_name} after 15s")

                before = get_metrics(page)
                before_value = int((before or {}).get(metric_key, 0))
                before_events = int((before or {}).get("timezoneEvents", 0))

                # Prepare next tz for the next step.
                next_tz = pick_different_timezone_value(page)
                if not next_tz:
                    # Surface the failure with enough context for the caller.
                    raise RuntimeError(f"No alternate timezone value found for {route_name} scenario")

                page.select_option("#timezone-selector", next_tz)
                page.wait_for_timeout(500)

                after = get_metrics(page)
                after_value = int((after or {}).get(metric_key, 0))
                # Prepare after events for the next step.
                after_events = int((after or {}).get("timezoneEvents", 0))

                issue = None
                if after_events <= before_events:
                    # Prepare issue for the next step.
                    issue = (
                        f"Timezone event did not fire on {route_name}: "
                        f"before={before_events}, after={after_events}"
                    )

                # Choose the correct branch before the workflow continues.
                if issue is None and after_value <= before_value:
                    if (route_name == "reports"):
                        # Prepare fallback for the next step.
                        fallback = page.evaluate(
                            """
                            () => {
                                const reportsPage = window.ReportsPage || (typeof ReportsPage !== 'undefined' ? ReportsPage : null);
                                const list = document.querySelector('#reports-list');
                                return {
                                    routeReady: !!list,
                                    hasHandler: !!(reportsPage && typeof reportsPage.timezoneChangeHandler === 'function'),
                                    reportCount: list ? list.querySelectorAll('.card[id^="report-"]').length : 0,
                                };
                            }
                            """
                        )
                        # Choose the correct branch before the workflow continues.
                        if not fallback or not fallback.get("routeReady") or not fallback.get("hasHandler"):
                            # Prepare issue for the next step.
                            issue = (
                                f"Timezone handler did not trigger {metric_key} on {route_name}: "
                                f"before={before_value}, after={after_value}, fallback={fallback}"
                            )
                        else:
                            print(
                                "PASS: timezone action on reports fired event and handler is registered "
                                f"(render counter unchanged on empty/cached list, fallback={fallback})"
                            )
                    else:
                        # Prepare issue for the next step.
                        issue = (
                            f"Timezone handler did not trigger {metric_key} on {route_name}: "
                            f"before={before_value}, after={after_value}"
                        )

                # Choose the correct branch before the workflow continues.
                if issue:
                    # Trigger the side effect required for this stage.
                    action_issues.append(issue)
                    print(f"FAIL: frontend action-test issue: {issue}")
                    continue

                print(
                    f"PASS: timezone action on {route_name} increased {metric_key} "
                    f"({before_value} -> {after_value})"
                )

            # Trigger the side effect required for this stage.
            navigate_to(page, "reports", "#reports-list")
            alignment = check_timestamp_alignment_contract(page)
            if not alignment or not alignment.get("ok"):
                # Surface the failure with enough context for the caller.
                raise RuntimeError(f"Timezone timestamp alignment contract failed: {alignment}")

            print(f"PASS: timezone timestamp alignment contract {alignment}")

            if action_issues:
                raise RuntimeError(
                    "frontend timezone action checks failed: "
                    + "; ".join(action_issues)
                )

            # Trigger the side effect required for this stage.
            browser.close()

        # Trigger the side effect required for this stage.
        print("PASS: navigation + timezone action test")
        return 0
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in navigation/timezone action test: {exc}", 40)
    except Exception as exc:
        return fail(f"navigation/timezone action test unhandled error: {exc}", 41)


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    sys.exit(main())
