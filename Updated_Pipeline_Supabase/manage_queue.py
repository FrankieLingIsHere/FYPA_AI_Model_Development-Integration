
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DB_URL = os.getenv("SUPABASE_DB_URL")
if not DB_URL:
    print("Error: SUPABASE_DB_URL not found in environment variables.")
    sys.exit(1)

def get_db_connection():
    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def list_queue():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Query for reports that are NOT completed and NOT failed
            # This includes pending, generating, or any granular status
            cur.execute("""
                SELECT report_id, timestamp, status, person_count, violation_count
                FROM public.detection_events
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                OR status IS NULL
                ORDER BY timestamp DESC
            """)
            reports = cur.fetchall()
            
            print(f"\n--- Queue Status ({len(reports)} items) ---")
            if not reports:
                print("Queue is empty.")
            else:
                for r in reports:
                    print(f"ID: {r['report_id']} | Time: {r['timestamp']} | Status: {r['status']} | P: {r['person_count']} V: {r['violation_count']}")
            return reports
    finally:
        conn.close()

def clear_queue():
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
                print("No reports to clear.")
                return

            print(f"Deleting {len(ids_to_delete)} reports...")
            
            # Execute Delete
            cur.execute("""
                DELETE FROM public.detection_events
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                OR status IS NULL
            """)
            
            print(f"Successfully deleted {cur.rowcount} records from detection_events.")
            
    except Exception as e:
        print(f"Error clearing queue: {e}")
    finally:
        conn.close()

def inspect_report(report_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check detection_events
            cur.execute("SELECT * FROM public.detection_events WHERE report_id = %s", (report_id,))
            de = cur.fetchone()
            print(f"\n--- Detection Event ({report_id}) ---")
            if de:
                for k, v in de.items():
                    print(f"{k}: {v}")
            else:
                print("No detection event found.")
            
            # Check violations
            cur.execute("SELECT * FROM public.violations WHERE report_id = %s", (report_id,))
            v = cur.fetchone()
            print(f"\n--- Violation Record ({report_id}) ---")
            if v:
                for k, val in v.items():
                    # Truncate long fields
                    val_str = str(val)
                    if len(val_str) > 100:
                        val_str = val_str[:100] + "..."
                    print(f"{k}: {val_str}")
            else:
                print("No violation record found.")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python manage_queue.py [list|clear|inspect <id>]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    if command == "list":
        list_queue()
    elif command == "inspect":
        if len(sys.argv) < 3:
            print("Usage: python manage_queue.py inspect <report_id>")
            sys.exit(1)
        inspect_report(sys.argv[2])
    elif command == "clear":
        force = "--force" in sys.argv
        list_queue() # Show what will be deleted
        
        if force:
            print("\nForce deleting without confirmation...")
            clear_queue()
            print("\nQueue cleared.")
        else:
            confirm = input("\nAre you sure you want to delete these pending reports? (yes/no): ")
            if confirm.lower() == "yes":
                clear_queue()
                print("\nQueue cleared. Updated status:")
                list_queue()
            else:
                print("Operation cancelled.")
    else:
        print("Unknown command. Use 'list' or 'clear'.")
