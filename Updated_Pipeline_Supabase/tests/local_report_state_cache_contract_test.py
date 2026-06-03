"""
Contract test for local report state cache reuse.

The helper that scans local violation folders is shared by multiple endpoints,
so repeated calls inside the short TTL should avoid rescanning the directory.
"""
# Readability: Test setup: document the contract this file protects.

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_STATE_DIR = os.path.join(tempfile.gettempdir(), "casm_local_report_state_cache_state")
TEST_ULTRALYTICS_DIR = os.path.join(tempfile.gettempdir(), "casm_local_report_state_cache_ultralytics")
os.makedirs(TEST_STATE_DIR, exist_ok=True)
os.makedirs(TEST_ULTRALYTICS_DIR, exist_ok=True)

os.environ.setdefault("FLASK_DEBUG", "false")
# Trigger the side effect required for this stage.
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-magic-password")
os.environ.setdefault("BOOTSTRAP_TOKEN_SECRET", "test-bootstrap-secret")
os.environ.setdefault("CASM_STATE_DIR", TEST_STATE_DIR)
os.environ.setdefault("YOLO_CONFIG_DIR", TEST_ULTRALYTICS_DIR)

import casm_app


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test local report state rows reuse short ttl cache workflow with clear inputs and outputs.
def test_local_report_state_rows_reuse_short_ttl_cache():
    old_violations_dir = casm_app.VIOLATIONS_DIR
    old_ttl = casm_app.LOCAL_REPORT_STATE_CACHE_TTL_SECONDS

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Prepare report dir for the next step.
        report_dir = root / "20260512_121500"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "original.jpg").write_bytes(b"image")
        (report_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "violation_count": 1,
                    "person_count": 1,
                    "missing_ppe": ["Hardhat"],
                    "ppe_tags": ["NO-Hardhat"],
                    "violation_summary": "PPE Violation Detected: NO-Hardhat",
                    "device_id": "webcam_0",
                }
            ),
            encoding="utf-8",
        )

        # Prepare original iterdir for the next step.
        original_iterdir = Path.iterdir
        scan_counter = {"count": 0}

        # Section: run the counted iterdir workflow with clear inputs and outputs.
        def counted_iterdir(self):
            # Choose the correct branch before the workflow continues.
            if self == root:
                scan_counter["count"] += 1
            return original_iterdir(self)

        try:
            casm_app.VIOLATIONS_DIR = root
            casm_app.LOCAL_REPORT_STATE_CACHE_TTL_SECONDS = 60.0
            casm_app._invalidate_local_report_state_cache()

            # Open the managed resource only for the block that needs it.
            with patch.object(Path, "iterdir", counted_iterdir):
                # Prepare first rows for the next step.
                first_rows = casm_app._collect_local_report_state_rows(limit=20)
                second_rows = casm_app._collect_local_report_state_rows(limit=20)

            _assert(len(first_rows) == 1, f"Unexpected first result: {first_rows}")
            _assert(len(second_rows) == 1, f"Unexpected second result: {second_rows}")
            _assert(
                scan_counter["count"] == 1,
                f"Expected cached second scan, observed scans={scan_counter['count']}",
            )

            # Trigger the side effect required for this stage.
            casm_app._invalidate_local_report_state_cache()
            with patch.object(Path, "iterdir", counted_iterdir):
                # Prepare third rows for the next step.
                third_rows = casm_app._collect_local_report_state_rows(limit=20)

            _assert(len(third_rows) == 1, f"Unexpected third result: {third_rows}")
            _assert(
                scan_counter["count"] == 2,
                f"Expected rescan after invalidation, observed scans={scan_counter['count']}",
            )
        finally:
            # Prepare violations dir for the next step.
            casm_app.VIOLATIONS_DIR = old_violations_dir
            casm_app.LOCAL_REPORT_STATE_CACHE_TTL_SECONDS = old_ttl
            casm_app._invalidate_local_report_state_cache()


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Trigger the side effect required for this stage.
        test_local_report_state_rows_reuse_short_ttl_cache()
        print("PASS: test_local_report_state_rows_reuse_short_ttl_cache")
    except Exception as exc:
        print(f"FAIL: test_local_report_state_rows_reuse_short_ttl_cache: {exc}")
        raise SystemExit(1)

    print("Local report state cache contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    main()
