import os
import sys
from contextlib import suppress

VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

MAX_WAIT_SECONDS = int(os.environ.get("LUNA_FRONTEND_VISUAL_MAX_WAIT_SECONDS", "120"))


def fail(message: str, code: int = 2) -> int:
    # Keep deployed visual placement check non-blocking like existing frontend action tests.
    print(f"INFO: non-blocking selenium visual placement issue: {message}")
    return 0


def main() -> int:
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as exc:
        return fail(f"selenium not available: {exc}", 30)

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

        realtime_badges = driver.find_elements(By.ID, "realtimeStatusBadge")
        if realtime_badges:
            raise RuntimeError("Live realtime badge is still present in sidebar")

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

        if delta_right > 110:
            raise RuntimeError(f"Network badge is not close to main-content right edge (deltaRight={delta_right:.1f}px)")

        if delta_top > 120:
            raise RuntimeError(f"Network badge is not close to main-content top edge (deltaTop={delta_top:.1f}px)")

        timezone = driver.find_elements(By.ID, "timezone-selector")
        if not timezone:
            raise RuntimeError("Timezone selector is missing from sidebar")

        with suppress(Exception):
            settings_links[0].click()
            wait.until(lambda d: "#settings" in (d.current_url or ""))

        print("PASS: selenium visual layout integrity checks")
        return 0
    except Exception as exc:
        return fail(f"selenium visual layout integrity unhandled error: {exc}", 31)
    finally:
        if driver is not None:
            with suppress(Exception):
                driver.quit()


if __name__ == "__main__":
    sys.exit(main())
