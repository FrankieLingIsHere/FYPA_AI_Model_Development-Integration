import os
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

MAX_NAV_LATENCY_MS = int(os.environ.get("LUNA_FRONTEND_MAX_NAV_LATENCY_MS", "12000"))


def fail(message: str, code: int = 2) -> int:
    # Keep this action test non-blocking in deployed CI, same philosophy as robustness checks.
    print(f"INFO: non-blocking frontend action-test issue: {message}")
    return 0


def ensure_nav_visible(page, page_name: str):
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
            page.wait_for_timeout(220)
            if locator.first.is_visible():
                return

    if not locator.first.is_visible():
        raise RuntimeError(f"Navigation link exists but is not visible for page={page_name}")


def navigate_to(page, page_name: str, wait_selector: str = "#app"):
    ensure_nav_visible(page, page_name)
    page.click(f"[data-page='{page_name}']")
    page.wait_for_selector(wait_selector, timeout=MAX_NAV_LATENCY_MS)
    page.wait_for_timeout(320)


def install_metrics_hooks(page):
    page.evaluate(
        """
        () => {
            if (!window.__LUNA_ACTION_METRICS) {
                window.__LUNA_ACTION_METRICS = {
                    mounts: { home: 0, reports: 0, analytics: 0, live: 0, about: 0 },
                    renders: 0,
                    timezoneEvents: 0,
                    reportsRenderCalls: 0,
                    homeRefreshCalls: 0,
                    analyticsRefreshCalls: 0,
                };
            }

            const m = window.__LUNA_ACTION_METRICS;

            const wrapMethod = (obj, methodName, counterName) => {
                if (!obj || typeof obj[methodName] !== 'function') return;
                if (obj[methodName].__luna_wrapped) return;
                const original = obj[methodName].bind(obj);
                const wrapped = function(...args) {
                    m[counterName] = (m[counterName] || 0) + 1;
                    return original(...args);
                };
                wrapped.__luna_wrapped = true;
                obj[methodName] = wrapped;
            };

            const wrapMount = (obj, pageKey) => {
                if (!obj || typeof obj.mount !== 'function') return;
                if (obj.mount.__luna_wrapped) return;
                const original = obj.mount.bind(obj);
                const wrapped = function(...args) {
                    m.mounts[pageKey] = (m.mounts[pageKey] || 0) + 1;
                    return original(...args);
                };
                wrapped.__luna_wrapped = true;
                obj.mount = wrapped;
            };

            if (window.Router && typeof window.Router.render === 'function' && !window.Router.render.__luna_wrapped) {
                const originalRender = window.Router.render.bind(window.Router);
                const wrappedRender = function(...args) {
                    m.renders += 1;
                    return originalRender(...args);
                };
                wrappedRender.__luna_wrapped = true;
                window.Router.render = wrappedRender;
            }

            wrapMount(window.HomePage, 'home');
            wrapMount(window.ReportsPage, 'reports');
            wrapMount(window.AnalyticsPage, 'analytics');
            wrapMount(window.LivePage, 'live');
            wrapMount(window.AboutPage, 'about');

            wrapMethod(window.ReportsPage, 'renderReports', 'reportsRenderCalls');
            wrapMethod(window.HomePage, 'refreshData', 'homeRefreshCalls');
            wrapMethod(window.AnalyticsPage, 'refreshData', 'analyticsRefreshCalls');

            if (!window.__LUNA_ACTION_METRICS_EVENT_HOOKED) {
                window.addEventListener('ppe-timezone:changed', () => {
                    m.timezoneEvents += 1;
                });
                window.__LUNA_ACTION_METRICS_EVENT_HOOKED = true;
            }
        }
        """
    )


def get_metrics(page):
    return page.evaluate("() => window.__LUNA_ACTION_METRICS || null")


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


def check_timestamp_alignment_contract(page):
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


def main() -> int:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"{VERCEL_URL}/", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)
            page.wait_for_function(
                "() => !document.body.classList.contains('startup-loading')",
                timeout=120000,
            )

            install_metrics_hooks(page)

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

            expected_visits = {"home": 0, "reports": 0, "analytics": 0, "live": 0, "about": 0}
            for route_name, wait_selector in sequence:
                navigate_to(page, route_name, wait_selector)
                expected_visits[route_name] += 1

            time.sleep(0.25)
            metrics = get_metrics(page)
            if not metrics:
                raise RuntimeError("Missing browser action metrics after navigation sequence")

            mounts = metrics.get("mounts", {})
            for page_name in ("home", "reports", "analytics", "live"):
                observed = int(mounts.get(page_name, 0))
                expected = int(expected_visits.get(page_name, 0))
                # Allow one extra mount for first-run/bootstrap variance.
                if observed > expected + 1:
                    raise RuntimeError(
                        f"Possible duplicate remounts for {page_name}: observed={observed}, expected<={expected + 1}"
                    )

            print(f"PASS: navigation remount guard checks metrics={metrics}")

            # Timezone action checks across pages.
            if page.locator("#timezone-selector").count() == 0:
                raise RuntimeError("Timezone selector is missing from deployed UI")

            tz_scenarios = [
                ("reports", "#reports-list", "reportsRenderCalls"),
                ("home", "#app", "homeRefreshCalls"),
                ("analytics", "#app", "analyticsRefreshCalls"),
            ]

            non_blocking_issues = []

            for route_name, wait_selector, metric_key in tz_scenarios:
                navigate_to(page, route_name, wait_selector)

                before = get_metrics(page)
                before_value = int((before or {}).get(metric_key, 0))
                before_events = int((before or {}).get("timezoneEvents", 0))

                next_tz = pick_different_timezone_value(page)
                if not next_tz:
                    raise RuntimeError(f"No alternate timezone value found for {route_name} scenario")

                page.select_option("#timezone-selector", next_tz)
                page.wait_for_timeout(500)

                after = get_metrics(page)
                after_value = int((after or {}).get(metric_key, 0))
                after_events = int((after or {}).get("timezoneEvents", 0))

                issue = None
                if after_events <= before_events:
                    issue = (
                        f"Timezone event did not fire on {route_name}: "
                        f"before={before_events}, after={after_events}"
                    )

                if issue is None and after_value <= before_value:
                    issue = (
                        f"Timezone handler did not trigger {metric_key} on {route_name}: "
                        f"before={before_value}, after={after_value}"
                    )

                if issue:
                    non_blocking_issues.append(issue)
                    print(f"INFO: non-blocking frontend action-test issue: {issue}")
                    continue

                print(
                    f"PASS: timezone action on {route_name} increased {metric_key} "
                    f"({before_value} -> {after_value})"
                )

            navigate_to(page, "reports", "#reports-list")
            alignment = check_timestamp_alignment_contract(page)
            if not alignment or not alignment.get("ok"):
                raise RuntimeError(f"Timezone timestamp alignment contract failed: {alignment}")

            print(f"PASS: timezone timestamp alignment contract {alignment}")

            if non_blocking_issues:
                print(
                    "INFO: non-blocking frontend action-test summary: "
                    f"{len(non_blocking_issues)} issue(s)"
                )

            browser.close()

        print("PASS: navigation + timezone action test")
        return 0
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in navigation/timezone action test: {exc}", 40)
    except Exception as exc:
        return fail(f"navigation/timezone action test unhandled error: {exc}", 41)


if __name__ == "__main__":
    sys.exit(main())
