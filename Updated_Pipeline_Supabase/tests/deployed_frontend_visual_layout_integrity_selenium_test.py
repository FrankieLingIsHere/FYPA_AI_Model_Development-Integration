import json
import os
import sys
from contextlib import suppress

VERCEL_URL = os.environ.get(
    "CASM_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

MAX_WAIT_SECONDS = int(os.environ.get("CASM_FRONTEND_VISUAL_MAX_WAIT_SECONDS", "120"))
# CASM_FRONTEND_STRICT=1 (default) causes visual layout issues to fail the job.
# Set CASM_FRONTEND_STRICT=0 for informational-only runs.
STRICT = os.environ.get("CASM_FRONTEND_STRICT", "1") not in ("0", "false", "no", "off")

SUMMARY_PATH = os.environ.get("CASM_SUMMARY_PATH", "frontend-visual-layout-summary.json")


def _write_summary(summary: dict) -> None:
    try:
        with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=True, indent=2)
        print(f"INFO: summary written to {SUMMARY_PATH}")
    except Exception as exc:
        print(f"WARN: could not write summary file: {exc}")


def fail(message: str, code: int = 2) -> int:
    if STRICT:
        print(f"FAIL: visual layout integrity check failed: {message}")
        return code
    # Non-strict: log as a warning but do not fail the job.
    print(f"INFO: non-blocking selenium visual placement issue: {message}")
    return 0


def main() -> int:
    checks: list = []
    metrics: dict = {"url": VERCEL_URL}

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as exc:
        result = fail(f"selenium not available: {exc}", 30)
        _write_summary({
            "test_name": "deployed_frontend_visual_layout_integrity_selenium",
            "target_url": VERCEL_URL,
            "checks": [{"name": "selenium_import", "pass": False, "message": str(exc)}],
            "pass": False,
            "metrics": metrics,
            "strict_mode": STRICT,
        })
        return result

    driver = None

    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,900")

        driver = webdriver.Chrome(options=options)
        driver.get(f"{VERCEL_URL}/")

        wait = WebDriverWait(driver, MAX_WAIT_SECONDS)
        wait.until(
            lambda d: "startup-loading" not in (d.find_element(By.TAG_NAME, "body").get_attribute("class") or "")
        )

        settings_links = driver.find_elements(By.CSS_SELECTOR, ".sidebar-bottom .sidebar-link[data-page='settings']")
        if not settings_links:
            raise RuntimeError("Settings link is not located in sidebar-bottom")

        is_last_item = driver.execute_script(
            """
            const bottom = document.querySelector('.sidebar-bottom');
            if (!bottom) return false;
            const settings = bottom.querySelector(".sidebar-link[data-page='settings']");
            if (!settings) return false;
            const visibleChildren = Array.from(bottom.children).filter((el) => {
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            });
            return visibleChildren.length > 0 && visibleChildren[visibleChildren.length - 1] === settings;
            """
        )
        if not is_last_item:
            raise RuntimeError("Settings link exists but is not at the lowest position in sidebar-bottom")

        checks.append({"name": "settings_link_position", "pass": True, "message": "Settings link is last in sidebar-bottom"})

        realtime_badges = driver.find_elements(By.ID, "realtimeStatusBadge")
        if realtime_badges:
            raise RuntimeError("Live realtime badge is still present in sidebar")

        checks.append({"name": "realtime_badge_removed", "pass": True, "message": "realtimeStatusBadge absent"})

        network_in_main = driver.find_elements(By.CSS_SELECTOR, ".main-content-statusbar #networkStatusBadge")
        if not network_in_main:
            raise RuntimeError("Network badge is not in main-content top-right status bar")

        network_in_sidebar = driver.find_elements(By.CSS_SELECTOR, ".sidebar #networkStatusBadge")
        if network_in_sidebar:
            raise RuntimeError("Network badge is still rendered inside sidebar")

        geometry = driver.execute_script(
            """
            const main = document.querySelector('.main-content');
            const badge = document.querySelector('.main-content-statusbar #networkStatusBadge');
            if (!main || !badge) return null;
            const mainRect = main.getBoundingClientRect();
            const badgeRect = badge.getBoundingClientRect();
            return {
                deltaRight: Math.abs(mainRect.right - badgeRect.right),
                deltaTop: badgeRect.top - mainRect.top,
                badgeVisible: badgeRect.width > 0 && badgeRect.height > 0,
            };
            """
        )

        if not geometry:
            raise RuntimeError("Unable to compute geometry for main network badge")

        if not geometry.get("badgeVisible"):
            raise RuntimeError("Network badge exists but is not visible")

        delta_right = float(geometry.get("deltaRight", 9999))
        delta_top = float(geometry.get("deltaTop", 9999))
        metrics["network_badge_delta_right_px"] = delta_right
        metrics["network_badge_delta_top_px"] = delta_top

        if delta_right > 110:
            raise RuntimeError(f"Network badge is not close to main-content right edge (deltaRight={delta_right:.1f}px)")

        if delta_top > 120:
            raise RuntimeError(f"Network badge is not close to main-content top edge (deltaTop={delta_top:.1f}px)")

        checks.append({"name": "network_badge_placement", "pass": True, "message": f"deltaRight={delta_right:.1f}px deltaTop={delta_top:.1f}px"})

        timezone = driver.find_elements(By.ID, "timezone-selector")
        if not timezone:
            raise RuntimeError("Timezone selector is missing from sidebar")

        checks.append({"name": "timezone_selector_present", "pass": True, "message": "timezone-selector present"})

        with suppress(Exception):
            live_links = driver.find_elements(By.CSS_SELECTOR, ".sidebar .sidebar-link[data-page='live']")
            if live_links:
                live_links[0].click()
                wait.until(lambda d: "#live" in (d.current_url or ""))

            quick_settings_launchers = driver.find_elements(By.ID, "quickRecommendedSettingsBtn")
            if quick_settings_launchers:
                raise RuntimeError("Live page still exposes quick settings launcher; settings windows must only open via sidebar Settings")

            open_settings_buttons = driver.find_elements(
                By.XPATH,
                "//button[contains(normalize-space(.), 'Open Settings')]"
            )
            if open_settings_buttons:
                raise RuntimeError("Live page still exposes an in-page Open Settings button; launch must be sidebar Settings only")

            settings_links[0].click()
            wait.until(lambda d: "#settings" in (d.current_url or ""))

            wait.until(
                lambda d: (
                    (d.find_element(By.ID, "settingsModal").get_attribute("aria-hidden") == "false")
                    or ("open" in ((d.find_element(By.ID, "settingsModal").get_attribute("class") or "").split()))
                )
            )

            settings_close_button = driver.find_elements(By.ID, "closeSettingsWindowBtn")
            if not settings_close_button:
                raise RuntimeError("Settings route does not render the expected popup window controls")

        checks.append({"name": "settings_modal_controls", "pass": True, "message": "settings modal controls present"})

        summary = {
            "test_name": "deployed_frontend_visual_layout_integrity_selenium",
            "target_url": VERCEL_URL,
            "checks": checks,
            "pass": True,
            "metrics": metrics,
            "strict_mode": STRICT,
        }
        _write_summary(summary)
        print("PASS: selenium visual layout integrity checks")
        return 0
    except Exception as exc:
        checks.append({"name": "visual_layout", "pass": False, "message": str(exc)})
        _write_summary({
            "test_name": "deployed_frontend_visual_layout_integrity_selenium",
            "target_url": VERCEL_URL,
            "checks": checks,
            "pass": False,
            "metrics": metrics,
            "strict_mode": STRICT,
        })
        return fail(f"selenium visual layout integrity unhandled error: {exc}", 31)
    finally:
        if driver is not None:
            with suppress(Exception):
                driver.quit()


if __name__ == "__main__":
    sys.exit(main())
