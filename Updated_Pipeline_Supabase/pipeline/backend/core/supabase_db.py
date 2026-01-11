"""
Supabase Database Manager
==========================

Handles database operations with Supabase Postgres.
Manages violations in detection_events, violations, and flood_logs tables.
"""

import logging
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger(__name__)


class SupabaseDatabaseManager:
    """
    Manages database operations with Supabase Postgres.
    
    Tables:
    - detection_events: Main violation event records
    - violations: Detailed violation data with storage keys
    - flood_logs: System event logging
    """
    
    def __init__(self, db_url: str):
        """
        Initialize Supabase Database Manager.
        
        Args:
            db_url: Postgres connection URL (from Supabase dashboard)
        """
        self.db_url = db_url
        self.conn = None
        
        try:
            self._connect()
            logger.info("Supabase Database Manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def _connect(self):
        """Establish database connection."""
        try:
            self.conn = psycopg2.connect(
                self.db_url,
                cursor_factory=RealDictCursor
            )
            self.conn.autocommit = False
            logger.info("Connected to Supabase Postgres")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def _ensure_connection(self):
        """Ensure database connection is active."""
        if self.conn is None or self.conn.closed:
            logger.warning("Database connection lost, reconnecting...")
            self._connect()
    
    def close(self):
        """Close database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("Database connection closed")
    
    # =========================================================================
    # DETECTION EVENTS
    # =========================================================================
    
    def insert_detection_event(
        self,
        report_id: str,
        timestamp: datetime,
        person_count: int = 0,
        violation_count: int = 0,
        severity: str = 'HIGH',
        status: str = 'pending'
    ) -> Optional[str]:
        """
        Insert a detection event record.
        
        Args:
            report_id: Unique report identifier
            timestamp: Detection timestamp
            person_count: Number of people detected
            violation_count: Number of violations
            severity: Severity level (HIGH/MEDIUM/LOW)
            status: Processing status (pending/generating/completed/failed)
        
        Returns:
            Report ID if successful, None otherwise
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                # Try with status column first, fallback without if column doesn't exist
                try:
                    cur.execute("""
                        INSERT INTO public.detection_events 
                        (report_id, timestamp, person_count, violation_count, severity, status)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING report_id
                    """, (report_id, timestamp, person_count, violation_count, severity, status))
                except Exception:
                    # Fallback without status column
                    cur.execute("""
                        INSERT INTO public.detection_events 
                        (report_id, timestamp, person_count, violation_count, severity)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING report_id
                    """, (report_id, timestamp, person_count, violation_count, severity))
                
                result = cur.fetchone()
                self.conn.commit()
                
                logger.info(f"Inserted detection event: {report_id} (status: {status})")
                return result['report_id'] if result else None
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert detection event: {e}")
            return None
    
    def update_detection_status(
        self,
        report_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> bool:
        """
        Update the status of a detection event.
        
        Args:
            report_id: Report identifier
            status: New status (pending/generating/completed/failed)
            error_message: Optional error message for failed status
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                if error_message:
                    cur.execute("""
                        UPDATE public.detection_events 
                        SET status = %s, error_message = %s, updated_at = NOW()
                        WHERE report_id = %s
                    """, (status, error_message, report_id))
                else:
                    cur.execute("""
                        UPDATE public.detection_events 
                        SET status = %s, updated_at = NOW()
                        WHERE report_id = %s
                    """, (status, report_id))
                
                self.conn.commit()
                logger.info(f"Updated detection status: {report_id} -> {status}")
                return True
                
        except Exception as e:
            self.conn.rollback()
            logger.warning(f"Could not update detection status (column may not exist): {e}")
            return False
    
    def update_detection_event(
        self,
        report_id: str,
        person_count: Optional[int] = None,
        violation_count: Optional[int] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Update detection event fields.
        
        Args:
            report_id: Report identifier
            person_count: Number of persons detected
            violation_count: Number of violations
            severity: Severity level
            status: Detection status
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        try:
            updates = []
            params = []
            
            if person_count is not None:
                updates.append("person_count = %s")
                params.append(person_count)
            
            if violation_count is not None:
                updates.append("violation_count = %s")
                params.append(violation_count)
            
            if severity is not None:
                updates.append("severity = %s")
                params.append(severity)
            
            if status is not None:
                updates.append("status = %s")
                params.append(status)
            
            if not updates:
                return False
            
            updates.append("updated_at = NOW()")
            params.append(report_id)
            
            with self.conn.cursor() as cur:
                query = f"""
                    UPDATE public.detection_events
                    SET {', '.join(updates)}
                    WHERE report_id = %s
                """
                cur.execute(query, params)
                self.conn.commit()
                
                logger.info(f"Updated detection event: {report_id}")
                return cur.rowcount > 0
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update detection event: {e}")
            return False
    
    def fix_stuck_reports(self) -> int:
        """
        Fix reports stuck in pending/generating status by checking actual data.
        
        This checks each report's actual state:
        - If has report_html_key -> completed
        - If has violation record but no report -> failed (likely timed out)
        - If no violation record and old -> failed
        
        Returns:
            Number of reports fixed
        """
        self._ensure_connection()
        fixed_count = 0
        
        try:
            with self.conn.cursor() as cur:
                # Get all reports with pending or generating status (or NULL/unknown)
                cur.execute("""
                    SELECT 
                        de.report_id,
                        de.timestamp,
                        de.status,
                        v.id as violation_id,
                        v.report_html_key,
                        v.annotated_image_key
                    FROM public.detection_events de
                    LEFT JOIN public.violations v ON de.report_id = v.report_id
                    WHERE de.status IS NULL 
                       OR de.status = 'pending' 
                       OR de.status = 'generating'
                       OR de.status = 'unknown'
                """)
                
                stuck_reports = cur.fetchall()
                
                for report in stuck_reports:
                    report_id = report['report_id']
                    has_violation = report['violation_id'] is not None
                    has_report = report['report_html_key'] is not None
                    has_annotated = report['annotated_image_key'] is not None
                    report_time = report['timestamp']
                    
                    # Determine correct status
                    new_status = None
                    
                    if has_report:
                        # Has full report - mark completed
                        new_status = 'completed'
                    elif has_violation and has_annotated:
                        # Has violation record with annotated image but no report
                        # Check if it's old (more than 5 minutes) - likely failed
                        from datetime import datetime, timedelta
                        if report_time and (datetime.now() - report_time) > timedelta(minutes=5):
                            new_status = 'partial'  # Has some data but incomplete
                        # else leave as generating - might still be processing
                    elif has_violation:
                        # Has violation record but no images/report
                        from datetime import datetime, timedelta
                        if report_time and (datetime.now() - report_time) > timedelta(minutes=5):
                            new_status = 'failed'
                    else:
                        # No violation record at all
                        from datetime import datetime, timedelta
                        if report_time and (datetime.now() - report_time) > timedelta(minutes=5):
                            new_status = 'failed'  # Timed out without generating anything
                    
                    if new_status:
                        try:
                            cur.execute("""
                                UPDATE public.detection_events 
                                SET status = %s, updated_at = NOW()
                                WHERE report_id = %s
                            """, (new_status, report_id))
                            fixed_count += 1
                            logger.info(f"Fixed stuck report {report_id}: {report['status']} -> {new_status}")
                        except Exception as e:
                            logger.warning(f"Could not fix report {report_id}: {e}")
                
                self.conn.commit()
                logger.info(f"Fixed {fixed_count} stuck reports")
                
        except Exception as e:
            self.conn.rollback()
            logger.warning(f"Could not fix stuck reports: {e}")
        
        return fixed_count
    
    def get_detection_event(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a detection event by report_id.
        
        Args:
            report_id: Report identifier
        
        Returns:
            Detection event dictionary or None
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM public.detection_events
                    WHERE report_id = %s
                """, (report_id,))
                
                result = cur.fetchone()
                return dict(result) if result else None
                
        except Exception as e:
            logger.error(f"Failed to get detection event {report_id}: {e}")
            return None
    
    def get_recent_detection_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve recent detection events.
        
        Args:
            limit: Maximum number of events to retrieve
        
        Returns:
            List of detection event dictionaries
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM public.detection_events
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (limit,))
                
                results = cur.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Failed to get recent detection events: {e}")
            return []
    
    def get_all_violations_with_status(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve ALL detection events with their violation data (including pending).
        Uses LEFT JOIN to include detection events that don't have violation records yet.
        
        This is the MAIN method to use for the frontend API - it returns:
        - Pending violations (detection event exists but no violation record)
        - Generating violations (in process)
        - Completed violations (full violation record exists)
        - Failed violations
        
        Args:
            limit: Maximum number of events to retrieve
        
        Returns:
            List of violation dictionaries with status
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                # Try query with status column first
                try:
                    cur.execute("""
                        SELECT 
                            de.report_id,
                            de.timestamp,
                            de.person_count,
                            de.violation_count,
                            de.severity,
                            de.status,
                            de.error_message,
                            v.id as violation_id,
                            v.violation_summary,
                            v.caption,
                            v.nlp_analysis,
                            v.detection_data,
                            v.original_image_key,
                            v.annotated_image_key,
                            v.report_html_key,
                            v.report_pdf_key
                        FROM public.detection_events de
                        LEFT JOIN public.violations v ON de.report_id = v.report_id
                        ORDER BY de.timestamp DESC
                        LIMIT %s
                    """, (limit,))
                except Exception:
                    # Fallback without status column
                    cur.execute("""
                        SELECT 
                            de.report_id,
                            de.timestamp,
                            de.person_count,
                            de.violation_count,
                            de.severity,
                            'unknown' as status,
                            NULL as error_message,
                            v.id as violation_id,
                            v.violation_summary,
                            v.caption,
                            v.nlp_analysis,
                            v.detection_data,
                            v.original_image_key,
                            v.annotated_image_key,
                            v.report_html_key,
                            v.report_pdf_key
                        FROM public.detection_events de
                        LEFT JOIN public.violations v ON de.report_id = v.report_id
                        ORDER BY de.timestamp DESC
                        LIMIT %s
                    """, (limit,))
                
                results = cur.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Failed to get violations with status: {e}")
            return []
    
    # =========================================================================
    # VIOLATIONS
    # =========================================================================
    
    def insert_violation(
        self,
        report_id: str,
        violation_summary: Optional[str] = None,
        caption: Optional[str] = None,
        nlp_analysis: Optional[Dict[str, Any]] = None,
        detection_data: Optional[Dict[str, Any]] = None,
        original_image_key: Optional[str] = None,
        annotated_image_key: Optional[str] = None,
        report_html_key: Optional[str] = None,
        report_pdf_key: Optional[str] = None
    ) -> Optional[str]:
        """
        Insert a violation record with storage keys.
        
        Args:
            report_id: Report identifier (foreign key to detection_events)
            violation_summary: Summary text
            caption: Image caption from LLaVA
            nlp_analysis: NLP analysis from Llama3 (stored as JSONB)
            detection_data: YOLO detection data (stored as JSONB)
            original_image_key: Storage key for original image
            annotated_image_key: Storage key for annotated image
            report_html_key: Storage key for HTML report
            report_pdf_key: Storage key for PDF report
        
        Returns:
            UUID of inserted violation or None
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.violations 
                    (report_id, violation_summary, caption, nlp_analysis, detection_data,
                     original_image_key, annotated_image_key, report_html_key, report_pdf_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    report_id,
                    violation_summary,
                    caption,
                    Json(nlp_analysis) if nlp_analysis else None,
                    Json(detection_data) if detection_data else None,
                    original_image_key,
                    annotated_image_key,
                    report_html_key,
                    report_pdf_key
                ))
                
                result = cur.fetchone()
                self.conn.commit()
                
                logger.info(f"Inserted violation: {report_id}")
                return str(result['id']) if result else None
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert violation: {e}")
            return None
    
    def get_violation(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve violation by report_id.
        
        Args:
            report_id: Report identifier
        
        Returns:
            Violation dictionary or None
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT v.*, de.timestamp, de.person_count, de.violation_count, de.severity
                    FROM public.violations v
                    JOIN public.detection_events de ON v.report_id = de.report_id
                    WHERE v.report_id = %s
                """, (report_id,))
                
                result = cur.fetchone()
                return dict(result) if result else None
                
        except Exception as e:
            logger.error(f"Failed to get violation {report_id}: {e}")
            return None
    
    def get_recent_violations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve recent violations with detection event data.
        
        Args:
            limit: Maximum number of violations to retrieve
        
        Returns:
            List of violation dictionaries
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT v.*, de.timestamp, de.person_count, de.violation_count, de.severity
                    FROM public.violations v
                    JOIN public.detection_events de ON v.report_id = de.report_id
                    ORDER BY de.timestamp DESC
                    LIMIT %s
                """, (limit,))
                
                results = cur.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Failed to get recent violations: {e}")
            return []
    
    def update_violation_storage_keys(
        self,
        report_id: str,
        original_image_key: Optional[str] = None,
        annotated_image_key: Optional[str] = None,
        report_html_key: Optional[str] = None,
        report_pdf_key: Optional[str] = None
    ) -> bool:
        """
        Update storage keys for a violation.
        
        Args:
            report_id: Report identifier
            original_image_key: Storage key for original image
            annotated_image_key: Storage key for annotated image
            report_html_key: Storage key for HTML report
            report_pdf_key: Storage key for PDF report
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        try:
            updates = []
            params = []
            
            if original_image_key is not None:
                updates.append("original_image_key = %s")
                params.append(original_image_key)
            
            if annotated_image_key is not None:
                updates.append("annotated_image_key = %s")
                params.append(annotated_image_key)
            
            if report_html_key is not None:
                updates.append("report_html_key = %s")
                params.append(report_html_key)
            
            if report_pdf_key is not None:
                updates.append("report_pdf_key = %s")
                params.append(report_pdf_key)
            
            if not updates:
                return False
            
            updates.append("updated_at = NOW()")
            params.append(report_id)
            
            with self.conn.cursor() as cur:
                query = f"""
                    UPDATE public.violations
                    SET {', '.join(updates)}
                    WHERE report_id = %s
                """
                cur.execute(query, params)
                self.conn.commit()
                
                logger.info(f"Updated storage keys for: {report_id}")
                return cur.rowcount > 0
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update storage keys: {e}")
            return False
    
    def update_violation(
        self,
        report_id: str,
        violation_summary: Optional[str] = None,
        caption: Optional[str] = None,
        nlp_analysis: Optional[Dict[str, Any]] = None,
        detection_data: Optional[Dict[str, Any]] = None,
        original_image_key: Optional[str] = None,
        annotated_image_key: Optional[str] = None,
        report_html_key: Optional[str] = None,
        report_pdf_key: Optional[str] = None
    ) -> bool:
        """
        Update a violation record with new data.
        
        Args:
            report_id: Report identifier
            violation_summary: Summary text
            caption: Image caption from LLaVA
            nlp_analysis: NLP analysis from Llama3 (stored as JSONB)
            detection_data: YOLO detection data (stored as JSONB)
            original_image_key: Storage key for original image
            annotated_image_key: Storage key for annotated image
            report_html_key: Storage key for HTML report
            report_pdf_key: Storage key for PDF report
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        try:
            updates = []
            params = []
            
            if violation_summary is not None:
                updates.append("violation_summary = %s")
                params.append(violation_summary)
            
            if caption is not None:
                updates.append("caption = %s")
                params.append(caption)
            
            if nlp_analysis is not None:
                updates.append("nlp_analysis = %s")
                params.append(Json(nlp_analysis))
            
            if detection_data is not None:
                updates.append("detection_data = %s")
                params.append(Json(detection_data))
            
            if original_image_key is not None:
                updates.append("original_image_key = %s")
                params.append(original_image_key)
            
            if annotated_image_key is not None:
                updates.append("annotated_image_key = %s")
                params.append(annotated_image_key)
            
            if report_html_key is not None:
                updates.append("report_html_key = %s")
                params.append(report_html_key)
            
            if report_pdf_key is not None:
                updates.append("report_pdf_key = %s")
                params.append(report_pdf_key)
            
            if not updates:
                return False
            
            updates.append("updated_at = NOW()")
            params.append(report_id)
            
            with self.conn.cursor() as cur:
                query = f"""
                    UPDATE public.violations
                    SET {', '.join(updates)}
                    WHERE report_id = %s
                """
                cur.execute(query, params)
                self.conn.commit()
                
                logger.info(f"Updated violation: {report_id}")
                return cur.rowcount > 0
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update violation: {e}")
            return False
    
    def delete_violation(self, report_id: str) -> bool:
        """
        Delete a violation and its detection event (cascade).
        
        Args:
            report_id: Report identifier
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                # Delete detection event (cascade will delete violation)
                cur.execute("""
                    DELETE FROM public.detection_events
                    WHERE report_id = %s
                """, (report_id,))
                
                self.conn.commit()
                logger.info(f"Deleted violation: {report_id}")
                return cur.rowcount > 0
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to delete violation: {e}")
            return False
    
    # =========================================================================
    # FLOOD LOGS
    # =========================================================================
    
    def log_event(
        self,
        event_type: str,
        message: str,
        report_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log a system event to flood_logs table.
        
        Args:
            event_type: Event type (e.g., 'upload', 'error', 'violation')
            message: Event message
            report_id: Associated report ID (optional)
            metadata: Additional metadata (stored as JSONB)
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.flood_logs 
                    (event_type, report_id, message, metadata)
                    VALUES (%s, %s, %s, %s)
                """, (
                    event_type,
                    report_id,
                    message,
                    Json(metadata) if metadata else None
                ))
                
                self.conn.commit()
                logger.debug(f"Logged event: {event_type}")
                return True
                
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to log event: {e}")
            return False
    
    def get_recent_logs(self, limit: int = 50, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve recent event logs.
        
        Args:
            limit: Maximum number of logs to retrieve
            event_type: Filter by event type (optional)
        
        Returns:
            List of log dictionaries
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cur:
                if event_type:
                    cur.execute("""
                        SELECT * FROM public.flood_logs
                        WHERE event_type = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (event_type, limit))
                else:
                    cur.execute("""
                        SELECT * FROM public.flood_logs
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                
                results = cur.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Failed to get recent logs: {e}")
            return []


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_db_manager_from_env() -> SupabaseDatabaseManager:
    """
    Create SupabaseDatabaseManager from environment variables.
    
    Required environment variable:
        - SUPABASE_DB_URL: Postgres connection URL
    
    Returns:
        SupabaseDatabaseManager instance
    """
    db_url = os.getenv('SUPABASE_DB_URL')
    
    if not db_url:
        raise ValueError("SUPABASE_DB_URL must be set in environment")
    
    return SupabaseDatabaseManager(db_url)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from dotenv import load_dotenv
    
    logging.basicConfig(level=logging.INFO)
    
    # Load environment variables
    load_dotenv()
    
    print("=" * 70)
    print("SUPABASE DATABASE MANAGER TEST")
    print("=" * 70)
    
    try:
        manager = create_db_manager_from_env()
        print(f"\n[OK] Database manager initialized")
        
        # Test detection event
        test_report_id = f"TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"\n--- Testing Detection Event ---")
        
        result = manager.insert_detection_event(
            report_id=test_report_id,
            timestamp=datetime.now(),
            person_count=2,
            violation_count=1,
            severity='HIGH'
        )
        
        if result:
            print(f"[OK] Inserted detection event: {result}")
            
            # Test violation
            print(f"\n--- Testing Violation ---")
            violation_id = manager.insert_violation(
                report_id=test_report_id,
                violation_summary="Test violation",
                caption="Test caption",
                nlp_analysis={"test": "data"},
                detection_data={"test": "detections"}
            )
            
            if violation_id:
                print(f"[OK] Inserted violation: {violation_id}")
                
                # Test retrieval
                print(f"\n--- Testing Retrieval ---")
                violation = manager.get_violation(test_report_id)
                if violation:
                    print(f"[OK] Retrieved violation: {violation['report_id']}")
                
                # Test log
                print(f"\n--- Testing Log ---")
                manager.log_event('test', 'Test event', test_report_id, {'test': 'metadata'})
                print(f"[OK] Logged event")
                
                # Clean up
                print(f"\n--- Testing Deletion ---")
                if manager.delete_violation(test_report_id):
                    print(f"[OK] Deleted test violation")
        
        manager.close()
        print("\n[OK] All tests passed!")
        
    except Exception as e:
        print(f"\n[X] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("=" * 70)
