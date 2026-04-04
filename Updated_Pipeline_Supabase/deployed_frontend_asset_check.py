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

    app_js = requests.get(app_js_url, timeout=30)
    app_js.raise_for_status()
    live_js = requests.get(live_js_url, timeout=30)
    live_js.raise_for_status()

    app_text = app_js.text
    live_text = live_js.text

    required_app_markers = [
        "const strongPhoneSignal = mobileUA || uaDataMobile || phoneLikeScreen;",
        "const phoneHeuristic = (strongPhoneSignal || (mobileUA && narrowViewport)) && !iPadLike;",
    ]
    required_live_markers = [
        "id=\"liveInlineSettingsBtn\"",
        "inlineSettingsClickHandler",
        "liveInlineSettingsBtn.addEventListener('click'",
    ]

    missing = []
    for marker in required_app_markers:
        if marker not in app_text:
            missing.append(f"app.js missing marker: {marker}")
    for marker in required_live_markers:
        if marker not in live_text:
            missing.append(f"live.js missing marker: {marker}")

    if missing:
        print("FAIL: deployed frontend assets do not include required settings visibility fixes")
        for line in missing:
            print(f" - {line}")
        return 2

    print("PASS: deployed frontend assets include settings visibility fixes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
