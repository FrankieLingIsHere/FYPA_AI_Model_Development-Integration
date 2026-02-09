
import os
import sys
import logging
from dotenv import load_dotenv

# Load env vars first
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CancelReports")

# Add parent directory to path to import pipeline modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pipeline.backend.core.supabase_db import SupabaseDatabaseManager
from pipeline.backend.core.supabase_db import SupabaseDatabaseManager
from pipeline.config import SUPABASE_CONFIG

def cancel_pending_reports():
    """
    Cancel all reports that are currently pending, generating, or stuck.
    """
    db_url = SUPABASE_CONFIG.get('db_url')
    if not db_url:
        logger.error("SUPABASE_DB_URL not found in environment or config")
        return

    try:
        db = SupabaseDatabaseManager(db_url)
        
        # Get all stuck/pending reports
        with db.conn.cursor() as cur:
            # Select all reports that are NOT completed and NOT failed
            cur.execute("""
                SELECT report_id, status 
                FROM public.detection_events 
                WHERE status NOT IN ('completed', 'failed')
            """)
            
            pending_reports = cur.fetchall()
            
            if not pending_reports:
                logger.info("No pending reports found to cancel.")
                return

            logger.info(f"Found {len(pending_reports)} pending/stuck reports. Cancelling...")
            
            count = 0
            for row in pending_reports:
                report_id = row['report_id']
                old_status = row['status']
                
                # Update to failed
                success = db.update_detection_status(
                    report_id, 
                    'failed', 
                    'Cancelled by user request to reset queue.'
                )
                
                if success:
                    logger.info(f"Cancelled {report_id} (was {old_status})")
                    count += 1
                else:
                    logger.error(f"Failed to cancel {report_id}")
            
            logger.info(f"Successfully cancelled {count} reports.")
            
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        if 'db' in locals():
            db.close()

if __name__ == "__main__":
    cancel_pending_reports()
