# Readability: Test setup: document the contract this file protects.
import os
import sys
from contextlib import suppress

# Prepare vercel url for the next step.
VERCEL_URL = os.environ.get(
    "CASM_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")

MAX_WAIT_SECONDS = int(os.environ.get("CASM_FRONTEND_VISUAL_MAX_WAIT_SECONDS", "180"))


# Section: run the fail workflow with clear inputs and outputs.
def fail(message: str, code: int = 2) -> int:
    # Trigger the side effect required for this stage.
    print(f"FAIL: selenium visual placement issue: {message}")
    return code


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    try:
        from selenium import webdriver
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as exc:
        # Return the prepared result to the caller.
        return fail(f"selenium not available: {exc}", 30)

    # Prepare driver for the next step.
    driver = None

    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Trigger the side effect required for this stage.
        options.add_argument("--window-size=1440,900")

        driver = webdriver.Chrome(options=options)
        driver.get(f"{VERCEL_URL}/")

        wait = WebDriverWait(driver, MAX_WAIT_SECONDS)
        wait.until(
            lambda d: "startup-loading" not in (d.find_element(By.TAG_NAME, "body").get_attribute("class") or "")
        )

        # Prepare settings links for the next step.
        settings_links = driver.find_elements(By.CSS_SELECTOR, ".sidebar-bottom .sidebar-link[data-page='settings']")
        if not settings_links:
            # Surface the failure with enough context for the caller.
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
            if (visibleChildren.length === 0) return false;
            const lastChild = visibleChildren[visibleChildren.length - 1];
            return lastChild === settings || lastChild.classList.contains('sidebar-voice-group');
            """
        )
        # Choose the correct branch before the workflow continues.
        if not is_last_item:
            # Surface the failure with enough context for the caller.
            raise RuntimeError("Settings link exists but layout of sidebar-bottom has changed (expected Settings or Voice controls at bottom)")

        realtime_badges = driver.find_elements(By.ID, "realtimeStatusBadge")
        if realtime_badges:
            raise RuntimeError("Live realtime badge is still present in sidebar")

        network_in_main = driver.find_elements(By.CSS_SELECTOR, ".main-content-statusbar #networkStatusBadge")
        if not network_in_main:
            raise RuntimeError("Network badge is not in main-content top-right status bar")

        # Prepare network in sidebar for the next step.
        network_in_sidebar = driver.find_elements(By.CSS_SELECTOR, ".sidebar #networkStatusBadge")
        if network_in_sidebar:
            # Surface the failure with enough context for the caller.
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

        # Choose the correct branch before the workflow continues.
        if not geometry:
            # Surface the failure with enough context for the caller.
            raise RuntimeError("Unable to compute geometry for main network badge")

        if not geometry.get("badgeVisible"):
            raise RuntimeError("Network badge exists but is not visible")

        delta_right = float(geometry.get("deltaRight", 9999))
        delta_top = float(geometry.get("deltaTop", 9999))

        # Choose the correct branch before the workflow continues.
        if delta_right > 110:
            # Surface the failure with enough context for the caller.
            raise RuntimeError(f"Network badge is not close to main-content right edge (deltaRight={delta_right:.1f}px)")

        if delta_top > 120:
            raise RuntimeError(f"Network badge is not close to main-content top edge (deltaTop={delta_top:.1f}px)")

        timezone = driver.find_elements(By.ID, "timezone-selector")
        if not timezone:
            raise RuntimeError("Timezone selector is missing from sidebar")

        # Open the managed resource only for the block that needs it.
        with suppress(Exception):
            # Prepare live links for the next step.
            live_links = driver.find_elements(By.CSS_SELECTOR, ".sidebar .sidebar-link[data-page='live']")
            if live_links:
                # Trigger the side effect required for this stage.
                live_links[0].click()
                wait.until(lambda d: "#live" in (d.current_url or ""))

            quick_settings_launchers = driver.find_elements(By.ID, "quickRecommendedSettingsBtn")
            if quick_settings_launchers:
                raise RuntimeError("Live page still exposes quick settings launcher; settings windows must only open via sidebar Settings")

            # Prepare open settings buttons for the next step.
            open_settings_buttons = driver.find_elements(
                By.XPATH,
                "//button[contains(normalize-space(.), 'Open Settings')]"
            )
            if open_settings_buttons:
                # Surface the failure with enough context for the caller.
                raise RuntimeError("Live page still exposes an in-page Open Settings button; launch must be sidebar Settings only")

            settings_links[0].click()
            wait.until(lambda d: "#settings" in (d.current_url or ""))

            # Trigger the side effect required for this stage.
            wait.until(
                lambda d: (
                    (d.find_element(By.ID, "settingsModal").get_attribute("aria-hidden") == "false")
                    or ("open" in ((d.find_element(By.ID, "settingsModal").get_attribute("class") or "").split()))
                )
            )

            settings_close_button = driver.find_elements(By.ID, "closeSettingsWindowBtn")
            if not settings_close_button:
                # Surface the failure with enough context for the caller.
                raise RuntimeError("Settings route does not render the expected popup window controls")

        # Trigger the side effect required for this stage.
        print("PASS: selenium visual layout integrity checks")
        return 0
    except TimeoutException as exc:
        diagnostics = {}
        if driver is not None:
            # Open the managed resource only for the block that needs it.
            with suppress(Exception):
                diagnostics["url"] = driver.current_url
            with suppress(Exception):
                # Prepare values needed by the next step.
                diagnostics["title"] = driver.title
            with suppress(Exception):
                diagnostics["body_class"] = driver.find_element(By.TAG_NAME, "body").get_attribute("class")
            with suppress(Exception):
                diagnostics["ready_state"] = driver.execute_script("return document.readyState")
        # Return the prepared result to the caller.
        return fail(
            f"selenium visual layout integrity timed out after {MAX_WAIT_SECONDS}s: "
            f"{diagnostics or str(exc)}",
            31,
        )
    except Exception as exc:
        return fail(f"selenium visual layout integrity unhandled error: {exc}", 31)
    finally:
        if driver is not None:
            # Open the managed resource only for the block that needs it.
            with suppress(Exception):
                # Trigger the side effect required for this stage.
                driver.quit()


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    sys.exit(main())
