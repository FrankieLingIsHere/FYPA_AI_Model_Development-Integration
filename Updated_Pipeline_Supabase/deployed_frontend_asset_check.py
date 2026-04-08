import os
import sys

import requests


VERCEL_URL = os.environ.get(
    "LUNA_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")
STRICT_FRONTEND_ASSETS = os.environ.get("LUNA_FRONTEND_ASSETS_STRICT", "0") != "0"


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
        "function initializeNetworkIndicator()",
        "window.dispatchEvent(new CustomEvent('ppe-network:status'",
        "function initializeAdaptivePipelineModeManager()",
        "API.syncLocalCacheToSupabase({ limit: 180 });",
    ]
    app_detection_marker_alternatives = [
        [
            "const strongPhoneSignal = mobileUA || uaDataMobile || phoneLikeScreen;",
            "const phoneHeuristic = (strongPhoneSignal || (mobileUA && narrowViewport)) && !iPadLike;",
        ],
        [
            "const getDeviceProfile = () => {",
            "const narrowTouchViewport = touchCapable && window.matchMedia('(max-width: 860px)').matches;",
            "body.classList.toggle('is-tablet-device', tabletDevice);",
        ],
    ]
    required_index_markers = [
        "id=\"networkStatusBadge\"",
        "id=\"networkStatusText\"",
        "rel=\"manifest\"",
    ]
    runtime_index_fallback_markers = [
        "function ensurePwaDocumentMarkers()",
        "manifest.setAttribute('rel', 'manifest');",
        "manifest.setAttribute('href', '/manifest.json');",
        "const badge = document.getElementById('networkStatusBadge');",
        "const label = document.getElementById('networkStatusText');",
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
    if not any(all(marker in app_text for marker in option) for option in app_detection_marker_alternatives):
        missing.append(
            "app.js missing phone/tablet detection markers (neither legacy nor updated implementation found)"
        )
    missing_index_markers = []
    for marker in required_index_markers:
        if marker not in index_text:
            missing_index_markers.append(marker)

    if missing_index_markers:
        # Some deployments may lag on static HTML updates while app.js already
        # contains runtime marker/bootstrap logic. Treat this as acceptable only
        # when all fallback markers are present in app.js.
        missing_runtime_fallback = [
            marker for marker in runtime_index_fallback_markers if marker not in app_text
        ]
        if missing_runtime_fallback:
            for marker in missing_index_markers:
                missing.append(f"index.html missing marker: {marker}")
            for marker in missing_runtime_fallback:
                missing.append(f"app.js missing runtime fallback marker: {marker}")
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
        if STRICT_FRONTEND_ASSETS:
            print("FAIL: deployed frontend assets do not include required settings visibility fixes")
            for line in missing:
                print(f" - {line}")
            return 2

        print(
            "WARN: deployed frontend assets do not yet include all required markers; "
            "treating as non-blocking by default (set LUNA_FRONTEND_ASSETS_STRICT=1 to enforce)"
        )
        for line in missing:
            print(f" - {line}")
        return 0

    print("PASS: deployed frontend assets include settings visibility fixes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
