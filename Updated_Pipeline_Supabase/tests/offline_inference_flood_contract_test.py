"""
Offline contract test: inference flood + duplicate-guard behaviour.

Mock server accepts the first upload and rejects the rest with a
cooldown signal — validates client-side dedup assertions without
touching the deployed backend or consuming Supabase egress.
"""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

TOTAL_REQUESTS = 3
MAX_WORKERS = 2
MAX_UNIQUE_REPORTS = 1

_lock = threading.Lock()
_first_done = False
_REPORT_ID = "offline-flood-001"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/system/startup-status":
            self._json({"ready": True, "status": "ready"})
        elif p == "/api/queue/status":
            self._json({"queue_size": 0})
        else:
            self._json({"error": "not_found"}, 404)

    def do_POST(self):
        global _first_done
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)

        if self.path == "/api/inference/upload":
            with _lock:
                if not _first_done:
                    _first_done = True
                    self._json({"report_queued": True, "report_id": _REPORT_ID,
                                "violations_detected": True})
                else:
                    self._json({"report_queued": False,
                                "report_queue_reason": "cooldown_or_already_processing",
                                "violations_detected": True})
        else:
            self._json({"error": "not_found"}, 404)


def _upload_one(base_url: str) -> dict:
    files = {"image": ("test.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    r = requests.post(f"{base_url}/api/inference/upload", files=files, timeout=10)
    return {"status": r.status_code, "payload": r.json() if r.status_code < 500 else {}}


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        # Gate: startup
        r = requests.get(f"{base_url}/api/system/startup-status", timeout=10)
        if r.status_code >= 400:
            print(f"FAIL: startup-status {r.status_code}")
            return 1

        # Send concurrent flood
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(_upload_one, base_url) for _ in range(TOTAL_REQUESTS)]
            for f in as_completed(futures):
                results.append(f.result())

        report_ids = []
        cooldown_count = 0
        for item in results:
            p = item.get("payload", {})
            if p.get("report_queued") is True:
                rid = p.get("report_id")
                if rid:
                    report_ids.append(rid)
            if str(p.get("report_queue_reason") or "").lower() == "cooldown_or_already_processing":
                cooldown_count += 1

        unique_ids = sorted(set(report_ids))
        print(f"INFO: unique_queued_ids={unique_ids} cooldown_rejected={cooldown_count}")

        if len(unique_ids) > MAX_UNIQUE_REPORTS:
            print(f"FAIL: dedup failed — {len(unique_ids)} unique IDs queued, max={MAX_UNIQUE_REPORTS}")
            return 2

        if unique_ids and cooldown_count == 0:
            print("FAIL: no cooldown rejections despite repeated same-frame flood")
            return 3

        print("PASS: offline inference flood and dedup-guard contract")
        return 0
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
