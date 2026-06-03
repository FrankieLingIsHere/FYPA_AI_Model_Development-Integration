"""Contract checks for report recovery terminal-state guards."""
# Readability: Test setup: document the contract this file protects.

from pathlib import Path


# Prepare root for the next step.
ROOT = Path(__file__).resolve().parents[1]
SUPABASE_DB = ROOT / "pipeline" / "backend" / "core" / "supabase_db.py"


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test cloud recovery candidates exclude terminal statuses workflow with clear inputs and outputs.
def test_cloud_recovery_candidates_exclude_terminal_statuses():
    source = SUPABASE_DB.read_text(encoding="utf-8")
    start = source.index("def get_cloud_pending_recovery_candidates")
    end = source.index("def get_detection_event", start)
    body = source[start:end]
    # Prepare status clause start for the next step.
    status_clause_start = body.index("WHERE (de.status IS NULL OR de.status IN")
    status_clause_end = body.index("AND v.original_image_key IS NOT NULL", status_clause_start)
    status_clause = body[status_clause_start:status_clause_end]

    _assert(
        "('pending', 'queued', 'generating', 'processing', 'unknown')" in status_clause,
        f"Cloud recovery status clause drifted: {status_clause}",
    )
    for terminal in ("'failed'", "'partial'", "'skipped'"):
        # Trigger the side effect required for this stage.
        _assert(
            terminal not in status_clause,
            f"Cloud recovery must not auto-requeue terminal status {terminal}: {status_clause}",
        )


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Prepare tests for the next step.
    tests = [
        test_cloud_recovery_candidates_exclude_terminal_statuses,
    ]
    for test_fn in tests:
        # Trigger the side effect required for this stage.
        test_fn()
        print(f"PASS: {test_fn.__name__}")
    print("Report recovery terminal contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Trigger the side effect required for this stage.
    main()
