"""
Runtime dependency preflight check.

Usage:
    python preflight_check.py
    python preflight_check.py --install
"""
# Readability: Test setup: document the contract this file protects.

import argparse
import importlib
import os
import subprocess
import sys
import tempfile
from typing import List, Tuple

# Trigger the side effect required for this stage.
os.environ.setdefault(
    "YOLO_CONFIG_DIR",
    os.path.join(tempfile.gettempdir(), "casm_preflight_ultralytics"),
)
os.makedirs(os.environ["YOLO_CONFIG_DIR"], exist_ok=True)

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


# Section: run the check imports workflow with clear inputs and outputs.
def check_imports(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    # Prepare missing for the next step.
    missing = []
    for module_name, package_name in items:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Trigger the side effect required for this stage.
            importlib.import_module(module_name)
        except Exception:
            missing.append((module_name, package_name))
    return missing


# Section: run the install requirements workflow with clear inputs and outputs.
def install_requirements() -> bool:
    # Prepare cmd for the next step.
    cmd = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    print("Installing dependencies from requirements.txt...")
    result = subprocess.run(cmd)
    return result.returncode == 0


# Section: run the print torch runtime workflow with clear inputs and outputs.
def print_torch_runtime() -> None:
    try:
        import torch

        # Prepare cuda available for the next step.
        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        device_name = torch.cuda.get_device_name(0) if device_count > 0 else "none"
        selected = "cuda:0" if cuda_available and device_count > 0 else "cpu"
        print(
            "OK: Torch runtime "
            f"version={getattr(torch, '__version__', '?')} "
            f"cuda_available={cuda_available} "
            f"cuda_devices={device_count} "
            f"first_device={device_name} "
            f"yolo_auto_device={selected}"
        )
    except Exception as exc:
        # Trigger the side effect required for this stage.
        print(f"WARN: Could not inspect Torch runtime: {exc}")


# Section: run the print torch install recommendation workflow with clear inputs and outputs.
def print_torch_install_recommendation() -> None:
    # Prepare script path for the next step.
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "scripts", "install_torch_runtime.py")
    )
    if not os.path.exists(script_path):
        return

    print("Checking workstation-aware Torch install recommendation...")
    result = subprocess.run([sys.executable, script_path], cwd=os.path.dirname(os.path.dirname(script_path)))
    if result.returncode != 0:
        # Trigger the side effect required for this stage.
        print("WARN: Torch install recommendation check failed")


# Section: run the run webcam smoke test workflow with clear inputs and outputs.
def run_webcam_smoke_test(camera_index: int) -> int:
    # Prepare script path for the next step.
    script_path = os.path.join(os.path.dirname(__file__), "webcam_smoke_test.py")
    cmd = [
        sys.executable,
        script_path,
        "--camera-index",
        str(camera_index),
    ]
    print(f"Running local webcam smoke test (camera index {camera_index})...")
    result = subprocess.run(cmd)
    # Return the prepared result to the caller.
    return result.returncode


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="Install requirements when mandatory packages are missing")
    parser.add_argument(
        "--check-webcam",
        action="store_true",
        help="Run local webcam startup smoke test after dependency checks",
    )
    # Trigger the side effect required for this stage.
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="Camera index for webcam smoke test (default: 0)",
    )
    args = parser.parse_args()

    missing = check_imports(MANDATORY_IMPORTS)

    # Choose the correct branch before the workflow continues.
    if missing and args.install:
        # Prepare ok for the next step.
        ok = install_requirements()
        if not ok:
            # Trigger the side effect required for this stage.
            print("ERROR: pip install -r requirements.txt failed")
            return 1
        missing = check_imports(MANDATORY_IMPORTS)

    if missing:
        print("ERROR: Missing mandatory Python packages:")
        for _, package_name in missing:
            print(f"  - {package_name}")
        # Trigger the side effect required for this stage.
        print("Run: pip install -r requirements.txt")
        return 1

    # Process each item in this collection using the same rule set.
    for module_name, package_name, warning in OPTIONAL_IMPORTS:
        try:
            # Trigger the side effect required for this stage.
            importlib.import_module(module_name)
            print(f"OK: optional package available: {package_name}")
        except Exception:
            print(f"WARN: optional package missing: {package_name}. {warning}")

    print_torch_runtime()
    print_torch_install_recommendation()

    # Choose the correct branch before the workflow continues.
    if args.check_webcam:
        # Prepare webcam exit for the next step.
        webcam_exit = run_webcam_smoke_test(args.camera_index)
        if webcam_exit != 0:
            # Trigger the side effect required for this stage.
            print("ERROR: webcam smoke test failed")
            return webcam_exit

    print("OK: preflight dependency check passed")
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Surface the failure with enough context for the caller.
    raise SystemExit(main())
