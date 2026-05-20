"""Contract checks for report recovery terminal-state guards."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUPABASE_DB = ROOT / "pipeline" / "backend" / "core" / "supabase_db.py"


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_cloud_recovery_candidates_exclude_terminal_statuses():
    source = SUPABASE_DB.read_text(encoding="utf-8")
    start = source.index("def get_cloud_pending_recovery_candidates")
    end = source.index("def get_detection_event", start)
    body = source[start:end]
    status_clause_start = body.index("WHERE (de.status IS NULL OR de.status IN")
    status_clause_end = body.index("AND v.original_image_key IS NOT NULL", status_clause_start)
    status_clause = body[status_clause_start:status_clause_end]

    _assert(
        "('pending', 'queued', 'generating', 'processing', 'unknown')" in status_clause,
        f"Cloud recovery status clause drifted: {status_clause}",
    )
    for terminal in ("'failed'", "'partial'", "'skipped'"):
        _assert(
            terminal not in status_clause,
            f"Cloud recovery must not auto-requeue terminal status {terminal}: {status_clause}",
        )


def main():
    tests = [
        test_cloud_recovery_candidates_exclude_terminal_statuses,
    ]
    for test_fn in tests:
        test_fn()
        print(f"PASS: {test_fn.__name__}")
    print("Report recovery terminal contract test passed")


if __name__ == "__main__":
    main()
