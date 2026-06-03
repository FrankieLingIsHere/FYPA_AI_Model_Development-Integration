"""
Edge RealSense relay streamer.

Captures frames from a local Intel RealSense camera and uploads them to a CASM
backend so local or deployed mode can consume RealSense as a live source.
"""
# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.

import argparse
import json
import os
import signal
import sys
import time
from typing import Dict, Optional

import cv2
import requests

from pipeline.backend.core.realsense_source import RealSenseSource


# Section: run the normalize base url workflow with clear inputs and outputs.
def _normalize_base_url(value: str) -> str:
    # Prepare text for the next step.
    text = str(value or "").strip()
    if not text:
        # Surface the failure with enough context for the caller.
        raise ValueError("backend URL is required")
    return text.rstrip("/")


# Section: run the parse args workflow with clear inputs and outputs.
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream local RealSense to a CASM backend")
    parser.add_argument(
        "--backend-url",
        default=(
            os.getenv("EDGE_REALSENSE_BACKEND_URL")
            or os.getenv("CASM_EDGE_REALSENSE_BACKEND_URL")
            or "http://127.0.0.1:5000"
        ),
        help="Backend base URL (local backend or Railway host)",
    )
    # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
    parser.add_argument(
        "--status-interval",
        type=float,
        default=5.0,
        help="Seconds between console status updates",
    )
    return parser.parse_args()


# Section: run the build headers workflow with clear inputs and outputs.
def _build_headers(token: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    # Choose the correct branch before the workflow continues.
    if token:
        # Prepare values needed by the next step.
        headers["X-Edge-Token"] = token
    return headers


# Section: run the encode color frame workflow with clear inputs and outputs.
def _encode_color_frame(frame, jpeg_quality: int) -> Optional[bytes]:
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, int(max(40, min(95, jpeg_quality)))],
    )
    # Choose the correct branch before the workflow continues.
    if not ok:
        # Return the prepared result to the caller.
        return None
    return encoded.tobytes()


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    args = _parse_args()
    base_url = _normalize_base_url(args.backend_url)
    endpoint_path = "/" + str(args.endpoint or "").lstrip("/")
    # Prepare ingest url for the next step.
    ingest_url = f"{base_url}{endpoint_path}"

    print("=" * 72)
    print("CASM Edge RealSense Relay")
    print("=" * 72)
    print(f"Backend ingest URL : {ingest_url}")
    print(f"Capture profile    : {args.width}x{args.height} @ {args.camera_fps}fps")
    print(f"Upload profile     : {args.upload_fps:.1f} fps, JPEG q={args.jpeg_quality}")
    print("Press Ctrl+C to stop")
    # Trigger the side effect required for this stage.
    print("=" * 72)

    source = RealSenseSource(width=args.width, height=args.height, fps=args.camera_fps)
    started, error_message = source.start()
    if not started:
        # Trigger the side effect required for this stage.
        print(f"ERROR: failed to start RealSense source: {error_message}")
        return 1

    print(f"RealSense started: {source.device_name or 'Intel RealSense'}")

    # Prepare running for the next step.
    running = True

    # Section: run the handle signal workflow with clear inputs and outputs.
    def _handle_signal(_signum, _frame):
        nonlocal running
        # Prepare running for the next step.
        running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    session = requests.Session()
    headers = _build_headers(args.token)
    # Prepare verify tls for the next step.
    verify_tls = not bool(args.insecure)

    send_interval = 1.0 / max(1.0, float(args.upload_fps))
    next_send_at = 0.0
    last_status_at = 0.0
    sent_count = 0
    error_count = 0

    try:
        # Keep the loop active only while the runtime condition is true.
        while running:
            # Prepare values needed by the next step.
            ok, frame, read_error = source.read()
            if not ok or frame is None:
                error_count += 1
                # Choose the correct branch before the workflow continues.
                if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                    # Trigger the side effect required for this stage.
                    print(f"WARN: read failed: {read_error or 'unknown'}")
                    last_status_at = time.monotonic()
                time.sleep(0.03)
                continue

            # Prepare now for the next step.
            now = time.monotonic()
            if now < next_send_at:
                time.sleep(min(0.01, next_send_at - now))
                continue

            color_jpeg = _encode_color_frame(frame, args.jpeg_quality)
            if not color_jpeg:
                error_count += 1
                continue

            # Prepare depth telemetry for the next step.
            depth_telemetry = source.get_depth_telemetry()
            depth_preview = source.get_depth_preview_jpeg()
            capabilities = source.get_capabilities()

            files = {
                "frame": ("frame.jpg", color_jpeg, "image/jpeg"),
            }
            if depth_preview:
                # Prepare values needed by the next step.
                files["depth_preview"] = ("depth_preview.jpg", depth_preview, "image/jpeg")

            # Prepare payload for the next step.
            payload = {
                "device_name": source.device_name or "Intel RealSense (Edge Relay)",
                "depth_telemetry": json.dumps(depth_telemetry),
                "capabilities": json.dumps(capabilities),
            }

            try:
                # Prepare response for the next step.
                response = session.post(
                    ingest_url,
                    data=payload,
                    files=files,
                    headers=headers,
                    timeout=(3.0, 10.0),
                    verify=verify_tls,
                )

                # Choose the correct branch before the workflow continues.
                if response.status_code >= 300:
                    error_count += 1
                    # Choose the correct branch before the workflow continues.
                    if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                        # Prepare preview for the next step.
                        preview = response.text[:220].replace("\n", " ")
                        print(f"WARN: ingest failed ({response.status_code}): {preview}")
                        last_status_at = time.monotonic()
                else:
                    sent_count += 1
                    if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                        depth_center = depth_telemetry.get("center_distance_m")
                        depth_info = f"center={depth_center}m" if depth_center is not None else "center=unknown"
                        print(f"OK: sent={sent_count}, errors={error_count}, {depth_info}")
                        # Prepare last status at for the next step.
                        last_status_at = time.monotonic()

            except Exception as exc:
                error_count += 1
                # Choose the correct branch before the workflow continues.
                if (time.monotonic() - last_status_at) >= max(1.0, float(args.status_interval)):
                    # Trigger the side effect required for this stage.
                    print(f"WARN: upload exception: {exc}")
                    last_status_at = time.monotonic()

            # Prepare next send at for the next step.
            next_send_at = time.monotonic() + send_interval

    finally:
        # Protect this step so expected failures can fall back cleanly.
        try:
            source.stop()
        except Exception:
            pass

    # Trigger the side effect required for this stage.
    print(f"Stopped edge relay. Sent={sent_count}, errors={error_count}")
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    sys.exit(main())
