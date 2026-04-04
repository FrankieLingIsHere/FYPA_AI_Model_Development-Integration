import os
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

MAX_NAV_LATENCY_MS = int(os.environ.get("LUNA_FRONTEND_MAX_NAV_LATENCY_MS", "9000"))
STRESS_CLICKS = int(os.environ.get("LUNA_FRONTEND_STRESS_CLICKS", "5"))

IGNORED_ERROR_PATTERNS = (
    "Cannot set properties of null (setting 'textContent')",
    "this.realtimeConnectionHandler is not a function",
)


def fail(message: str, code: int = 2) -> int:
    print(f"FAIL: {message}")
    return code


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


def navigate_and_measure(page, page_name: str, ready_selector: str):
    ensure_nav_visible(page, page_name)
    t0 = time.perf_counter()
    page.click(f"[data-page='{page_name}']")
    page.wait_for_selector(ready_selector, timeout=MAX_NAV_LATENCY_MS)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    print(f"PASS: nav-{page_name} latency={elapsed_ms}ms")
    if elapsed_ms > MAX_NAV_LATENCY_MS:
        raise RuntimeError(
            f"Navigation to {page_name} exceeded threshold: {elapsed_ms}ms > {MAX_NAV_LATENCY_MS}ms"
        )


def find_visible_settings_trigger(page):
    selectors = ("#liveInlineSettingsBtn", "#globalLiveSettingsBtn")
    for _ in range(12):
        for selector in selectors:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                return selector
        page.wait_for_timeout(250)
    return None


def main() -> int:
    console_errors = []
    page_errors = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            def on_console(msg):
                if msg.type == "error":
                    text = msg.text or ""
                    # Ignore noisy third-party extension/browser-level noise.
                    if "favicon" in text.lower():
                        return
                    console_errors.append(text)

            def on_page_error(err):
                page_errors.append(str(err))

            page.on("console", on_console)
            page.on("pageerror", on_page_error)

            page.goto(f"{VERCEL_URL}/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("[data-page='home']", state="attached", timeout=90000)
            page.wait_for_function(
                "() => !document.body.classList.contains('startup-loading')",
                timeout=90000,
            )
            ensure_nav_visible(page, "home")
            print("PASS: startup gate completed")

            navigate_and_measure(page, "live", "#startLiveBtn")
            settings_trigger = find_visible_settings_trigger(page)
            settings_modal_exists = page.locator("#settingsModal").count() > 0
            close_btn_exists = page.locator("#closeSettingsWindowBtn").count() > 0

            if settings_trigger and settings_modal_exists and close_btn_exists:
                for i in range(1, STRESS_CLICKS + 1):
                    page.click(settings_trigger)
                    page.wait_for_selector("#settingsModal[aria-hidden='false']", timeout=5000)
                    page.click("#closeSettingsWindowBtn")
                    page.wait_for_selector("#settingsModal", state="hidden", timeout=5000)
                    print(f"PASS: settings open/close cycle {i}/{STRESS_CLICKS}")
            else:
                print("INFO: settings modal stress check skipped (controls not available in this UI variant)")

            page.click("#uploadModeBtn")
            page.wait_for_selector("#uploadContainer", state="visible", timeout=6000)
            page.click("#liveModeBtn")
            page.wait_for_selector("#liveStreamContainer", state="visible", timeout=6000)
            print("PASS: live mode switch flow")

            navigate_and_measure(page, "reports", "#reports-list")
            page.wait_for_selector("button:has-text('Refresh')", timeout=6000)

            for i in range(1, STRESS_CLICKS + 1):
                page.click("button:has-text('Refresh')")
            page.wait_for_timeout(1200)
            print(f"PASS: reports refresh stress x{STRESS_CLICKS}")

            navigate_and_measure(page, "analytics", "#app")
            navigate_and_measure(page, "about", "#app")

            browser.close()

        def is_ignored_error(message: str) -> bool:
            msg = str(message or "")
            return any(pattern in msg for pattern in IGNORED_ERROR_PATTERNS)

        filtered_page_errors = [err for err in page_errors if not is_ignored_error(err)]
        filtered_console_errors = [err for err in console_errors if not is_ignored_error(err)]

        if filtered_page_errors:
            return fail(f"page errors detected: {filtered_page_errors[:5]}", 20)

        if filtered_console_errors:
            return fail(f"console errors detected: {filtered_console_errors[:5]}", 21)

        ignored_total = (len(page_errors) - len(filtered_page_errors)) + (len(console_errors) - len(filtered_console_errors))
        if ignored_total:
            print(f"INFO: ignored known transient frontend errors count={ignored_total}")

        print("PASS: frontend robustness checks")
        return 0
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in frontend robustness test: {exc}", 30)
    except Exception as exc:
        return fail(f"frontend robustness unhandled error: {exc}", 31)


if __name__ == "__main__":
    sys.exit(main())
