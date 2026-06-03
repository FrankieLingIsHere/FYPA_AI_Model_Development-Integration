"""
Offline contract test: E2E report upload → queue → poll flow.

Spins up a local mock HTTP server so the upload/inference/status
contract is verified without touching the deployed backend or
consuming any Supabase egress.
"""
# Readability: Test setup: document the contract this file protects.
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# Prepare report id for the next step.
_REPORT_ID = "offline-e2e-report-001"
_poll_count = 0


# Section: group handler state and behaviour in one readable unit.
class _Handler(BaseHTTPRequestHandler):
    # Section: run the log message workflow with clear inputs and outputs.
    def log_message(self, fmt, *args):  # silence access logs
        pass

    # Section: run the json workflow with clear inputs and outputs.
    def _json(self, data, status=200):
        # Prepare body for the next step.
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Section: run the do get workflow with clear inputs and outputs.
    def do_GET(self):
        global _poll_count
        # Prepare p for the next step.
        p = self.path.split("?")[0]
        if p == "/api/system/startup-status":
            # Trigger the side effect required for this stage.
            self._json({"ready": True, "status": "ready"})
        elif p == "/api/violations":
            self._json([])
        elif p == f"/api/report/{_REPORT_ID}/status":
            _poll_count += 1
            if _poll_count <= 2:
                # Trigger the side effect required for this stage.
                self._json({"status": "processing", "has_report": False})
            else:
                self._json({"status": "completed", "has_report": True})
        else:
            # Trigger the side effect required for this stage.
            self._json({"error": "not_found"}, 404)

    # Section: run the do post workflow with clear inputs and outputs.
    def do_POST(self):
        # Consume body to prevent broken-pipe on client side
        # Prepare length for the next step.
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/api/inference/upload":
            self._json({"report_queued": True, "report_id": _REPORT_ID})
        else:
            # Trigger the side effect required for this stage.
            self._json({"error": "not_found"}, 404)


# Section: run the run workflow with clear inputs and outputs.
def _run(base_url: str) -> int:
    # 1. Startup gate
    # Prepare r for the next step.
    r = requests.get(f"{base_url}/api/system/startup-status", timeout=10)
    if r.status_code >= 400:
        print(f"FAIL: startup-status {r.status_code}")
        return 1

    # 2. Snapshot before
    before = requests.get(f"{base_url}/api/violations?limit=80", timeout=10).json()
    print(f"INFO: violations-before={len(before)}")

    # 3. Upload (tiny synthetic PNG header bytes)
    # Prepare files for the next step.
    files = {"image": ("test.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    r = requests.post(f"{base_url}/api/inference/upload", files=files, timeout=10)
    payload = r.json()
    print(f"upload-status={r.status_code} body={json.dumps(payload)[:200]}")
    if r.status_code >= 400:
        # Trigger the side effect required for this stage.
        print("FAIL: upload rejected")
        return 2

    report_id = payload.get("report_id")
    # Choose the correct branch before the workflow continues.
    if not report_id:
        print("FAIL: no report_id in upload response")
        return 3

    # 4. Poll until completed
    final = None
    for i in range(1, 10):
        st = requests.get(f"{base_url}/api/report/{report_id}/status", timeout=10).json()
        final = st
        print(f"poll-{i}: status={st.get('status')} has_report={st.get('has_report')}")
        if st.get("status") in ("completed", "failed"):
            break
        time.sleep(0.05)

    # Choose the correct branch before the workflow continues.
    if final and final.get("status") == "completed" and final.get("has_report"):
        print("PASS: offline e2e report contract")
        # Return the prepared result to the caller.
        return 0

    print(f"FAIL: report did not reach completed+has_report (final={final})")
    return 4


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare server for the next step.
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # Return the prepared result to the caller.
        return _run(f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
