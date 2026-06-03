"""
Offline contract test: generate-now progression smoke.

Mock server returns a violations list, accepts a generate-now call,
and simulates status progressing to 'completed'. No Supabase egress.
"""
# Readability: Test setup: document the contract this file protects.
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# Prepare report id for the next step.
_REPORT_ID = "offline-gen-now-001"
_poll_count = 0


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
        global _poll_count
        # Prepare p for the next step.
        p = self.path.split("?")[0]
        if p == "/api/violations":
            # Trigger the side effect required for this stage.
            self._json([{"report_id": _REPORT_ID, "created_at": "2026-01-01T00:00:00Z"}])
        elif p == f"/api/report/{_REPORT_ID}/status":
            _poll_count += 1
            if _poll_count <= 2:
                # Trigger the side effect required for this stage.
                self._json({"status": "processing", "has_report": False,
                            "message": "Generating report..."})
            else:
                self._json({"status": "completed", "has_report": True,
                            "message": "Done"})
        else:
            # Trigger the side effect required for this stage.
            self._json({"error": "not_found"}, 404)

    # Section: run the do post workflow with clear inputs and outputs.
    def do_POST(self):
        # Prepare length for the next step.
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        if self.path == f"/api/report/{_REPORT_ID}/generate-now":
            self._json({"success": True, "status": "queued",
                        "message": "Report queued for generation"})
        else:
            # Trigger the side effect required for this stage.
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
        # 1. List violations
        # Prepare r for the next step.
        r = requests.get(f"{base_url}/api/violations?limit=60", timeout=10)
        violations = r.json() if isinstance(r.json(), list) else []
        if not violations:
            # Trigger the side effect required for this stage.
            print("FAIL: no violations returned by mock")
            return 1

        report_id = violations[0].get("report_id")
        print(f"INFO: candidate-report-id={report_id}")

        # 2. Trigger generate-now
        # Prepare r for the next step.
        r = requests.post(f"{base_url}/api/report/{report_id}/generate-now",
                          json={"force": False}, timeout=10)
        gn_payload = r.json()
        print(f"generate-now-status={r.status_code} body={json.dumps(gn_payload)[:200]}")
        if r.status_code >= 400:
            # Trigger the side effect required for this stage.
            print("FAIL: generate-now rejected")
            return 2

        # 3. Poll status
        # Prepare statuses for the next step.
        statuses = []
        for i in range(1, 8):
            st = requests.get(f"{base_url}/api/report/{report_id}/status", timeout=10).json()
            status = str(st.get("status") or "unknown").lower()
            statuses.append(status)
            # Trigger the side effect required for this stage.
            print(f"poll-{i}: status={status} has_report={st.get('has_report')} "
                  f"msg={st.get('message')}")
            if status in ("completed", "failed"):
                break
            time.sleep(0.05)

        # Choose the correct branch before the workflow continues.
        if all(s in ("pending", "queued") for s in statuses):
            print("FAIL: report remained queued/pending for entire smoke window")
            return 3

        print("PASS: offline generate-now progression contract")
        return 0
    finally:
        server.shutdown()


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
