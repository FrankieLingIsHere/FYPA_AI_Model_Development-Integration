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


def fail(message: str, code: int = 2) -> int:
    print(f"FAIL: {message}")
    return code


def navigate_and_measure(page, page_name: str, ready_selector: str):
    t0 = time.perf_counter()
    page.click(f".nav-link[data-page='{page_name}']")
    page.wait_for_selector(ready_selector, timeout=MAX_NAV_LATENCY_MS)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    print(f"PASS: nav-{page_name} latency={elapsed_ms}ms")
    if elapsed_ms > MAX_NAV_LATENCY_MS:
        raise RuntimeError(
            f"Navigation to {page_name} exceeded threshold: {elapsed_ms}ms > {MAX_NAV_LATENCY_MS}ms"
        )


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
            page.wait_for_selector(".nav-link[data-page='home']", timeout=30000)
            page.wait_for_function(
                "() => !document.body.classList.contains('startup-loading')",
                timeout=90000,
            )
            print("PASS: startup gate completed")

            navigate_and_measure(page, "live", "#startLiveBtn")
            page.wait_for_selector("#liveInlineSettingsBtn", timeout=5000)

            for i in range(1, STRESS_CLICKS + 1):
                page.click("#liveInlineSettingsBtn")
                page.wait_for_selector("#settingsModal[aria-hidden='false']", timeout=5000)
                page.click("#closeSettingsWindowBtn")
                page.wait_for_selector("#settingsModal[aria-hidden='true']", timeout=5000)
                print(f"PASS: settings open/close cycle {i}/{STRESS_CLICKS}")

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

        if page_errors:
            return fail(f"page errors detected: {page_errors[:5]}", 20)

        if console_errors:
            return fail(f"console errors detected: {console_errors[:5]}", 21)

        print("PASS: frontend robustness checks")
        return 0
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in frontend robustness test: {exc}", 30)
    except Exception as exc:
        return fail(f"frontend robustness unhandled error: {exc}", 31)


if __name__ == "__main__":
    sys.exit(main())
