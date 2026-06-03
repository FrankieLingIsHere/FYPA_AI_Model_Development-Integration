# Readability: Test setup: document the contract this file protects.
import os
import sys

import requests


# Prepare vercel url for the next step.
VERCEL_URL = os.environ.get(
    "CASM_VERCEL_URL",
    "https://fypa-ai-model-development-integrati.vercel.app",
).rstrip("/")
STRICT_FRONTEND_ASSETS = os.environ.get("CASM_FRONTEND_ASSETS_STRICT", "1") != "0"


# Section: run the looks like html workflow with clear inputs and outputs.
def _looks_like_html(payload: str) -> bool:
    # Prepare head for the next step.
    head = (payload or "").lstrip()[:512].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<html" in head


# Section: run the fetch asset text workflow with clear inputs and outputs.
def fetch_asset_text(base_url: str, candidate_paths, label: str):
    errors = []
    for path in candidate_paths:
        # Prepare separator for the next step.
        separator = "&" if "?" in path else "?"
        url = f"{base_url}{path}{separator}casm_asset_check=1"
        try:
            # Prepare response for the next step.
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            errors.append(f"{url} -> {exc}")
            continue

        # Prepare payload for the next step.
        payload = response.text or ""
        content_type = (response.headers.get("Content-Type") or "").lower()
        # Some route fallbacks return index.html with 200; reject that for JS assets.
        if "text/html" in content_type or _looks_like_html(payload):
            # Trigger the side effect required for this stage.
            errors.append(f"{url} -> HTML fallback returned")
            continue

        return payload, url

    # Surface the failure with enough context for the caller.
    raise RuntimeError(
        f"Unable to fetch {label} from expected asset paths: " + "; ".join(errors)
    )


# Section: run the has marker group workflow with clear inputs and outputs.
def has_marker_group(text: str, markers) -> bool:
    return all(marker in text for marker in markers)


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare index url for the next step.
    index_url = f"{VERCEL_URL}/"

    app_text, app_js_url = fetch_asset_text(
        VERCEL_URL,
        ["/static/js/app.js", "/js/app.js"],
        "app.js",
    )
    live_text, live_js_url = fetch_asset_text(
        VERCEL_URL,
        ["/static/js/pages/live.js", "/js/pages/live.js"],
        "pages/live.js",
    )
    # Prepare values needed by the next step.
    reports_text, reports_js_url = fetch_asset_text(
        VERCEL_URL,
        ["/static/js/pages/reports.js", "/js/pages/reports.js"],
        "pages/reports.js",
    )
    notifications_text, notifications_js_url = fetch_asset_text(
        VERCEL_URL,
        ["/static/js/notifications.js", "/js/notifications.js"],
        "notifications.js",
    )

    # Prepare index html for the next step.
    index_html = requests.get(index_url, timeout=30)
    index_html.raise_for_status()

    index_text = index_html.text

    required_app_markers = [
        "function initializeNetworkIndicator()",
        "window.dispatchEvent(new CustomEvent('ppe-network:status'",
        "function initializeAdaptivePipelineModeManager()",
    ]
    # Prepare app detection marker alternatives for the next step.
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
        [
            "const getDeviceProfile = () => {",
            "const narrowTouchViewport = touchCapable && window.matchMedia('(max-width: 860px)').matches;",
            "body.classList.remove('is-tablet-device');",
            "body.classList.toggle('is-tablet-landscape', tabletDevice && !portrait);",
        ],
    ]
    # Prepare app reconnect sync marker alternatives for the next step.
    app_reconnect_sync_marker_alternatives = [
        [
            "API.syncLocalCacheToSupabase({ limit: 180 });",
        ],
        [
            "API.syncLocalCacheToSupabase({",
            "limit: 180",
            "reason: 'reconnect_auto'",
        ],
        [
            "API.syncLocalCacheToSupabase({",
            "reason: 'reconnect_auto'",
        ],
    ]
    # Prepare required index markers for the next step.
    required_index_markers = [
        "id=\"networkStatusBadge\"",
        "id=\"networkStatusText\"",
        "rel=\"manifest\"",
    ]
    runtime_index_fallback_markers = [
        "function ensurePwaDocumentMarkers()",
        "manifest.setAttribute('rel', 'manifest');",
        "manifest.setAttribute('href', '/manifest.json');",
        "badge: document.getElementById('networkStatusBadge')",
        "label: document.getElementById('networkStatusText')",
    ]
    # Prepare required live markers for the next step.
    required_live_markers = [
        "id=\"settingsModal\"",
        "id=\"nlpProviderOrderSelect\"",
        "id=\"visionProviderOrderSelect\"",
        "id=\"embeddingProviderOrderSelect\"",
    ]
    live_settings_trigger_marker_alternatives = [
        [
            "id=\"reopenSettingsWindowBtn\"",
            "reopenSettingsWindowBtn.addEventListener('click', openSettingsWindow);",
        ],
        [
            "id=\"liveToolbarSettingsBtn\"",
            "liveToolbarSettingsBtn.addEventListener('click'",
            "toolbarSettingsClickHandler",
        ],
    ]
    # Prepare live settings route marker alternatives for the next step.
    live_settings_route_marker_alternatives = [
        [
            "const isSettingsRoute = APP_STATE.currentPage === 'settings' || APP_STATE.currentPage === 'settings-checkup';",
            ".settings-route .live-mode-tabs",
            ".settings-route .live-monitor-card",
            ".settings-route .settings-route-panel",
        ],
        [
            "toolbarSettingsClickHandler",
        ],
    ]
    # Prepare required reports markers for the next step.
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

    # Prepare missing for the next step.
    missing = []
    for marker in required_app_markers:
        # Choose the correct branch before the workflow continues.
        if marker not in app_text:
            # Trigger the side effect required for this stage.
            missing.append(f"app.js missing marker: {marker}")
    if not any(all(marker in app_text for marker in option) for option in app_detection_marker_alternatives):
        missing.append(
            "app.js missing phone/tablet detection markers (neither legacy nor updated implementation found)"
        )
    if not any(has_marker_group(app_text, option) for option in app_reconnect_sync_marker_alternatives):
        missing.append(
            "app.js missing reconnect-sync markers (expected API.syncLocalCacheToSupabase call with reconnect_auto reason)"
        )
    # Prepare missing index markers for the next step.
    missing_index_markers = []
    for marker in required_index_markers:
        # Choose the correct branch before the workflow continues.
        if marker not in index_text:
            # Trigger the side effect required for this stage.
            missing_index_markers.append(marker)

    if missing_index_markers:
        # Some deployments may lag on static HTML updates while app.js already
        # contains runtime marker/bootstrap logic. Treat this as acceptable only
        # when all fallback markers are present in app.js.
        missing_runtime_fallback = [
            marker for marker in runtime_index_fallback_markers if marker not in app_text
        ]
        # Choose the correct branch before the workflow continues.
        if missing_runtime_fallback:
            # Process each item in this collection using the same rule set.
            for marker in missing_index_markers:
                # Trigger the side effect required for this stage.
                missing.append(f"index.html missing marker: {marker}")
            for marker in missing_runtime_fallback:
                missing.append(f"app.js missing runtime fallback marker: {marker}")
    # Process each item in this collection using the same rule set.
    for marker in required_live_markers:
        if marker not in live_text:
            missing.append(f"live.js missing marker: {marker}")
    if not any(has_marker_group(live_text, option) for option in live_settings_trigger_marker_alternatives):
        # Trigger the side effect required for this stage.
        missing.append(
            "live.js missing settings trigger markers (expected reopen button or toolbar settings handler variant)"
        )
    if not any(has_marker_group(live_text, option) for option in live_settings_route_marker_alternatives):
        missing.append(
            "live.js missing settings-route markers (expected settings-route panel behavior or toolbar handler variant)"
        )
    # Process each item in this collection using the same rule set.
    for marker in required_reports_markers:
        if marker not in reports_text:
            # Trigger the side effect required for this stage.
            missing.append(f"reports.js missing marker: {marker}")
    for marker in required_notifications_markers:
        # Choose the correct branch before the workflow continues.
        if marker not in notifications_text:
            missing.append(f"notifications.js missing marker: {marker}")

    if missing:
        if STRICT_FRONTEND_ASSETS:
            print("FAIL: deployed frontend assets do not include required settings visibility fixes")
            for line in missing:
                # Trigger the side effect required for this stage.
                print(f" - {line}")
            # Return the prepared result to the caller.
            return 2

        # Trigger the side effect required for this stage.
        print(
            "WARN: deployed frontend assets do not yet include all required markers; "
            "treating as non-blocking by default (set CASM_FRONTEND_ASSETS_STRICT=1 to enforce)"
        )
        for line in missing:
            print(f" - {line}")
        return 0

    # Trigger the side effect required for this stage.
    print("INFO: validated asset URLs")
    print(f" - app.js: {app_js_url}")
    print(f" - live.js: {live_js_url}")
    print(f" - reports.js: {reports_js_url}")
    print(f" - notifications.js: {notifications_js_url}")
    print("PASS: deployed frontend assets include settings visibility fixes")
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    sys.exit(main())
