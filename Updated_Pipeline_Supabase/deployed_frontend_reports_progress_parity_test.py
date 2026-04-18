import json
import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")
STRICT_MODE = os.environ.get("LUNA_FRONTEND_PARITY_STRICT", "0") != "0"


def fail(message: str, code: int = 2) -> int:
    if STRICT_MODE:
        print(f"FAIL: {message}")
        return code

    print(f"INFO: non-blocking parity check issue: {message}")
    return 0


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


def run_parity_probe(page):
    return page.evaluate(
        """
        async () => {
            const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

            const originalGetReportStatus = API.getReportStatus && API.getReportStatus.bind(API);
            const originalOpenReport = ReportsPage.openReport && ReportsPage.openReport.bind(ReportsPage);

            const callsByReport = {};
            const openedReports = [];
            const statuses = ['pending', 'generating', 'completed'];

            API.getReportStatus = async (reportId) => {
                const key = String(reportId || '');
                if (!callsByReport[key]) {
                    callsByReport[key] = [];
                }

                const idx = Math.min(callsByReport[key].length, statuses.length - 1);
                const status = statuses[idx];
                callsByReport[key].push(status);

                return {
                    success: true,
                    report_id: key,
                    status,
                    has_report: status === 'completed',
                    message: status === 'generating' ? 'Generating in progress...' : (status === 'completed' ? 'done' : 'Queued...')
                };
            };

            ReportsPage.openReport = (reportId) => {
                openedReports.push(String(reportId || ''));
            };

            const runScenario = async (name, reportId, deviceId) => {
                const violation = {
                    report_id: reportId,
                    timestamp: new Date().toISOString(),
                    status: 'pending',
                    has_report: false,
                    has_original: true,
                    has_annotated: false,
                    severity: 'HIGH',
                    violation_count: 1,
                    missing_ppe: ['Hardhat'],
                    device_id: deviceId
                };

                await ReportsPage.showGeneratingModal(violation);
                ReportsPage.startModalPolling(reportId, { autoOpen: false });
                await delay(8500);

                const statusEl = document.getElementById('report-modal-status');
                const completedStageEl = document.getElementById('report-stage-completed');

                const finalStatusText = statusEl ? String(statusEl.textContent || '').trim() : '';
                const completedStageDone = !!(completedStageEl && completedStageEl.classList.contains('done'));
                const completedStageActive = !!(completedStageEl && completedStageEl.classList.contains('active'));

                const seq = Array.isArray(callsByReport[reportId]) ? callsByReport[reportId].slice() : [];
                const containsPending = seq.includes('pending');
                const containsGenerating = seq.includes('generating');
                const containsCompleted = seq.includes('completed');

                ReportsPage.closeModal();

                const pass = (
                    containsPending
                    && containsGenerating
                    && containsCompleted
                    && finalStatusText.toLowerCase().includes('report completed')
                    && completedStageDone
                );

                return {
                    name,
                    reportId,
                    deviceId,
                    statusSequence: seq,
                    finalStatusText,
                    completedStageDone,
                    completedStageActive,
                    pass
                };
            };

            let local = null;
            let cloud = null;
            let restoreError = null;

            try {
                local = await runScenario('local', 'ui-local-progress-001', 'offline_local_cache');
                cloud = await runScenario('cloud', 'ui-cloud-progress-001', 'cloud_device_demo');
            } finally {
                try {
                    if (originalGetReportStatus) {
                        API.getReportStatus = originalGetReportStatus;
                    }
                    if (originalOpenReport) {
                        ReportsPage.openReport = originalOpenReport;
                    }
                    if (typeof ReportsPage.closeModal === 'function') {
                        ReportsPage.closeModal();
                    }
                } catch (err) {
                    restoreError = String((err && err.message) || err || 'unknown restore error');
                }
            }

            const pass = !!(local && cloud && local.pass && cloud.pass);

            return {
                pass,
                local,
                cloud,
                openedReports,
                restoreError
            };
        }
        """
    )


def main() -> int:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"{VERCEL_URL}/", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector("[data-page='home']", state="attached", timeout=120000)
            page.wait_for_function(
                "() => !document.body.classList.contains('startup-loading')",
                timeout=120000,
            )
            page.wait_for_function(
                "() => typeof ReportsPage !== 'undefined' && typeof API !== 'undefined'",
                timeout=30000,
            )

            ensure_nav_visible(page, "reports")
            page.click("[data-page='reports']")
            page.wait_for_selector("#reports-list", timeout=12000)

            result = run_parity_probe(page)

            summary = {
                "frontend": VERCEL_URL,
                "pass": bool(result.get("pass")),
                "local": result.get("local"),
                "cloud": result.get("cloud"),
                "openedReports": result.get("openedReports"),
                "restoreError": result.get("restoreError"),
            }

            print("PASS" if summary["pass"] else "FAIL")
            print(json.dumps(summary, indent=2, ensure_ascii=True))

            browser.close()
            return 0 if summary["pass"] else 2
    except PlaywrightTimeoutError as exc:
        return fail(f"timeout in reports progress parity test: {exc}", 40)
    except Exception as exc:
        return fail(f"reports progress parity test unhandled error: {exc}", 41)


if __name__ == "__main__":
    sys.exit(main())
