import os
import sys

import requests


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")


def main() -> int:
    app_js_url = f"{VERCEL_URL}/js/app.js"
    live_js_url = f"{VERCEL_URL}/js/pages/live.js"
    reports_js_url = f"{VERCEL_URL}/js/pages/reports.js"
    notifications_js_url = f"{VERCEL_URL}/js/notifications.js"
    index_url = f"{VERCEL_URL}/"

    app_js = requests.get(app_js_url, timeout=30)
    app_js.raise_for_status()
    live_js = requests.get(live_js_url, timeout=30)
    live_js.raise_for_status()
    reports_js = requests.get(reports_js_url, timeout=30)
    reports_js.raise_for_status()
    notifications_js = requests.get(notifications_js_url, timeout=30)
    notifications_js.raise_for_status()
    index_html = requests.get(index_url, timeout=30)
    index_html.raise_for_status()

    app_text = app_js.text
    live_text = live_js.text
    reports_text = reports_js.text
    notifications_text = notifications_js.text
    index_text = index_html.text

    required_app_markers = [
        "const strongPhoneSignal = mobileUA || uaDataMobile || phoneLikeScreen;",
        "const phoneHeuristic = (strongPhoneSignal || (mobileUA && narrowViewport)) && !iPadLike;",
        "function initializeNetworkIndicator()",
        "window.dispatchEvent(new CustomEvent('ppe-network:status'",
        "function initializeAdaptivePipelineModeManager()",
        "API.syncLocalCacheToSupabase({ limit: 180 });",
    ]
    required_index_markers = [
        "id=\"networkStatusBadge\"",
        "id=\"networkStatusText\"",
        "rel=\"manifest\"",
    ]
    required_live_markers = [
        "id=\"liveToolbarSettingsBtn\"",
        "toolbarSettingsClickHandler",
        "liveToolbarSettingsBtn.addEventListener('click'",
        "id=\"nlpProviderOrderSelect\"",
        "id=\"visionProviderOrderSelect\"",
        "id=\"embeddingProviderOrderSelect\"",
    ]
    required_reports_markers = [
        "focusReport(reportId, { openModal = false } = {})",
        "applyPendingFocusRequest()",
        "NotificationManager.reportGenerating(reportId",
        "onClickFn: () => this.focusReport(reportId, { openModal: true })",
    ]
    required_notifications_markers = [
        "onClickFn: () => {",
        "ReportsPage.focusReport(reportId, { openModal: true });",
    ]

    missing = []
    for marker in required_app_markers:
        if marker not in app_text:
            missing.append(f"app.js missing marker: {marker}")
    for marker in required_index_markers:
        if marker not in index_text:
            missing.append(f"index.html missing marker: {marker}")
    for marker in required_live_markers:
        if marker not in live_text:
            missing.append(f"live.js missing marker: {marker}")
    for marker in required_reports_markers:
        if marker not in reports_text:
            missing.append(f"reports.js missing marker: {marker}")
    for marker in required_notifications_markers:
        if marker not in notifications_text:
            missing.append(f"notifications.js missing marker: {marker}")

    if missing:
        print("FAIL: deployed frontend assets do not include required settings visibility fixes")
        for line in missing:
            print(f" - {line}")
        return 2

    print("PASS: deployed frontend assets include settings visibility fixes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
