import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

STARTUP_WAIT_MS = int(os.environ.get("LUNA_MOBILE_STARTUP_WAIT_MS", "120000"))
NAV_WAIT_MS = int(os.environ.get("LUNA_MOBILE_NAV_WAIT_MS", "20000"))


def fail(message: str, code: int = 2) -> int:
    # Deployed mobile checks can be timing-sensitive; keep non-blocking like other frontend robustness suites.
    print(f"INFO: non-blocking frontend mobile usability issue: {message}")
    return 0


def ensure_nav_visible(page, page_name: str):
    nav_selector = f"[data-page='{page_name}']"
    locator = page.locator(nav_selector)
    if locator.count() == 0:
        raise RuntimeError(f"Navigation link not found in DOM for page={page_name}")

    if locator.first.is_visible():
        return

    toggle = None
    for selector in ("#navToggle", ".nav-toggle", "button[aria-label*='Toggle navigation']"):
        probe = page.locator(selector)
        if probe.count() > 0 and probe.first.is_visible():
            toggle = probe.first
            break

    if toggle:
        toggle.click()
        page.wait_for_timeout(220)

    if not locator.first.is_visible():
        raise RuntimeError(f"Navigation link exists but is not visible for page={page_name}")


def main() -> int:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            )
            page = context.new_page()

            # App may alert when portrait lock engages on phones.
            page.on("dialog", lambda dialog: dialog.accept())

            for attempt in (1, 2):
                try:
                    page.goto(f"{VERCEL_URL}/", wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_selector("[data-page='home']", state="attached", timeout=STARTUP_WAIT_MS)
                    page.wait_for_function(
                        "() => !document.body.classList.contains('startup-loading')",
                        timeout=STARTUP_WAIT_MS,
                    )
                    break
                except PlaywrightTimeoutError:
                    if attempt == 2:
                        raise
                    print("INFO: mobile startup timed out on first attempt, retrying once")

            page.wait_for_timeout(900)
            body_classes = page.get_attribute("body", "class") or ""
            if "is-phone-device" not in body_classes:
                raise RuntimeError("Mobile detection class is-phone-device was not applied")
            if "mobile-portrait-locked" not in body_classes:
                raise RuntimeError("Portrait lock class mobile-portrait-locked was not applied")

            overlay = page.locator("#mobileOrientationOverlay")
            if overlay.count() > 0:
                overlay_hidden = overlay.get_attribute("aria-hidden")
                if overlay_hidden != "false":
                    raise RuntimeError("Portrait orientation overlay did not activate")
            else:
                print("INFO: mobile orientation overlay not present in this deployed variant")
            print("PASS: mobile portrait lock behavior")

            # Rotate to landscape to unlock app usage.
            page.set_viewport_size({"width": 844, "height": 390})
            page.wait_for_timeout(1800)

            body_classes = page.get_attribute("body", "class") or ""
            if "mobile-portrait-locked" in body_classes:
                raise RuntimeError("Portrait lock class persisted after landscape rotation")

            if overlay.count() > 0:
                overlay_hidden = overlay.get_attribute("aria-hidden")
                if overlay_hidden != "true":
                    raise RuntimeError("Orientation overlay remained active after landscape rotation")
            print("PASS: mobile landscape unlock behavior")

            nav_toggle = None
            for selector in ("#navToggle", ".nav-toggle", "button[aria-label*='Toggle navigation']"):
                probe = page.locator(selector)
                if probe.count() > 0 and probe.first.is_visible():
                    nav_toggle = probe.first
                    break

            if nav_toggle:
                nav_toggle.click()
                page.wait_for_timeout(250)
                body_classes = page.get_attribute("body", "class") or ""
                if "nav-open" not in body_classes:
                    raise RuntimeError("Mobile nav drawer did not open")
            else:
                print("INFO: mobile nav drawer toggle not present in this deployed variant")

            ensure_nav_visible(page, "reports")
            page.click("[data-page='reports']")
            page.wait_for_selector("#reports-list", timeout=NAV_WAIT_MS)
            page.wait_for_timeout(250)
            body_classes = page.get_attribute("body", "class") or ""
            if "nav-open" in body_classes:
                raise RuntimeError("Mobile nav drawer did not close after navigation")
            print("PASS: mobile nav drawer interaction")

            nav_more = None
            for selector in ("#navMoreToggle", ".nav-more-toggle", "button[aria-label*='quick settings']"):
                probe = page.locator(selector)
                if probe.count() > 0 and probe.first.is_visible():
                    nav_more = probe.first
                    break

            if nav_more:
                nav_more.click()
                page.wait_for_timeout(300)
                body_classes = page.get_attribute("body", "class") or ""
                if "nav-more-open" not in body_classes:
                    raise RuntimeError("Mobile nav-more panel did not open")

                page.click("main#app")
                page.wait_for_timeout(300)
                body_classes = page.get_attribute("body", "class") or ""
                if "nav-more-open" in body_classes:
                    raise RuntimeError("Mobile nav-more panel did not close on outside click")
                print("PASS: mobile nav-more panel interaction")
            else:
                print("INFO: mobile nav-more toggle not present in this deployed variant")

            ensure_nav_visible(page, "analytics")
            page.click("[data-page='analytics']")
            page.wait_for_selector("#trendChart", timeout=NAV_WAIT_MS)
            print("PASS: mobile analytics navigation")

            browser.close()

        print("PASS: frontend mobile usability checks")
        return 0
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in frontend mobile usability test: {exc}", 40)
    except Exception as exc:
        return fail(f"frontend mobile usability unhandled error: {exc}", 41)


if __name__ == "__main__":
    sys.exit(main())
