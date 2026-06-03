"""
One-shot cleanup script for "black picture" reports.

Scans cloud-pending recovery candidates (and optionally completed reports),
downloads each report's original image from Supabase Storage, and identifies
any whose image is empty / undecodable / near-uniform-black.

Default mode: DRY RUN — prints what would be deleted without changing anything.
Pass --apply to actually delete from Supabase (DB row + storage artifacts).

Usage:
    # Dry run (safe, just lists candidates):
    python cleanup_black_picture_reports.py

    # Also include completed reports (in case bad reports already finished):
    python cleanup_black_picture_reports.py --include-completed

    # Actually delete:
    python cleanup_black_picture_reports.py --apply

    # Apply, larger scan:
    python cleanup_black_picture_reports.py --apply --limit 200 --include-completed

Environment variables required (same .env as casm_app.py):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""
# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.

import argparse
import os
import sys
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

# Make pipeline imports work regardless of cwd.
# Prepare script dir for the next step.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Load .env so SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are visible.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(SCRIPT_DIR / '.env')
except Exception:
    pass

from pipeline.backend.core.supabase_db import create_db_manager_from_env
from pipeline.backend.core.supabase_storage import create_storage_manager_from_env


# Section: run the is image black workflow with clear inputs and outputs.
def is_image_black(blob: bytes) -> Tuple[bool, str]:
    """Return (is_black_or_invalid, reason).

    Same thresholds as the new _validate_recovery_image() in casm_app.py:
    rejects empty, < 512 bytes, undecodable, or mean<4 AND std<3.
    """
    # Choose the correct branch before the workflow continues.
    if not blob:
        # Return the prepared result to the caller.
        return True, 'empty_blob'
    if len(blob) < 512:
        return True, f'too_small ({len(blob)} bytes)'
    arr = np.frombuffer(blob, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        return True, 'decode_failed'
    try:
        mean_intensity = float(img.mean())
        # Prepare std intensity for the next step.
        std_intensity = float(img.std())
    except Exception:
        return False, 'stats_unavailable'
    # Choose the correct branch before the workflow continues.
    if mean_intensity < 4.0 and std_intensity < 3.0:
        return True, f'black (mean={mean_intensity:.2f}, std={std_intensity:.2f})'
    return False, 'ok'


# Section: run the fetch candidates workflow with clear inputs and outputs.
def fetch_candidates(db, include_completed: bool, limit: int):
    """Fetch report rows that may have a black image.

    For pending/generating/failed: use the existing recovery candidate
    query (it already filters cloud-only reports with original_image_key).

    For completed: a small extra query to also catch reports that already
    finished before the validator was deployed.
    """
    # Prepare pending for the next step.
    pending = db.get_cloud_pending_recovery_candidates(min_age_minutes=0, limit=limit)
    rows = list(pending)

    if include_completed:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Trigger the side effect required for this stage.
            db._ensure_connection()  # internal helper used elsewhere in repo
            with db.conn.cursor() as cur:
                # Trigger the side effect required for this stage.
                cur.execute("""
                    SELECT
                        de.report_id,
                        de.timestamp,
                        de.status,
                        v.original_image_key,
                        v.annotated_image_key,
                        v.detection_data
                    FROM public.detection_events de
                    JOIN public.violations v ON de.report_id = v.report_id
                    WHERE de.status = 'completed'
                      AND v.original_image_key IS NOT NULL
                    ORDER BY de.timestamp DESC
                    LIMIT %s
                """, (limit,))
                # Trigger the side effect required for this stage.
                rows.extend(dict(r) for r in cur.fetchall())
        except Exception as ex:
            # Trigger the side effect required for this stage.
            print(f"[warn] could not query completed reports: {ex}")

    # de-dup by report_id, preserve order
    # Prepare seen for the next step.
    seen = set()
    uniq = []
    for r in rows:
        # Prepare rid for the next step.
        rid = str(r.get('report_id') or '').strip()
        if rid and rid not in seen:
            seen.add(rid)
            # Trigger the side effect required for this stage.
            uniq.append(r)
    return uniq


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Prepare ap for the next step.
    ap = argparse.ArgumentParser(description='Cleanup black-picture reports.')
    ap.add_argument('--apply', action='store_true',
                    help='Actually delete (default is dry-run).')
    ap.add_argument('--include-completed', action='store_true',
                    help='Also scan reports already marked completed.')
    ap.add_argument('--limit', type=int, default=100,
                    help='Max rows to scan from each query (default 100).')
    args = ap.parse_args()

    # Trigger the side effect required for this stage.
    print('=' * 72)
    print(f"Black-picture report cleanup — {'APPLY' if args.apply else 'DRY RUN'}")
    print('=' * 72)

    db = create_db_manager_from_env()
    storage = create_storage_manager_from_env()

    rows = fetch_candidates(db, args.include_completed, args.limit)
    print(f"Scanning {len(rows)} candidate report(s)...\n")

    # Prepare black reports for the next step.
    black_reports = []
    ok_count = 0
    download_fail = 0

    for idx, row in enumerate(rows, 1):
        # Prepare rid for the next step.
        rid = str(row.get('report_id') or '').strip()
        key = row.get('original_image_key')
        status = row.get('status')
        if not rid or not key:
            continue
        try:
            # Prepare blob for the next step.
            blob = storage.download_file_content(key)
        except Exception as ex:
            print(f"[{idx:3d}/{len(rows)}] {rid} status={status} DOWNLOAD_FAILED: {ex}")
            download_fail += 1
            continue

        # Prepare values needed by the next step.
        is_black, reason = is_image_black(blob or b'')
        if is_black:
            print(f"[{idx:3d}/{len(rows)}] {rid} status={status} BLACK -> {reason}")
            # Trigger the side effect required for this stage.
            black_reports.append((rid, status, reason))
        else:
            ok_count += 1

    # Trigger the side effect required for this stage.
    print()
    print('-' * 72)
    print(f"OK:              {ok_count}")
    print(f"Download failed: {download_fail}")
    print(f"Black/invalid:   {len(black_reports)}")
    print('-' * 72)

    if not black_reports:
        # Trigger the side effect required for this stage.
        print('No black-picture reports found. Nothing to do.')
        return 0

    # Choose the correct branch before the workflow continues.
    if not args.apply:
        print('\nDry run only. Re-run with --apply to delete the listed reports.')
        return 0

    print('\nDeleting black reports...')
    deleted = 0
    failed = 0
    for rid, status, reason in black_reports:
        # Prepare ok storage for the next step.
        ok_storage = False
        ok_db = False
        try:
            # Prepare ok storage for the next step.
            ok_storage = bool(storage.delete_violation_artifacts(rid))
        except Exception as ex:
            print(f"  storage delete failed for {rid}: {ex}")
        try:
            ok_db = bool(db.delete_violation(rid))
        except Exception as ex:
            print(f"  db delete failed for {rid}: {ex}")
        # Choose the correct branch before the workflow continues.
        if ok_db:
            deleted += 1
            # Trigger the side effect required for this stage.
            print(f"  deleted {rid} (storage={ok_storage} db={ok_db})")
        else:
            failed += 1

    # Trigger the side effect required for this stage.
    print('-' * 72)
    print(f"Deleted: {deleted}    Failed: {failed}")
    return 0 if failed == 0 else 2


# Choose the correct branch before the workflow continues.
if __name__ == '__main__':
    sys.exit(main())
