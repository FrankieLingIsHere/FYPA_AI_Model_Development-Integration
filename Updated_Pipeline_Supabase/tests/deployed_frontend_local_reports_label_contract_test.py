# Readability: Test setup: document the contract this file protects.
import json
import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# Prepare vercel url for the next step.
VERCEL_URL = os.environ.get(
    "CASM_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")


# Section: run the find visible nav workflow with clear inputs and outputs.
def _find_visible_nav(page, nav_selector: str):
    # Prepare locator for the next step.
    locator = page.locator(nav_selector)
    for index in range(locator.count()):
        # Prepare candidate for the next step.
        candidate = locator.nth(index)
        if candidate.is_visible():
            # Return the prepared result to the caller.
            return candidate
    return None


# Section: run the wait for visible nav workflow with clear inputs and outputs.
def _wait_for_visible_nav(page, nav_selector: str, *, attempts: int = 10, pause_ms: int = 200):
    # Process each item in this collection using the same rule set.
    for _ in range(attempts):
        candidate = _find_visible_nav(page, nav_selector)
        # Choose the correct branch before the workflow continues.
        if candidate:
            return candidate
        page.wait_for_timeout(pause_ms)
    return None


# Section: run the ensure nav visible workflow with clear inputs and outputs.
def ensure_nav_visible(page, page_name: str):
    # Prepare nav selector for the next step.
    nav_selector = f"[data-page='{page_name}']"
    if page.locator(nav_selector).count() == 0:
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Navigation link not found in DOM for page={page_name}")

    if _wait_for_visible_nav(page, nav_selector):
        return

    for toggle_selector in ("#navToggle", "#navMoreToggle"):
        toggle = page.locator(toggle_selector)
        if toggle.count() > 0 and toggle.first.is_visible():
            # Trigger the side effect required for this stage.
            toggle.first.click()
            page.wait_for_timeout(220)
            if _wait_for_visible_nav(page, nav_selector, attempts=6, pause_ms=220):
                # Return the prepared result to the caller.
                return

    # Choose the correct branch before the workflow continues.
    if not _find_visible_nav(page, nav_selector):
        # Surface the failure with enough context for the caller.
        raise RuntimeError(f"Navigation link exists but is not visible for page={page_name}")


# Section: run the run label probe workflow with clear inputs and outputs.
def run_label_probe(page):
    return page.evaluate(
        """
        () => {
            if (typeof ReportsPage === 'undefined' || typeof ReportsPage.renderReports !== 'function') {
                throw new Error('ReportsPage is unavailable for label probe');
            }

            const originalViolations = Array.isArray(ReportsPage.violations)
                ? JSON.parse(JSON.stringify(ReportsPage.violations))
                : [];

            const fixtures = [
                {
                    report_id: 'ui-local-queued-001',
                    timestamp: new Date().toISOString(),
                    status: 'queued',
                    has_report: false,
                    has_original: true,
                    has_annotated: false,
                    severity: 'HIGH',
                    violation_count: 1,
                    missing_ppe: ['Hardhat'],
                    source_scope: 'local',
                    source_label: 'Local',
                    device_id: 'offline_local_cache'
                },
                {
                    report_id: 'ui-local-generating-001',
                    timestamp: new Date().toISOString(),
                    status: 'generating',
                    has_report: false,
                    has_original: true,
                    has_annotated: true,
                    severity: 'HIGH',
                    violation_count: 1,
                    missing_ppe: ['Vest'],
                    source_scope: 'local',
                    source_label: 'Local',
                    device_id: 'offline_local_cache'
                },
                {
                    report_id: 'ui-local-failed-001',
                    timestamp: new Date().toISOString(),
                    status: 'failed',
                    has_report: false,
                    has_original: true,
                    has_annotated: true,
                    severity: 'HIGH',
                    violation_count: 1,
                    missing_ppe: ['Gloves'],
                    source_scope: 'local',
                    source_label: 'Local',
                    device_id: 'offline_local_cache'
                },
                {
                    report_id: 'ui-local-ready-001',
                    timestamp: new Date().toISOString(),
                    status: 'completed',
                    has_report: true,
                    has_original: true,
                    has_annotated: true,
                    severity: 'MEDIUM',
                    violation_count: 1,
                    missing_ppe: ['Mask'],
                    source_scope: 'local',
                    source_label: 'Local',
                    device_id: 'offline_local_cache'
                }
            ];

            const expectedById = {
                'ui-local-queued-001': 'queued',
                'ui-local-generating-001': 'generating',
                'ui-local-failed-001': 'failed',
                'ui-local-ready-001': 'ready'
            };

            const normalize = (value) => String(value || '').trim().toLowerCase();

            try {
                ReportsPage.violations = fixtures;
                ReportsPage.renderReports();

                const checks = fixtures.map((fixture) => {
                    const reportId = String(fixture.report_id || '');
                    const expectedStatus = String(expectedById[reportId] || '');
                    const card = document.getElementById(`report-${reportId}`);

                    if (!card) {
                        return {
                            reportId,
                            expectedStatus,
                            exists: false,
                            sourceBadgeText: '',
                            statusBadgeText: '',
                            allBadges: [],
                            sourceOk: false,
                            statusOk: false,
                        };
                    }

                    const badgeTexts = Array.from(card.querySelectorAll('.badge'))
                        .map((el) => String(el.textContent || '').trim());

                    const sourceBadgeText = badgeTexts.find((text) => normalize(text).includes('local')) || '';
                    const statusBadgeText = badgeTexts.find((text) => normalize(text).includes(expectedStatus)) || '';

                    return {
                        reportId,
                        expectedStatus,
                        exists: true,
                        sourceBadgeText,
                        statusBadgeText,
                        allBadges: badgeTexts,
                        sourceOk: !!sourceBadgeText,
                        statusOk: !!statusBadgeText,
                    };
                });

                const pass = checks.every((row) => row.exists && row.sourceOk && row.statusOk);

                return {
                    pass,
                    checks,
                    cardCount: document.querySelectorAll('#reports-list .card').length,
                };
            } finally {
                ReportsPage.violations = originalViolations;
                ReportsPage.renderReports();
            }
        }
        """
    )


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Open the managed resource only for the block that needs it.
        with sync_playwright() as p:
            # Prepare browser for the next step.
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"{VERCEL_URL}/", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)
            page.wait_for_function(
                "() => !document.body.classList.contains('startup-loading')",
                timeout=120000,
            )
            # Trigger the side effect required for this stage.
            page.wait_for_function(
                "() => typeof ReportsPage !== 'undefined' && typeof API !== 'undefined'",
                timeout=30000,
            )

            ensure_nav_visible(page, "reports")
            page.click("[data-page='reports']")
            page.wait_for_selector("#reports-list", timeout=12000)

            # Prepare result for the next step.
            result = run_label_probe(page)

            summary = {
                "frontend": VERCEL_URL,
                "pass": bool(result.get("pass")),
                "cardCount": result.get("cardCount"),
                "checks": result.get("checks", []),
            }

            # Trigger the side effect required for this stage.
            print("PASS" if summary["pass"] else "FAIL")
            print(json.dumps(summary, indent=2, ensure_ascii=True))

            browser.close()
            return 0 if summary["pass"] else 2

    except PlaywrightTimeoutError as exc:
        # Trigger the side effect required for this stage.
        print(f"FAIL: timeout in local report label contract test: {exc}")
        return 40
    except Exception as exc:
        print(f"FAIL: local report label contract test unhandled error: {exc}")
        return 41


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    sys.exit(main())
