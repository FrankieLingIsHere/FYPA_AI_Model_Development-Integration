import base64
import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


APP_URL = os.environ.get("CASM_ASSISTANT_APP_URL", "http://127.0.0.1:5001").rstrip("/")
STARTUP_WAIT_MS = int(os.environ.get("CASM_ASSISTANT_STARTUP_WAIT_MS", "120000"))
ADMIN_USERNAME = os.environ.get("CASM_ASSISTANT_ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("CASM_ASSISTANT_ADMIN_PASSWORD", "")


def fail(message: str, code: int = 2) -> int:
    print(f"FAIL: assistant action-test issue: {message}")
    return code


def wait_until_ready(page):
    page.goto(f"{APP_URL}/", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_selector("#assistantLauncher", state="visible", timeout=STARTUP_WAIT_MS)
    page.wait_for_function(
        "() => !document.body.classList.contains('startup-loading')",
        timeout=STARTUP_WAIT_MS,
    )
    page.wait_for_timeout(900)


def assert_boxes_do_not_overlap(a, b, label_a: str, label_b: str):
    if not a or not b:
        raise RuntimeError(f"Missing bounding box for {label_a} or {label_b}")
    overlaps = not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )
    if overlaps:
        raise RuntimeError(f"{label_a} overlaps {label_b}")


def read_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fetch_json(path: str, *, username: str = "", password: str = ""):
    url = f"{APP_URL}{path}"
    request = Request(url, headers={"Accept": "application/json"})
    if username or password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def choose_reports_export_case():
    payload = fetch_json("/api/violations?limit=200")
    if isinstance(payload, dict):
        rows = payload.get("violations") or payload.get("reports") or payload.get("items") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Violations API did not return rows for assistant export testing")

    candidates = [
        (
            "export high local synced reports csv",
            lambda row: str(row.get("source_scope") or "").strip().lower() == "synced_local"
            and str(row.get("severity") or "").strip().lower() == "high",
            {"source_scope": "synced_local", "severity": "high"},
        ),
        (
            "export high cloud reports csv",
            lambda row: str(row.get("source_scope") or "").strip().lower() == "cloud"
            and str(row.get("severity") or "").strip().lower() == "high",
            {"source_scope": "cloud", "severity": "high"},
        ),
        (
            "export cloud reports csv",
            lambda row: str(row.get("source_scope") or "").strip().lower() == "cloud",
            {"source_scope": "cloud"},
        ),
        (
            "export local reports csv",
            lambda row: str(row.get("source_scope") or "").strip().lower() == "local",
            {"source_scope": "local"},
        ),
    ]

    for prompt, predicate, expected in candidates:
        matched = [row for row in rows if isinstance(row, dict) and predicate(row)]
        if matched:
            return prompt, expected, matched

    raise RuntimeError("Could not find a real assistant export filter case from the live violations API")


def main() -> int:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            export_prompt, export_expectations, _source_rows = choose_reports_export_case()

            desktop = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 960})
            desktop_page = desktop.new_page()
            desktop_page.on("dialog", lambda dialog: dialog.accept())
            wait_until_ready(desktop_page)

            launcher = desktop_page.locator("#assistantLauncher")
            bell = desktop_page.locator("#notifBellHost")
            assistant_panel = desktop_page.locator("#assistantPanel")
            assistant_input = desktop_page.locator("#assistantInput")

            launcher_box = launcher.bounding_box()
            bell_box = bell.bounding_box()
            assert_boxes_do_not_overlap(launcher_box, bell_box, "assistant launcher", "notification bell")
            print("PASS: desktop launcher is visible and clear of the bell")

            launcher.click()
            assistant_panel.wait_for(state="visible", timeout=15000)
            desktop_page.wait_for_timeout(400)
            if not desktop_page.locator("#assistantInput").is_visible():
                raise RuntimeError("Assistant input is not visible after opening the panel")
            if not desktop_page.locator("#assistantPromptDeck").is_visible():
                raise RuntimeError("Assistant starter prompts are not visible")
            if not desktop_page.locator(".assistant-composer-guide").is_visible():
                raise RuntimeError("Assistant composer guide is not visible")
            starter_mode = desktop_page.locator("#assistantPromptDeck [data-prompt-mode]").get_attribute("data-prompt-mode")
            starter_text = desktop_page.locator("#assistantPromptDeck").inner_text()
            if starter_mode != "starter" or "Show local tutorial" not in starter_text:
                raise RuntimeError("Assistant did not render the expected starter prompt deck")
            print("PASS: assistant input and starter prompts are visible")

            desktop_page.evaluate(
                """
                () => {
                    if (typeof NotificationManager !== 'undefined' && NotificationManager.show) {
                        NotificationManager.show('Assistant verification toast', 'warning', 0, {
                            forceToast: true,
                            persistHistory: false,
                            dedupeKey: 'assistant-action-test-toast'
                        });
                    }
                }
                """
            )
            desktop_page.wait_for_timeout(500)
            notification_box = desktop_page.locator("#notification-container").bounding_box()
            panel_box = assistant_panel.bounding_box()
            assert_boxes_do_not_overlap(notification_box, panel_box, "notification container", "assistant panel")
            print("PASS: notification stack stays clear of the assistant panel")

            assistant_input.fill("show local tutorial")
            assistant_input.press("Enter")
            desktop_page.wait_for_selector("text=Local tutorial loaded.", timeout=20000)
            desktop_page.wait_for_selector("text=Local Pipeline", timeout=20000)
            tutorial_mode = desktop_page.locator("#assistantPromptDeck [data-prompt-mode]").get_attribute("data-prompt-mode")
            tutorial_text = desktop_page.locator("#assistantPromptDeck").inner_text()
            if tutorial_mode != "tutorial-local" or "Next tutorial step" not in tutorial_text:
                raise RuntimeError("Prompt deck did not adapt to the local tutorial flow")
            print("PASS: tutorial card appears in chat")

            desktop_page.locator(".assistant-action-btn", has_text="Next step").last.click()
            desktop_page.wait_for_selector("text=Step 2 of 4", timeout=15000)
            print("PASS: tutorial step controls advance in chat")

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                with desktop_page.expect_download(timeout=30000) as download_info:
                    assistant_input.fill("export analytics csv")
                    assistant_input.press("Enter")
                analytics_download = download_info.value
                analytics_name = analytics_download.suggested_filename
                if "analytics" not in analytics_name.lower():
                    raise RuntimeError(f"Unexpected analytics export filename: {analytics_name}")
                analytics_path = temp_path / analytics_name
                analytics_download.save_as(str(analytics_path))
                analytics_rows = read_csv_rows(analytics_path)
                if not any(str(row.get("metric") or "").strip() == "ready_rate_percent" for row in analytics_rows):
                    raise RuntimeError("Analytics export did not include ready_rate_percent")
                analytics_mode = desktop_page.locator("#assistantPromptDeck [data-prompt-mode]").get_attribute("data-prompt-mode")
                analytics_text = desktop_page.locator("#assistantPromptDeck").inner_text()
                if analytics_mode != "analytics-export" or "Open analytics" not in analytics_text:
                    raise RuntimeError("Prompt deck did not adapt after analytics export")
                print("PASS: analytics CSV download contains summary metrics")

                with desktop_page.expect_download(timeout=30000) as download_info:
                    assistant_input.fill(export_prompt)
                    assistant_input.press("Enter")
                reports_download = download_info.value
                reports_name = reports_download.suggested_filename
                if "reports" not in reports_name.lower():
                    raise RuntimeError(f"Unexpected reports export filename: {reports_name}")
                reports_path = temp_path / reports_name
                reports_download.save_as(str(reports_path))
                report_rows = read_csv_rows(reports_path)
                if not report_rows:
                    raise RuntimeError("Assistant reports export returned an empty CSV")
                for row in report_rows:
                    if "source_scope" in export_expectations:
                        actual_scope = str(row.get("source_scope") or "").strip().lower()
                        if actual_scope != export_expectations["source_scope"]:
                            raise RuntimeError(
                                f"Reports export broke source filtering: expected {export_expectations['source_scope']}, got {actual_scope}"
                            )
                    if "severity" in export_expectations:
                        actual_severity = str(row.get("severity") or "").strip().lower()
                        if actual_severity != export_expectations["severity"]:
                            raise RuntimeError(
                                f"Reports export broke severity filtering: expected {export_expectations['severity']}, got {actual_severity}"
                            )
                print(f"PASS: reports CSV export honors natural-language filters via '{export_prompt}'")

            assistant_input.fill("find docs about wifi reconnect local sync")
            assistant_input.press("Enter")
            desktop_page.wait_for_selector(".assistant-doc-card", timeout=15000)
            docs_mode = desktop_page.locator("#assistantPromptDeck [data-prompt-mode]").get_attribute("data-prompt-mode")
            docs_text = desktop_page.locator("#assistantPromptDeck").inner_text()
            if docs_mode != "docs" or "Export docs CSV" not in docs_text:
                raise RuntimeError("Prompt deck did not adapt after handbook search")
            desktop_page.locator(".assistant-doc-card .assistant-inline-link").first.click()
            desktop_page.wait_for_timeout(400)
            if "hidden" in (desktop_page.get_attribute("#handbookModal", "class") or ""):
                raise RuntimeError("Handbook did not open from assistant documentation result")
            active_workflow = desktop_page.locator("#handbook-workflow.active")
            if active_workflow.count() == 0:
                raise RuntimeError("Expected workflow handbook page to activate from assistant docs result")
            print("PASS: assistant docs results open the handbook section")

            desktop_page.click("#closeHandbook")
            desktop_page.wait_for_timeout(300)
            session_chips_before = desktop_page.locator(".assistant-session-chip").count()
            desktop_page.click("#assistantNewSession")
            desktop_page.wait_for_timeout(500)
            session_chips_after = desktop_page.locator(".assistant-session-chip").count()
            if session_chips_after <= session_chips_before:
                raise RuntimeError("Creating a new assistant session did not add another session entry")
            print("PASS: session history is available and a new session can be created")

            desktop_page.wait_for_timeout(1400)
            if ADMIN_PASSWORD:
                client_id = desktop_page.evaluate(
                    "() => window.localStorage.getItem('casm.assistant.clientId.v1') || ''"
                )
                try:
                    fetch_json("/admin/assistant-sessions?format=json")
                except HTTPError as exc:
                    if exc.code != 401:
                        raise RuntimeError(f"Admin assistant sessions endpoint returned {exc.code} instead of 401 without auth")
                else:
                    raise RuntimeError("Admin assistant sessions endpoint was readable without credentials")
                admin_payload = fetch_json(
                    "/admin/assistant-sessions?format=json",
                    username=ADMIN_USERNAME,
                    password=ADMIN_PASSWORD,
                )
                entries = admin_payload.get("entries") if isinstance(admin_payload, dict) else []
                matching = [
                    entry for entry in (entries or [])
                    if str(entry.get("client_id") or "").strip() == str(client_id).strip()
                ]
                if not matching:
                    raise RuntimeError("Admin assistant session log did not contain the current browser client")
                if int(matching[0].get("session_count") or 0) < 1:
                    raise RuntimeError("Admin assistant session log stored zero sessions for the current client")
                print("PASS: assistant session sync is only exposed through the admin endpoint")
            else:
                print("INFO: skipped admin session sync readback because assistant admin credentials were not provided")

            mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                accept_downloads=True,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            )
            mobile_page = mobile.new_page()
            mobile_page.on("dialog", lambda dialog: dialog.accept())
            wait_until_ready(mobile_page)

            mobile_launcher = mobile_page.locator("#assistantLauncher")
            mobile_nav = mobile_page.locator(".mobile-bottom-nav")
            mobile_launcher_box = mobile_launcher.bounding_box()
            mobile_nav_box = mobile_nav.bounding_box()
            if not mobile_launcher_box or not mobile_nav_box:
                raise RuntimeError("Missing mobile bounding boxes for launcher or bottom nav")
            if mobile_launcher_box["y"] + mobile_launcher_box["height"] >= mobile_nav_box["y"]:
                raise RuntimeError("Mobile assistant launcher overlaps the bottom navigation")

            mobile_launcher.click()
            mobile_page.wait_for_selector("#assistantPanel", state="visible", timeout=15000)
            mobile_panel_box = mobile_page.locator("#assistantPanel").bounding_box()
            if not mobile_panel_box or mobile_panel_box["width"] > 390:
                raise RuntimeError("Mobile assistant panel overflowed the viewport width")
            mobile_page.evaluate(
                """
                () => {
                    if (typeof NotificationManager !== 'undefined' && NotificationManager.show) {
                        NotificationManager.show('Mobile assistant toast', 'info', 0, {
                            forceToast: true,
                            persistHistory: false,
                            dedupeKey: 'assistant-mobile-action-test-toast'
                        });
                    }
                }
                """
            )
            mobile_page.wait_for_timeout(450)
            mobile_notification_box = mobile_page.locator("#notification-container").bounding_box()
            mobile_panel_box = mobile_page.locator("#assistantPanel").bounding_box()
            assert_boxes_do_not_overlap(
                mobile_notification_box,
                mobile_panel_box,
                "mobile notification container",
                "mobile assistant panel",
            )
            print("PASS: mobile assistant launcher clears the bottom nav and panel fits")

            mobile.close()
            desktop.close()
            browser.close()

        print("PASS: assistant action checks")
        return 0
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in assistant action test: {exc}", 40)
    except Exception as exc:
        return fail(f"assistant action-test unhandled error: {exc}", 41)


if __name__ == "__main__":
    sys.exit(main())
