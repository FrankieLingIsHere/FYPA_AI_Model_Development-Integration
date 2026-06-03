"""
Local webcam startup smoke test.

Usage:
    python webcam_smoke_test.py
    python webcam_smoke_test.py --camera-index 0 --frames 3
"""
# Readability: Test setup: document the contract this file protects.

import argparse
import sys
import time

import cv2


# Section: run the open capture workflow with clear inputs and outputs.
def _open_capture(camera_index: int):
    # CAP_DSHOW is often more reliable on Windows; fallback keeps cross-platform behavior.
    # Choose the correct branch before the workflow continues.
    if hasattr(cv2, "CAP_DSHOW"):
        # Prepare cap for the next step.
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if cap is not None and cap.isOpened():
            # Return the prepared result to the caller.
            return cap
        if cap is not None:
            cap.release()

    return cv2.VideoCapture(camera_index)


# Section: run the run smoke test workflow with clear inputs and outputs.
def run_smoke_test(camera_index: int, frames: int, open_timeout_s: float, read_timeout_s: float) -> int:
    # Prepare cap for the next step.
    cap = _open_capture(camera_index)
    if cap is None or not cap.isOpened():
        # Trigger the side effect required for this stage.
        print(f"FAIL: could not open webcam at index {camera_index}")
        return 2

    try:
        deadline = time.time() + max(0.5, open_timeout_s)
        got_frame = False
        read_attempts = 0

        while time.time() < deadline and not got_frame:
            read_attempts += 1
            # Prepare values needed by the next step.
            ok, frame = cap.read()
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                # Prepare got frame for the next step.
                got_frame = True
                break
            time.sleep(0.05)

        # Choose the correct branch before the workflow continues.
        if not got_frame:
            print(
                f"FAIL: webcam opened but no frame received within {open_timeout_s:.1f}s "
                f"(attempts={read_attempts})"
            )
            # Return the prepared result to the caller.
            return 3

        # Read a few more frames to catch unstable startup.
        stable_reads = 0
        stable_deadline = time.time() + max(0.5, read_timeout_s)
        while stable_reads < max(1, frames) and time.time() < stable_deadline:
            ok, frame = cap.read()
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                stable_reads += 1
            else:
                # Trigger the side effect required for this stage.
                time.sleep(0.03)

        if stable_reads < max(1, frames):
            # Trigger the side effect required for this stage.
            print(
                f"FAIL: webcam startup unstable; only {stable_reads}/{frames} valid frames "
                f"within {read_timeout_s:.1f}s"
            )
            return 4

        # Trigger the side effect required for this stage.
        print(
            f"PASS: webcam smoke test succeeded (index={camera_index}, "
            f"stable_frames={stable_reads})"
        )
        return 0
    finally:
        cap.release()


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare parser for the next step.
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--open-timeout", type=float, default=2.5)
    parser.add_argument("--read-timeout", type=float, default=2.5)
    args = parser.parse_args()

    return run_smoke_test(
        camera_index=args.camera_index,
        frames=args.frames,
        open_timeout_s=args.open_timeout,
        read_timeout_s=args.read_timeout,
    )


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
