from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
ASSISTANT_JS = ROOT / "frontend" / "js" / "assistant.js"


def _build_page_html() -> str:
    script = ASSISTANT_JS.read_text(encoding="utf-8")
    style = """
    .hidden { display: none; }
    #assistantPanel { width: 900px; }
    #assistantMessages {
        width: 820px;
        min-height: 420px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 12px;
    }
    .assistant-message {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        width: 100%;
    }
    .assistant-message-user {
        justify-content: flex-start;
        flex-direction: row-reverse;
    }
    .assistant-message-assistant {
        justify-content: flex-start;
    }
    .assistant-message-stack {
        display: flex;
        flex-direction: column;
        max-width: min(100%, 620px);
    }
    .assistant-message-user .assistant-message-stack {
        align-items: flex-end;
        margin-left: auto;
        max-width: min(82%, 520px);
    }
    .assistant-message-assistant .assistant-message-stack,
    .assistant-message-thinking .assistant-message-stack {
        align-items: flex-start;
        margin-right: auto;
    }
    .assistant-bubble {
        display: inline-block;
        border: 1px solid #ddd;
        padding: 8px 10px;
        border-radius: 12px;
    }
    """
    return f"""
<!doctype html>
<html>
<head>
    <style>{style}</style>
</head>
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
    const todayIso = new Date().toISOString();
    const sampleReportHtml = `<!doctype html>
        <html><body>
            <div class="section">
                <h2 class="section-title">AI Scene Description</h2>
                <div class="card"><div class="card-content"><p>Two workers are visible near the front gate. The first worker lacks a mask and the second worker lacks a safety vest while standing near moving vehicle access.</p></div></div>
            </div>
            <table class="summary-table">
                <tr><td class="summary-label">WHO</td><td class="summary-value">Report lists 2 persons; both have detector-confirmed PPE concerns.</td></tr>
                <tr><td class="summary-label">WHAT</td><td class="summary-value"><ul><li>Scene class: Front gate access control</li><li>Core violation: Missing mask and missing safety vest</li></ul></td></tr>
                <tr><td class="summary-label">DANGER</td><td class="summary-value"><ul><li>Respiratory exposure risk from dust or airborne contaminants</li><li>Struck-by risk due to reduced worker visibility near vehicles</li></ul></td></tr>
                <tr><td class="summary-label">LAW</td><td class="summary-value"><ul><li>USECHH 2000 / MS 2323:2010</li><li>JKR Standard Specification Section A</li></ul></td></tr>
            </table>
            <details class="person-card" open>
                <summary class="person-header"><div><h3>Person 1</h3><p>Worker nearest the gate entrance.</p></div></summary>
                <div class="person-content">
                    <div class="ppe-item"><span class="ppe-label">Mask</span><span class="ppe-status">Missing</span></div>
                    <div class="hazard-chip">Dust exposure at gate queue</div>
                    <div class="risk-item"><div class="risk-content">Respiratory exposure risk from dust while waiting near the driveway.</div><span class="likelihood-value">Medium</span><div class="risk-mitigation"><ul><li>Issue a suitable mask before the worker resumes the gate task.</li></ul></div></div>
                    <div class="action-chip">Verify mask replacement and record the correction.</div>
                </div>
            </details>
            <details class="person-card" open>
                <summary class="person-header"><div><h3>Person 2</h3><p>Worker beside the vehicle access lane.</p></div></summary>
                <div class="person-content">
                    <div class="ppe-item"><span class="ppe-label">Safety Vest</span><span class="ppe-status">Missing</span></div>
                    <div class="hazard-chip">Reduced visibility to approaching vehicles</div>
                    <div class="risk-item"><div class="risk-content">Struck-by risk because the worker is not highly visible to drivers.</div><span class="likelihood-value">High</span><div class="risk-mitigation"><ul><li>Move the worker away from the access lane until a high-visibility vest is worn.</li></ul></div></div>
                    <div class="action-chip">Confirm high-visibility vest use before reopening the lane.</div>
                </div>
            </details>
            <section class="section"><h2 class="section-title">Verified Safety Regulations & Standards</h2><article class="regulation-card"><div class="regulation-header">USECHH 2000 / MS 2323:2010</div><div class="regulation-body"><p>Respiratory PPE applies to airborne contaminant exposure.</p></div></article></section>
        </body></html>`;
    window.API = {{
        getImageUrl: () => '',
        getReportUrl: () => `data:text/html;charset=utf-8,${{encodeURIComponent(sampleReportHtml)}}`,
        getViolations: async () => [
            {{
                report_id: 'front-gate-001',
                timestamp: todayIso,
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


def _wait_for_idle_after(page, prompt: str) -> None:
    page.wait_for_function(
        "(prompt) => window.CASMAssistant.getActiveSession()?.context?.lastUserPrompt === prompt "
        "&& window.CASMAssistant.isResponding === false",
        arg=prompt,
        timeout=10000,
    )


def test_assistant_explains_likelihood_and_browses_report_risks():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(_build_page_html(), wait_until="domcontentloaded")
        page.wait_for_selector("#assistantTitle", state="attached")
        page.locator("#assistantLauncher").click()

        _submit_prompt(page, "what does likelihood mean in the report")
        page.get_by_text("Likelihood in a report means", exact=False).wait_for(timeout=10000)
        _wait_for_idle_after(page, "what does likelihood mean in the report")

        _submit_prompt(page, "i wanna know what is the main risks of each case")
        page.get_by_text("Report 1 of 2", exact=False).wait_for(timeout=10000)
        _wait_for_idle_after(page, "i wanna know what is the main risks of each case")
        assert "front-gate-001" in page.locator("#assistantMessages").inner_text()

        _submit_prompt(page, "what/how is the latest reports so far, can i have a look?")
        page.get_by_text("Report 1 of 2", exact=False).wait_for(timeout=10000)
        _wait_for_idle_after(page, "what/how is the latest reports so far, can i have a look?")

        _submit_prompt(page, "i want to see latest report")
        _wait_for_idle_after(page, "i want to see latest report")
        page.wait_for_function(
            "() => window.CASMAssistant.getReportReviewContext()?.reports?.length === 1 && "
            "window.CASMAssistant.getCurrentReportReview()?.report?.reportId === 'front-gate-001'",
            timeout=10000,
        )

        _submit_prompt(page, "i wanna see cloud reports")
        _wait_for_idle_after(page, "i wanna see cloud reports")
        page.wait_for_function(
            "() => window.CASMAssistant.getReportReviewContext()?.reports?.length === 1 && "
            "window.CASMAssistant.getCurrentReportReview()?.report?.reportId === 'front-gate-001'",
            timeout=10000,
        )

        _submit_prompt(page, "export cloud medium mask reports csv")
        page.get_by_text("Reports CSV is prepared", exact=False).wait_for(timeout=10000)
        page.locator(".assistant-action-btn", has_text="Download CSV").last.wait_for(timeout=10000)
        _wait_for_idle_after(page, "export cloud medium mask reports csv")
        export_preview = page.locator("#assistantMessages").inner_text()
        assert "front-gate-001" in export_preview
        assert "loading-bay-002" not in export_preview.split("export cloud medium mask reports csv")[-1]

        _submit_prompt(page, "i wanna check reports on front gate")
        _wait_for_idle_after(page, "i wanna check reports on front gate")
        page.wait_for_function(
            "() => window.CASMAssistant.getReportReviewContext()?.reports?.length === 1 && "
            "window.CASMAssistant.getCurrentReportReview()?.report?.reportId === 'front-gate-001'",
            timeout=10000,
        )

        page.locator(".assistant-action-btn", has_text="Explain this report").last.click()
        page.wait_for_function(
            "() => window.CASMAssistant.getActiveSession().messages.some((message) => "
            "String(message.text || '').includes('Here is a fuller read of report front-gate-001'))",
            timeout=10000,
        )
        explanation_text = page.locator("#assistantMessages").inner_text()
        assert "What happened:" in explanation_text
        assert "Recommended next step:" in explanation_text
        assert "Scene / Caption" in explanation_text
        assert "Person 2" in explanation_text
        assert "Mitigation Steps" in explanation_text

        _submit_prompt(page, "explain report today")
        _wait_for_idle_after(page, "explain report today")
        page.wait_for_function(
            "() => window.CASMAssistant.getActiveSession().messages.filter((message) => "
            "String(message.text || '').includes('Here is a fuller read of report front-gate-001')).length >= 2",
            timeout=10000,
        )
        today_explanation = page.locator("#assistantMessages").inner_text().split("explain report today")[-1]
        assert "Person 2" in today_explanation
        assert "Move the worker away from the access lane" in today_explanation

        _submit_prompt(page, "i wanna check reports on no-such-zone-999")
        page.get_by_text("I could not find report rows", exact=False).wait_for(timeout=10000)
        browser.close()


def test_assistant_shortcuts_preserve_user_prompt_and_reports_show_progress():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(_build_page_html(), wait_until="domcontentloaded")
        page.wait_for_selector("#assistantTitle", state="attached")
        page.locator("#assistantLauncher").click()

        page.get_by_role("button", name="Reports", exact=True).click()
        page.wait_for_function("() => window.CASMAssistant.isResponding === false", timeout=10000)
        shortcut_messages = page.evaluate(
            """
            () => window.CASMAssistant.getActiveSession().messages.map((message) => ({
                role: message.role,
                text: message.text
            }))
            """
        )
        assert any(message["role"] == "user" and message["text"] == "open reports" for message in shortcut_messages)
        assert any("I am opening it now" in message["text"] for message in shortcut_messages if message["role"] == "assistant")

        page.wait_for_timeout(250)
        if not page.locator("#assistantPanel").is_visible():
            page.locator("#assistantLauncher").click()
            page.locator("#assistantPanel").wait_for(state="visible", timeout=10000)

        page.evaluate(
            """
            () => {
                window.__resolveAssistantViolations = null;
                window.API.getViolations = () => new Promise((resolve) => {
                    window.__resolveAssistantViolations = () => resolve([
                        {
                            report_id: 'progress-report-001',
                            timestamp: new Date().toISOString(),
                            status: 'completed',
                            severity: 'HIGH',
                            device_id: 'progress-cam',
                            violation_count: 1,
                            missing_ppe: ['Hardhat'],
                            source_scope: 'cloud',
                            source_label: 'Cloud',
                            violation_summary: 'PPE Violation Detected: Missing Hardhat'
                        }
                    ]);
                });
            }
            """
        )
        _submit_prompt(page, "shows reports")
        page.get_by_text("Reading report rows", exact=False).wait_for(timeout=10000)
        assert page.evaluate("() => window.CASMAssistant.isResponding === true")
        user_prompts = page.evaluate(
            "window.CASMAssistant.getActiveSession().messages.filter((message) => message.role === 'user').map((message) => message.text)"
        )
        assert "shows reports" in user_prompts

        page.evaluate("window.__resolveAssistantViolations()")
        _wait_for_idle_after(page, "shows reports")
        page.get_by_text("Report 1 of 1", exact=False).wait_for(timeout=10000)
        assert "progress-report-001" in page.locator("#assistantMessages").inner_text()
        browser.close()


def test_assistant_revisited_report_controls_append_at_conversation_bottom():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(_build_page_html(), wait_until="domcontentloaded")
        page.wait_for_selector("#assistantTitle", state="attached")
        page.locator("#assistantLauncher").click()

        page.locator(".assistant-action-btn", has_text="Guided Reports").first.click()
        page.wait_for_function(
            "() => window.CASMAssistant.getActiveSession().messages.at(-1)?.guided?.kind === 'reports'",
            timeout=10000,
        )

        _submit_prompt(page, "i wanna know what is the main risks of each case")
        page.get_by_text("Report 1 of 2", exact=False).wait_for(timeout=10000)
        _wait_for_idle_after(page, "i wanna know what is the main risks of each case")

        page.locator(".assistant-action-btn", has_text="Explain this report").last.click()
        page.wait_for_function(
            "() => String(window.CASMAssistant.getActiveSession().messages.at(-1)?.text || '').includes('Here is a fuller read')",
            timeout=10000,
        )

        page.locator(".assistant-action-btn", has_text="Next report").last.click()
        page.wait_for_function(
            "() => window.CASMAssistant.getActiveSession().messages.at(-1)?.reportCarousel?.report?.reportId === 'loading-bay-002'",
            timeout=10000,
        )

        page.locator(".assistant-action-btn", has_text="Refine by clicking filters").last.click()
        page.wait_for_function(
            "() => window.CASMAssistant.getActiveSession().messages.at(-1)?.guided?.kind === 'reports'",
            timeout=10000,
        )
        last_text = page.evaluate("() => window.CASMAssistant.getActiveSession().messages.at(-1)?.text || ''")
        assert "Guided reports" in last_text
        browser.close()


def test_assistant_role_aliases_and_busy_guard_keep_chat_order_clear():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(_build_page_html(), wait_until="domcontentloaded")
        page.wait_for_selector("#assistantTitle", state="attached")
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
        user_box = page.locator(".assistant-message-user .assistant-bubble").last.bounding_box()
        messages_box = page.locator("#assistantMessages").bounding_box()
        assert user_box and messages_box
        assert user_box["x"] + user_box["width"] > messages_box["x"] + (messages_box["width"] * 0.62)

        page.evaluate("window.__busyJob = window.CASMAssistant.beginResponseFeedback('Finding matching reports...')")
        page.get_by_text("Finding matching reports", exact=False).wait_for(timeout=10000)
        page.wait_for_function("() => window.CASMAssistant.isResponding === true", timeout=10000)
        assert page.locator("#assistantInput").is_disabled()
        assert page.locator("#assistantSend").is_disabled()

        page.evaluate("void window.CASMAssistant.runSuggestedPrompt('export reports csv')")
        user_prompts = page.evaluate(
            "window.CASMAssistant.getActiveSession().messages.filter((message) => message.role === 'user').map((message) => message.text)"
        )
        assert "export reports csv" not in user_prompts
        page.evaluate("window.CASMAssistant.finishResponseFeedback(window.__busyJob)")
        page.wait_for_function("() => window.CASMAssistant.isResponding === false", timeout=10000)

        page.evaluate(
            """
            window.API.getViolations = async () => [
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
            ];
            """
        )
        _submit_prompt(page, "i wanna see cloud reports")
        page.get_by_text("Report 1 of 1", exact=False).wait_for(timeout=10000)
        _wait_for_idle_after(page, "i wanna see cloud reports")
        assert "cloud-delayed-001" in page.locator("#assistantMessages").inner_text()
        assert not page.locator("#assistantInput").is_disabled()
        browser.close()
