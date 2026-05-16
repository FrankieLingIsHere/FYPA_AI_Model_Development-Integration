from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
ASSISTANT_JS = ROOT / "frontend" / "js" / "assistant.js"


def _build_page_html() -> str:
    script = ASSISTANT_JS.read_text(encoding="utf-8")
    return f"""
<!doctype html>
<html>
<body>
    <div id="assistantDock">
        <button id="assistantLauncher" type="button"></button>
        <section id="assistantPanel" class="hidden">
            <button id="assistantClose" type="button"></button>
            <button id="assistantSessionsToggle" type="button"></button>
            <button id="assistantNewSession" type="button"></button>
            <aside id="assistantSessionRail"><div id="assistantSessionList"></div></aside>
            <div id="assistantShortcutStrip"></div>
            <div id="assistantPromptDeck"></div>
            <div id="assistantMessages"></div>
            <form id="assistantComposer">
                <textarea id="assistantInput"></textarea>
                <button id="assistantSend" type="submit">Send</button>
            </form>
            <h2 id="assistantTitle"></h2>
            <span id="assistantKicker"></span>
            <p id="assistantSubtitle"></p>
        </section>
    </div>
    <div id="handbookModal">
        <section id="handbook-intro" class="handbook-page">
            <h3>Intro</h3>
            <p>Mira helps with reports, exports, and workflow guidance.</p>
        </section>
        <section id="handbook-workflow" class="handbook-page">
            <h3>Workflow</h3>
            <div data-stage-panel="reports">
                <h4>Reports</h4>
                <p>Reports include severity, likelihood, source tags, and evidence rows.</p>
            </div>
        </section>
    </div>
    <script>
    window.APP_STATE = {{ currentPage: 'reports' }};
    window.Router = {{ navigate: (page) => {{ window.APP_STATE.currentPage = page; }} }};
    window.TimezoneManager = {{ formatDateTime: (value) => String(value) }};
    window.CASM_TUTORIAL_FLOWS = {{ cloud: [], local: [] }};
    window.API = {{
        getImageUrl: () => '',
        getReportUrl: () => '',
        getViolations: async () => [
            {{
                report_id: 'front-gate-001',
                timestamp: '2026-05-15T08:00:00Z',
                status: 'completed',
                severity: 'MEDIUM',
                device_id: 'front-gate-cam',
                violation_count: 1,
                missing_ppe: ['Mask'],
                source_scope: 'cloud',
                source_label: 'Cloud',
                violation_summary: 'PPE Violation Detected: Missing Mask at front gate'
            }},
            {{
                report_id: 'loading-bay-002',
                timestamp: '2026-05-15T07:30:00Z',
                status: 'completed',
                severity: 'HIGH',
                device_id: 'loading-bay-cam',
                violation_count: 2,
                missing_ppe: ['Hardhat', 'Safety Vest'],
                source_scope: 'local',
                source_label: 'Local',
                violation_summary: 'PPE Violation Detected: Missing Hardhat, Missing Safety Vest near loading bay'
            }}
        ]
    }};
    </script>
    <script>{script}</script>
</body>
</html>
"""


def _submit_prompt(page, prompt: str) -> None:
    page.locator("#assistantInput").fill(prompt)
    page.locator("#assistantSend").click()


def test_assistant_explains_likelihood_and_browses_report_risks():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(_build_page_html(), wait_until="domcontentloaded")
        page.wait_for_selector("#assistantTitle", state="visible")
        page.locator("#assistantLauncher").click()

        _submit_prompt(page, "what does likelihood mean in the report")
        page.get_by_text("Likelihood in a report means", exact=False).wait_for(timeout=10000)

        _submit_prompt(page, "i wanna know what is the main risks of each case")
        page.get_by_text("Report 1 of 2", exact=False).wait_for(timeout=10000)
        assert "front-gate-001" in page.locator("#assistantMessages").inner_text()

        _submit_prompt(page, "what/how is the latest reports so far, can i have a look?")
        page.get_by_text("Report 1 of 2", exact=False).wait_for(timeout=10000)

        _submit_prompt(page, "i wanna see cloud reports")
        page.get_by_text("Report 1 of 1", exact=False).wait_for(timeout=10000)
        cloud_prompt_text = page.locator("#assistantMessages").inner_text().split("i wanna see cloud reports")[-1]
        assert "front-gate-001" in cloud_prompt_text
        assert "loading-bay-002" not in cloud_prompt_text

        _submit_prompt(page, "export 2026-05-15 cloud medium mask reports csv")
        page.get_by_text("Reports CSV is prepared", exact=False).wait_for(timeout=10000)
        page.locator(".assistant-action-btn", has_text="Download CSV").last.wait_for(timeout=10000)
        export_preview = page.locator("#assistantMessages").inner_text()
        assert "front-gate-001" in export_preview
        assert "loading-bay-002" not in export_preview.split("export 2026-05-15 cloud medium mask reports csv")[-1]

        _submit_prompt(page, "i wanna check reports on front gate")
        page.get_by_text("Report 1 of 1", exact=False).wait_for(timeout=10000)
        message_text = page.locator("#assistantMessages").inner_text()
        assert "front-gate-001" in message_text
        assert "loading-bay-002" not in message_text.split("i wanna check reports on front gate")[-1]

        page.locator(".assistant-action-btn", has_text="Explain this report").last.click()
        page.get_by_text("Here is a fuller read of report front-gate-001", exact=False).wait_for(timeout=10000)
        explanation_text = page.locator("#assistantMessages").inner_text()
        assert "What happened:" in explanation_text
        assert "Recommended next step:" in explanation_text

        _submit_prompt(page, "i wanna check reports on no-such-zone-999")
        page.get_by_text("I could not find report rows", exact=False).wait_for(timeout=10000)
        browser.close()


def test_assistant_role_aliases_and_busy_guard_keep_chat_order_clear():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(_build_page_html(), wait_until="domcontentloaded")
        page.wait_for_selector("#assistantTitle", state="visible")
        page.locator("#assistantLauncher").click()

        page.evaluate(
            """
            const session = window.CASMAssistant.getActiveSession();
            session.messages = [
                { id: 'assistant-alias-1', role: 'Mira', text: 'Alias message one' },
                { id: 'assistant-alias-2', role: 'Moira', text: 'Alias message two' },
                { id: 'user-message-1', role: 'user', text: 'User message' }
            ].map((message) => window.CASMAssistant.normalizeMessage(message));
            window.CASMAssistant.refreshSessionUi();
            """
        )
        assert page.locator(".assistant-message-assistant").count() == 2
        assert page.locator(".assistant-message-user").count() == 1

        page.evaluate(
            """
            window.__resolveViolations = null;
            window.__violationsPromise = new Promise((resolve) => {
                window.__resolveViolations = resolve;
            });
            window.API.getViolations = async () => window.__violationsPromise;
            """
        )

        _submit_prompt(page, "i wanna see cloud reports")
        page.get_by_text("Finding matching reports", exact=False).wait_for(timeout=10000)
        assert page.locator("#assistantInput").is_disabled()
        assert page.locator("#assistantSend").is_disabled()

        page.evaluate("window.CASMAssistant.runSuggestedPrompt('export reports csv')")
        user_prompts = page.evaluate(
            "window.CASMAssistant.getActiveSession().messages.filter((message) => message.role === 'user').map((message) => message.text)"
        )
        assert user_prompts.count("i wanna see cloud reports") == 1
        assert "export reports csv" not in user_prompts

        page.evaluate(
            """
            window.__resolveViolations([
                {
                    report_id: 'cloud-delayed-001',
                    timestamp: '2026-05-15T09:00:00Z',
                    status: 'completed',
                    severity: 'HIGH',
                    device_id: 'cloud-cam',
                    violation_count: 1,
                    missing_ppe: ['Safety Vest'],
                    source_scope: 'cloud',
                    source_label: 'Cloud',
                    violation_summary: 'PPE Violation Detected: Missing Safety Vest'
                }
            ]);
            """
        )
        page.get_by_text("Report 1 of 1", exact=False).wait_for(timeout=10000)
        assert "cloud-delayed-001" in page.locator("#assistantMessages").inner_text()
        assert not page.locator("#assistantInput").is_disabled()
        browser.close()
