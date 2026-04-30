"""
Runtime dependency preflight check.

Usage:
    python preflight_check.py
    python preflight_check.py --install
"""

import argparse
import importlib
import os
import subprocess
import sys
from typing import List, Tuple

MANDATORY_IMPORTS: List[Tuple[str, str]] = [
    ("flask", "Flask"),
    ("cv2", "opencv-python"),
    ("numpy", "numpy"),
    ("ultralytics", "ultralytics"),
    ("dotenv", "python-dotenv"),
    ("requests", "requests"),
    ("supabase", "supabase"),
    ("psycopg2", "psycopg2-binary"),
]

OPTIONAL_IMPORTS: List[Tuple[str, str, str]] = [
    (
        "pyrealsense2",
        "pyrealsense2",
        "RealSense source will be disabled; webcam fallback still works.",
    ),
]


def check_imports(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    missing = []
    for module_name, package_name in items:
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append((module_name, package_name))
    return missing


def install_requirements() -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    print("Installing dependencies from requirements.txt...")
    result = subprocess.run(cmd)
    return result.returncode == 0


def run_webcam_smoke_test(camera_index: int) -> int:
    script_path = os.path.join(os.path.dirname(__file__), "webcam_smoke_test.py")
    cmd = [
        sys.executable,
        script_path,
        "--camera-index",
        str(camera_index),
    ]
    print(f"Running local webcam smoke test (camera index {camera_index})...")
    result = subprocess.run(cmd)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="Install requirements when mandatory packages are missing")
    parser.add_argument(
        "--check-webcam",
        action="store_true",
        help="Run local webcam startup smoke test after dependency checks",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="Camera index for webcam smoke test (default: 0)",
    )
    args = parser.parse_args()

    missing = check_imports(MANDATORY_IMPORTS)

    if missing and args.install:
        ok = install_requirements()
        if not ok:
            print("ERROR: pip install -r requirements.txt failed")
            return 1
        missing = check_imports(MANDATORY_IMPORTS)

    if missing:
        print("ERROR: Missing mandatory Python packages:")
        for _, package_name in missing:
            print(f"  - {package_name}")
        print("Run: pip install -r requirements.txt")
        return 1

    for module_name, package_name, warning in OPTIONAL_IMPORTS:
        try:
            importlib.import_module(module_name)
            print(f"OK: optional package available: {package_name}")
        except Exception:
            print(f"WARN: optional package missing: {package_name}. {warning}")

    if args.check_webcam:
        webcam_exit = run_webcam_smoke_test(args.camera_index)
        if webcam_exit != 0:
            print("ERROR: webcam smoke test failed")
            return webcam_exit

    print("OK: preflight dependency check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
