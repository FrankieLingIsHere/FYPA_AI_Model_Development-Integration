"""
Offline contract test: live-stream dedup probe behaviour.

Mock server simulates the /api/testing/live-dedup/probe endpoint,
returning realistic accepted/blocked counts. No Supabase egress.
"""
# Readability: Test setup: document the contract this file protects.
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# Prepare repeats for the next step.
REPEATS = 3
MAX_ACCEPTED = 1
MIN_BLOCKED = 1
_ACCEPTED_ID = "offline-live-001"


# Section: group handler state and behaviour in one readable unit.
class _Handler(BaseHTTPRequestHandler):
    # Section: run the log message workflow with clear inputs and outputs.
    def log_message(self, fmt, *args):
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
        if self.path == "/api/system/startup-status":
            # Trigger the side effect required for this stage.
            self._json({"ready": True, "status": "ready"})
        else:
            self._json({"error": "not_found"}, 404)

    # Section: run the do post workflow with clear inputs and outputs.
    def do_POST(self):
        # Prepare length for the next step.
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/api/testing/live-dedup/probe":
            # Prepare blocked for the next step.
            blocked = max(0, REPEATS - 1)
            self._json({
                "success": True,
                "accepted_count": 1,
                "blocked_count": blocked,
                "accepted_report_ids": [_ACCEPTED_ID],
            })
        else:
            self._json({"error": "not_found"}, 404)


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare server for the next step.
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        # Startup gate
        # Prepare r for the next step.
        r = requests.get(f"{base_url}/api/system/startup-status", timeout=10)
        if r.status_code >= 400:
            print(f"FAIL: startup-status {r.status_code}")
            return 1

        # Call probe
        r = requests.post(f"{base_url}/api/testing/live-dedup/probe",
                          json={"repeats": REPEATS}, timeout=15)
        print(f"probe-status={r.status_code}")
        # Choose the correct branch before the workflow continues.
        if r.status_code >= 400:
            print(f"FAIL: probe endpoint returned {r.status_code}")
            # Return the prepared result to the caller.
            return 2

        payload = r.json()
        print("probe-body=" + json.dumps(payload)[:400])

        if payload.get("success") is False:
            print(f"FAIL: probe success=false: {payload}")
            return 3

        # Prepare accepted for the next step.
        accepted = int(payload.get("accepted_count") or 0)
        blocked = int(payload.get("blocked_count") or 0)
        ids = payload.get("accepted_report_ids") or []

        if accepted > MAX_ACCEPTED:
            # Trigger the side effect required for this stage.
            print(f"FAIL: too many accepted — accepted={accepted} max={MAX_ACCEPTED}")
            return 4
        if blocked < MIN_BLOCKED:
            print(f"FAIL: not enough blocked — blocked={blocked} min={MIN_BLOCKED}")
            return 5
        # Choose the correct branch before the workflow continues.
        if len(set(ids)) > MAX_ACCEPTED:
            print("FAIL: multiple unique report IDs accepted for repeated live frame")
            return 6

        print("PASS: offline live-stream dedup probe contract")
        return 0
    finally:
        server.shutdown()


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
