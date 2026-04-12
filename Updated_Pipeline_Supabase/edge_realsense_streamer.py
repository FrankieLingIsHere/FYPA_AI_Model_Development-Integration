"""
Edge RealSense relay streamer.

Captures frames from a local Intel RealSense camera and uploads them to a hosted
LUNA backend so deployment mode can consume local hardware as a live source.
"""

import argparse
import json
import signal
import sys
import time
from typing import Dict, Optional

import cv2
import requests

from pipeline.backend.core.realsense_source import RealSenseSource


def _normalize_base_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("backend URL is required")
    return text.rstrip("/")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream local RealSense to deployed backend")
    parser.add_argument(
        "--backend-url",
        default="https://fypaaimodeldevelopment-integration-production.up.railway.app",
        help="Backend base URL (Railway host)",
    )
    parser.add_argument(
        "--endpoint",
        default="/api/live/edge/realsense/frame",
        help="Edge ingest endpoint path",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Optional X-Edge-Token header value",
    )
    parser.add_argument("--width", type=int, default=640, help="Capture width")
    parser.add_argument("--height", type=int, default=480, help="Capture height")
    parser.add_argument("--camera-fps", type=int, default=60, help="RealSense stream FPS")
    parser.add_argument("--upload-fps", type=float, default=12.0, help="Upload FPS target")
    parser.add_argument("--jpeg-quality", type=int, default=70, help="Uploaded color JPEG quality")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (not recommended)",
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=5.0,
        help="Seconds between console status updates",
    )
    return parser.parse_args()


def _build_headers(token: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if token:
        headers["X-Edge-Token"] = token
    return headers


def _encode_color_frame(frame, jpeg_quality: int) -> Optional[bytes]:
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, int(max(40, min(95, jpeg_quality)))],
    )
    if not ok:
        return None
    return encoded.tobytes()


def main() -> int:
    args = _parse_args()
    base_url = _normalize_base_url(args.backend_url)
    endpoint_path = "/" + str(args.endpoint or "").lstrip("/")
    ingest_url = f"{base_url}{endpoint_path}"

    print("=" * 72)
    print("LUNA Edge RealSense Relay")
    print("=" * 72)
    print(f"Backend ingest URL : {ingest_url}")
    print(f"Capture profile    : {args.width}x{args.height} @ {args.camera_fps}fps")
    print(f"Upload profile     : {args.upload_fps:.1f} fps, JPEG q={args.jpeg_quality}")
    print("Press Ctrl+C to stop")
    print("=" * 72)

    source = RealSenseSource(width=args.width, height=args.height, fps=args.camera_fps)
    started, error_message = source.start()
    if not started:
        print(f"ERROR: failed to start RealSense source: {error_message}")
        return 1

    print(f"RealSense started: {source.device_name or 'Intel RealSense'}")

    running = True

    def _handle_signal(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    session = requests.Session()
    headers = _build_headers(args.token)
    verify_tls = not bool(args.insecure)

    send_interval = 1.0 / max(1.0, float(args.upload_fps))
    next_send_at = 0.0
    last_status_at = 0.0
    sent_count = 0
    error_count = 0

    try:
        while running:
            ok, frame, read_error = source.read()
            if not ok or frame is None:
                error_count += 1
                if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                    print(f"WARN: read failed: {read_error or 'unknown'}")
                    last_status_at = time.monotonic()
                time.sleep(0.03)
                continue

            now = time.monotonic()
            if now < next_send_at:
                time.sleep(min(0.01, next_send_at - now))
                continue

            color_jpeg = _encode_color_frame(frame, args.jpeg_quality)
            if not color_jpeg:
                error_count += 1
                continue

            depth_telemetry = source.get_depth_telemetry()
            depth_preview = source.get_depth_preview_jpeg()
            capabilities = source.get_capabilities()

            files = {
                "frame": ("frame.jpg", color_jpeg, "image/jpeg"),
            }
            if depth_preview:
                files["depth_preview"] = ("depth_preview.jpg", depth_preview, "image/jpeg")

            payload = {
                "device_name": source.device_name or "Intel RealSense (Edge Relay)",
                "depth_telemetry": json.dumps(depth_telemetry),
                "capabilities": json.dumps(capabilities),
            }

            try:
                response = session.post(
                    ingest_url,
                    data=payload,
                    files=files,
                    headers=headers,
                    timeout=(3.0, 10.0),
                    verify=verify_tls,
                )

                if response.status_code >= 300:
                    error_count += 1
                    if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                        preview = response.text[:220].replace("\n", " ")
                        print(f"WARN: ingest failed ({response.status_code}): {preview}")
                        last_status_at = time.monotonic()
                else:
                    sent_count += 1
                    if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                        depth_center = depth_telemetry.get("center_distance_m")
                        depth_info = f"center={depth_center}m" if depth_center is not None else "center=unknown"
                        print(f"OK: sent={sent_count}, errors={error_count}, {depth_info}")
                        last_status_at = time.monotonic()

            except Exception as exc:
                error_count += 1
                if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                    print(f"WARN: upload exception: {exc}")
                    last_status_at = time.monotonic()

            next_send_at = time.monotonic() + send_interval

    finally:
        try:
            source.stop()
        except Exception:
            pass

    print(f"Stopped edge relay. Sent={sent_count}, errors={error_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
