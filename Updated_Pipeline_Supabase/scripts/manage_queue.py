# Readability: Utility script: keep operational maintenance steps visible and repeatable.

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
# Trigger the side effect required for this stage.
load_dotenv()

DB_URL = os.getenv("SUPABASE_DB_URL")
if not DB_URL:
    # Trigger the side effect required for this stage.
    print("Error: SUPABASE_DB_URL not found in environment variables.")
    sys.exit(1)

# Section: run the get db connection workflow with clear inputs and outputs.
def get_db_connection():
    try:
        # Prepare conn for the next step.
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

# Section: run the list queue workflow with clear inputs and outputs.
def list_queue():
    # Prepare conn for the next step.
    conn = get_db_connection()
    try:
        # Open the managed resource only for the block that needs it.
        with conn.cursor() as cur:
            # Query for reports that are NOT completed and NOT failed
            # This includes pending, generating, or any granular status
            # Trigger the side effect required for this stage.
            cur.execute("""
                SELECT report_id, timestamp, status, person_count, violation_count
                FROM public.detection_events
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                OR status IS NULL
                ORDER BY timestamp DESC
            """)
            reports = cur.fetchall()
            
            # Trigger the side effect required for this stage.
            print(f"\n--- Queue Status ({len(reports)} items) ---")
            if not reports:
                # Trigger the side effect required for this stage.
                print("Queue is empty.")
            else:
                for r in reports:
                    # Trigger the side effect required for this stage.
                    print(f"ID: {r['report_id']} | Time: {r['timestamp']} | Status: {r['status']} | P: {r['person_count']} V: {r['violation_count']}")
            return reports
    finally:
        # Trigger the side effect required for this stage.
        conn.close()

# Section: run the clear queue workflow with clear inputs and outputs.
def clear_queue():
    # Prepare conn for the next step.
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Delete reports that are NOT completed and NOT failed
            # We delete from detection_events. Assuming cascade or manual cleanup needed?
            # Let's check constraints? Usually report_id is foreign key in violations.
            # We'll try to delete from violations first just in case.
            
            # Identify IDs to delete first for logging
            cur.execute("""
                SELECT report_id FROM public.detection_events
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                OR status IS NULL
            """)
            rows = cur.fetchall()
            ids_to_delete = [r['report_id'] for r in rows]
            
            if not ids_to_delete:
                # Trigger the side effect required for this stage.
                print("No reports to clear.")
                return

            # Trigger the side effect required for this stage.
            print(f"Deleting {len(ids_to_delete)} reports...")
            
            # Execute Delete
            cur.execute("""
                DELETE FROM public.detection_events
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                OR status IS NULL
            """)
            
            # Trigger the side effect required for this stage.
            print(f"Successfully deleted {cur.rowcount} records from detection_events.")
            
    except Exception as e:
        # Trigger the side effect required for this stage.
        print(f"Error clearing queue: {e}")
    finally:
        conn.close()

# Section: run the inspect report workflow with clear inputs and outputs.
def inspect_report(report_id):
    # Prepare conn for the next step.
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check detection_events
            # Trigger the side effect required for this stage.
            cur.execute("""
                SELECT
                    report_id,
                    timestamp,
                    device_id,
                    person_count,
                    violation_count,
                    severity,
                    status,
                    error_message,
                    created_at,
                    updated_at
                FROM public.detection_events
                WHERE report_id = %s
                LIMIT 1
            """, (report_id,))
            # Prepare de for the next step.
            de = cur.fetchone()
            print(f"\n--- Detection Event ({report_id}) ---")
            if de:
                # Process each item in this collection using the same rule set.
                for k, v in de.items():
                    # Trigger the side effect required for this stage.
                    print(f"{k}: {v}")
            else:
                print("No detection event found.")
            
            # Check violations
            # Trigger the side effect required for this stage.
            cur.execute("""
                SELECT
                    id,
                    report_id,
                    violation_summary,
                    caption,
                    nlp_analysis,
                    detection_data,
                    original_image_key,
                    annotated_image_key,
                    report_html_key,
                    report_pdf_key,
                    device_id,
                    created_at,
                    updated_at
                FROM public.violations
                WHERE report_id = %s
                LIMIT 1
            """, (report_id,))
            # Prepare v for the next step.
            v = cur.fetchone()
            print(f"\n--- Violation Record ({report_id}) ---")
            if v:
                # Process each item in this collection using the same rule set.
                for k, val in v.items():
                    # Truncate long fields
                    # Prepare val str for the next step.
                    val_str = str(val)
                    if len(val_str) > 100:
                        val_str = val_str[:100] + "..."
                    print(f"{k}: {val_str}")
            else:
                print("No violation record found.")
    finally:
        # Trigger the side effect required for this stage.
        conn.close()

# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Choose the correct branch before the workflow continues.
    if len(sys.argv) < 2:
        print("Usage: python manage_queue.py [list|clear|inspect <id>]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    if command == "list":
        # Trigger the side effect required for this stage.
        list_queue()
    elif command == "inspect":
        if len(sys.argv) < 3:
            # Trigger the side effect required for this stage.
            print("Usage: python manage_queue.py inspect <report_id>")
            sys.exit(1)
        inspect_report(sys.argv[2])
    # Choose the correct branch before the workflow continues.
    elif command == "clear":
        force = "--force" in sys.argv
        list_queue() # Show what will be deleted
        
        # Choose the correct branch before the workflow continues.
        if force:
            print("\nForce deleting without confirmation...")
            # Trigger the side effect required for this stage.
            clear_queue()
            print("\nQueue cleared.")
        else:
            confirm = input("\nAre you sure you want to delete these pending reports? (yes/no): ")
            if confirm.lower() == "yes":
                # Trigger the side effect required for this stage.
                clear_queue()
                print("\nQueue cleared. Updated status:")
                list_queue()
            else:
                print("Operation cancelled.")
    else:
        # Trigger the side effect required for this stage.
        print("Unknown command. Use 'list' or 'clear'.")
