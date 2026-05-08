"""
Supabase Database Manager
==========================

Handles database operations with Supabase Postgres.
Manages violations in detection_events, violations, and flood_logs tables.
"""

import logging
import os
import json
import re
import time
from functools import wraps
from threading import RLock
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2 import extensions
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
    
    def __init__(self, db_url: str, connect_timeout: Optional[int] = None):
        """
        Initialize Supabase Database Manager.
        
        Args:
            db_url: Postgres connection URL (from Supabase dashboard)
        """
        self.db_url = db_url
        self.connect_timeout = int(connect_timeout if connect_timeout is not None else os.getenv('SUPABASE_DB_CONNECT_TIMEOUT_SECONDS', '10'))
        self.conn = None
        self._operation_lock = RLock()
        self.reconnect_backoff_seconds = max(3, int(os.getenv('SUPABASE_DB_RECONNECT_BACKOFF_SECONDS', '12')))
        self._reconnect_retry_after_epoch = 0.0
        
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
                cursor_factory=RealDictCursor,
                connect_timeout=max(1, int(self.connect_timeout))
            )
            self.conn.autocommit = False
            # Set connection-level statement and lock timeouts so every query on
            # this connection is automatically bounded. Individual methods may
            # override with SET LOCAL inside their own transaction if they need
            # a different budget (e.g. fix_stuck_reports uses its own timeout).
            _stmt_ms = max(1000, int(os.getenv('SUPABASE_DB_STATEMENT_TIMEOUT_MS', '8000')))
            _lock_ms = max(500, int(os.getenv('SUPABASE_DB_LOCK_TIMEOUT_MS', '3000')))
            try:
                with self.conn.cursor() as _cur:
                    _cur.execute("SET statement_timeout = %s", (_stmt_ms,))
                    _cur.execute("SET lock_timeout = %s", (_lock_ms,))
                self.conn.commit()
            except Exception:
                pass  # Non-fatal: some PG editions may reject SET before a tx
            self._reconnect_retry_after_epoch = 0.0
            logger.info(f"Connected to Supabase Postgres (connect_timeout={self.connect_timeout}s, stmt_timeout={_stmt_ms}ms)")
        except Exception as e:
            self._reconnect_retry_after_epoch = time.time() + float(self.reconnect_backoff_seconds)
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def _ensure_connection(self):
        """Ensure database connection is active."""
        if self.conn is None or self.conn.closed:
            now_epoch = time.time()
            if now_epoch < float(self._reconnect_retry_after_epoch or 0.0):
                remaining = max(0, int(self._reconnect_retry_after_epoch - now_epoch))
                raise ConnectionError(f"Database reconnect backoff active ({remaining}s remaining)")
            logger.warning("Database connection lost, reconnecting...")
            self._connect()

    def _safe_rollback(self) -> None:
        """Rollback current transaction if connection is still usable."""
        lock = getattr(self, '_operation_lock', None)
        if lock is not None:
            with lock:
                self._safe_rollback_unlocked()
            return

        self._safe_rollback_unlocked()

    def _safe_rollback_unlocked(self) -> None:
        """Rollback current transaction without acquiring the operation lock."""
        try:
            if self.conn is not None and not self.conn.closed:
                self.conn.rollback()
        except Exception:
            pass

    def _cleanup_transaction_state(self) -> None:
        """Leave the shared psycopg2 connection out of any open/aborted transaction."""
        lock = getattr(self, '_operation_lock', None)
        if lock is not None:
            with lock:
                self._cleanup_transaction_state_unlocked()
            return

        self._cleanup_transaction_state_unlocked()

    def _cleanup_transaction_state_unlocked(self) -> None:
        """Leave the shared psycopg2 connection out of any open tx without locking."""
        try:
            if self.conn is None or self.conn.closed:
                return
            if self.conn.get_transaction_status() != extensions.TRANSACTION_STATUS_IDLE:
                self.conn.rollback()
        except Exception:
            pass

    @staticmethod
    def _is_connection_failure(raw_error: Any) -> bool:
        """Return True when an error indicates network/connection loss."""
        normalized = str(raw_error or '').strip().lower()
        if not normalized:
            return False

        markers = (
            'database reconnect backoff active',
            'could not translate host name',
            'name or service not known',
            'failed to resolve',
            'getaddrinfo failed',
            'server closed the connection unexpectedly',
            'connection refused',
            'connection timed out',
            'timeout expired',
            'network is unreachable',
            'could not connect to server',
            'connection already closed',
            'cursor already closed',
            'broken pipe',
            'ssl syscall error',
            'eof detected',
        )
        return any(marker in normalized for marker in markers)

    def _raise_if_connection_failure(self, raw_error: Any, context: str) -> None:
        """Raise ConnectionError and arm reconnect backoff for transport-level failures."""
        if not self._is_connection_failure(raw_error):
            return

        try:
            if self.conn is not None and not self.conn.closed:
                self.conn.close()
        except Exception:
            pass

        self.conn = None
        self._reconnect_retry_after_epoch = time.time() + float(self.reconnect_backoff_seconds)
        wrapped = ConnectionError(f"{context}: {raw_error}")
        if isinstance(raw_error, Exception):
            raise wrapped from raw_error
        raise wrapped

    @staticmethod
    def _is_unique_constraint_violation(raw_error: Any) -> bool:
        """True when Postgres reports duplicate-key unique-constraint violation."""
        if str(getattr(raw_error, 'pgcode', '') or '').strip() == '23505':
            return True

        normalized = str(raw_error or '').strip().lower()
        if not normalized:
            return False
        return 'duplicate key value violates unique constraint' in normalized

    def _get_existing_detection_event_report_id(self, report_id: str) -> Optional[str]:
        """Fetch existing detection-event report_id for idempotent insert retries."""
        self._ensure_connection()

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT report_id
                    FROM public.detection_events
                    WHERE report_id = %s
                    LIMIT 1
                    """,
                    (report_id,),
                )
                row = cur.fetchone()
                return str((row or {}).get('report_id') or '') if row else None
        except Exception as lookup_error:
            self._safe_rollback()
            self._raise_if_connection_failure(
                lookup_error,
                f'get_existing_detection_event_report_id:{report_id}',
            )
            return None

    def _get_existing_violation_id(self, report_id: str) -> Optional[str]:
        """Fetch existing violations.id for idempotent insert retries."""
        self._ensure_connection()

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM public.violations
                    WHERE report_id = %s
                    LIMIT 1
                    """,
                    (report_id,),
                )
                row = cur.fetchone()
                return str((row or {}).get('id') or '') if row else None
        except Exception as lookup_error:
            self._safe_rollback()
            self._raise_if_connection_failure(
                lookup_error,
                f'get_existing_violation_id:{report_id}',
            )
            return None

    def _normalize_device_id(self, device_id: Optional[str]) -> Optional[str]:
        """Normalize and validate camera device IDs before DB writes."""
        normalized = str(device_id or '').strip()
        if not normalized:
            return None
        if not re.fullmatch(r'[A-Za-z0-9._:-]{1,120}', normalized):
            return None
        return normalized

    def _upsert_device_presence(self, device_id: str, status: str = 'active') -> None:
        """Best-effort heartbeat into public.devices for known camera device IDs."""
        normalized_device_id = self._normalize_device_id(device_id)
        if not normalized_device_id:
            return

        normalized_status = str(status or 'active').strip().lower()
        if normalized_status not in ('active', 'inactive', 'maintenance'):
            normalized_status = 'active'

        self._ensure_connection()

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.devices (device_id, name, status, last_seen, config)
                    VALUES (%s, %s, %s, NOW(), %s)
                    ON CONFLICT (device_id) DO UPDATE
                    SET
                        status = EXCLUDED.status,
                        last_seen = NOW(),
                        config = COALESCE(public.devices.config, '{}'::jsonb) || EXCLUDED.config
                    """,
                    (
                        normalized_device_id,
                        f"Camera {normalized_device_id}",
                        normalized_status,
                        Json({'last_ingest_source': 'casm_backend'})
                    ),
                )

            self.conn.commit()
        except Exception as device_err:
            self.conn.rollback()
            logger.debug(f"Could not upsert device presence for {normalized_device_id}: {device_err}")
    
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
        device_id: Optional[str] = None,
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
            device_id: Optional camera/source device identifier
            status: Processing status (pending/generating/completed/failed)
        
        Returns:
            Report ID if successful, None otherwise
        """
        self._ensure_connection()
        
        normalized_device_id = self._normalize_device_id(device_id)
        insert_attempts = []

        if normalized_device_id:
            insert_attempts.append((
                """
                INSERT INTO public.detection_events
                (report_id, timestamp, device_id, person_count, violation_count, severity, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING report_id
                """,
                (report_id, timestamp, normalized_device_id, person_count, violation_count, severity, status),
            ))
            insert_attempts.append((
                """
                INSERT INTO public.detection_events
                (report_id, timestamp, device_id, person_count, violation_count, severity)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING report_id
                """,
                (report_id, timestamp, normalized_device_id, person_count, violation_count, severity),
            ))

        insert_attempts.append((
            """
            INSERT INTO public.detection_events
            (report_id, timestamp, person_count, violation_count, severity, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING report_id
            """,
            (report_id, timestamp, person_count, violation_count, severity, status),
        ))
        insert_attempts.append((
            """
            INSERT INTO public.detection_events
            (report_id, timestamp, person_count, violation_count, severity)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING report_id
            """,
            (report_id, timestamp, person_count, violation_count, severity),
        ))

        result = None
        last_error = None
        for query, params in insert_attempts:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(query, params)
                    result = cur.fetchone()
                self.conn.commit()
                break
            except Exception as attempt_error:
                self._safe_rollback()
                if self._is_unique_constraint_violation(attempt_error):
                    existing_report_id = self._get_existing_detection_event_report_id(report_id)
                    if existing_report_id:
                        logger.info(
                            f"Detection event already exists for {report_id}; "
                            "using existing row"
                        )
                        return existing_report_id
                last_error = attempt_error
                result = None

        if not result:
            self._raise_if_connection_failure(last_error, 'insert_detection_event')
            logger.error(f"Failed to insert detection event: {last_error}")
            return None

        if normalized_device_id:
            self._upsert_device_presence(normalized_device_id)

        logger.info(
            f"Inserted detection event: {report_id} "
            f"(status: {status}, device_id: {normalized_device_id or 'n/a'})"
        )
        return result['report_id'] if result else None
    
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
                    # Clear stale error_message when transitioning to healthy/in-progress states.
                    if str(status).lower() in ('pending', 'generating', 'completed', 'partial', 'skipped'):
                        cur.execute("""
                            UPDATE public.detection_events 
                            SET status = %s, error_message = NULL, updated_at = NOW()
                            WHERE report_id = %s
                        """, (status, report_id))
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'update_detection_status')
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'update_detection_event')
            logger.error(f"Failed to update detection event: {e}")
            return False
    
    def fix_stuck_reports(self) -> int:
        """
        Fix reports stuck in pending/generating status by checking actual data.

        Decision table (evaluated in order):
        - Has report_html_key                           -> completed
        - Has original_image_key (recoverable in cloud) -> leave as-is; cloud
          recovery sweep will auto-enqueue (don't mark failed)
        - Has violation record, no recoverable image,
          older than STUCK_REPORT_AGE_MINUTES           -> failed
        - No violation record at all,
          older than STUCK_REPORT_AGE_MINUTES           -> failed

        Returns:
            Number of reports fixed
        """
        self._ensure_connection()
        fixed_count = 0
        statement_timeout_ms = int(os.getenv('SUPABASE_DB_STATEMENT_TIMEOUT_MS', '10000'))
        lock_timeout_ms = int(os.getenv('SUPABASE_DB_LOCK_TIMEOUT_MS', '2000'))
        sweep_limit = max(1, min(1000, int(os.getenv('STUCK_REPORT_SWEEP_LIMIT', '200') or 200)))
        # How long a report must be stuck before we declare it failed.
        # Default 20 min -- long enough to survive Railway cold-start + worker
        # startup, which previously caused all in-flight reports to be swept to
        # 'failed' immediately after every deployment/restart.
        stuck_age_minutes = max(5, int(os.getenv('STUCK_REPORT_AGE_MINUTES', '20') or 20))

        try:
            with self.conn.cursor() as cur:
                # Avoid blocking startup indefinitely on locks/slow queries.
                cur.execute("SET LOCAL statement_timeout = %s", (statement_timeout_ms,))
                cur.execute("SET LOCAL lock_timeout = %s", (lock_timeout_ms,))

                # Only one backend process should run the status repair sweep at a time.
                # The row locks below also skip reports currently being generated.
                cur.execute(
                    "SELECT pg_try_advisory_xact_lock(%s, %s) AS lock_acquired",
                    (4240006, 260507),
                )
                lock_row = cur.fetchone() or {}
                if not bool(lock_row.get('lock_acquired')):
                    self.conn.rollback()
                    logger.info("Skipped stuck report sweep because another backend holds the repair lock")
                    return 0

                # Scan pending/generating/unknown AND failed. A report already
                # marked failed that actually has report_html_key must be
                # promoted back to completed. FOR UPDATE SKIP LOCKED prevents
                # startup repair from fighting active report generation.
                cur.execute(
                    """
                    WITH candidate_rows AS MATERIALIZED (
                        SELECT
                            de.report_id,
                            de.status AS old_status,
                            CASE
                                WHEN v.report_html_key IS NOT NULL THEN 'completed'
                                WHEN v.original_image_key IS NOT NULL THEN NULL
                                WHEN v.id IS NOT NULL
                                     AND v.annotated_image_key IS NOT NULL
                                     AND de.timestamp < NOW() - (INTERVAL '1 minute' * %s)
                                    THEN 'partial'
                                WHEN v.id IS NOT NULL
                                     AND v.original_image_key IS NULL
                                     AND de.timestamp < NOW() - (INTERVAL '1 minute' * %s)
                                    THEN 'failed'
                                WHEN v.id IS NULL
                                     AND de.timestamp < NOW() - (INTERVAL '1 minute' * %s)
                                    THEN 'failed'
                                ELSE NULL
                            END AS new_status
                        FROM public.detection_events de
                        LEFT JOIN public.violations v ON de.report_id = v.report_id
                        WHERE de.status IS NULL
                           OR de.status IN ('pending', 'generating', 'unknown', 'failed', 'partial')
                        ORDER BY de.timestamp ASC NULLS LAST
                        LIMIT %s
                        FOR UPDATE OF de SKIP LOCKED
                    ),
                    updated_rows AS (
                        UPDATE public.detection_events AS de
                        SET status = candidate_rows.new_status,
                            updated_at = NOW()
                        FROM candidate_rows
                        WHERE de.report_id = candidate_rows.report_id
                          AND candidate_rows.new_status IS NOT NULL
                          AND de.status IS DISTINCT FROM candidate_rows.new_status
                        RETURNING
                            de.report_id,
                            candidate_rows.old_status,
                            de.status AS new_status
                    )
                    SELECT report_id, old_status, new_status
                    FROM updated_rows
                    """,
                    (stuck_age_minutes, stuck_age_minutes, stuck_age_minutes, sweep_limit),
                )

                updated_rows = cur.fetchall()
                fixed_count = len(updated_rows)
                for row in updated_rows[:20]:
                    logger.info(
                        f"Fixed stuck report {row['report_id']}: "
                        f"{row['old_status']} -> {row['new_status']}"
                    )
                if fixed_count > 20:
                    logger.info(f"Fixed {fixed_count - 20} additional stuck reports")

                self.conn.commit()
                logger.info(f"Fixed {fixed_count} stuck reports")

        except Exception as e:
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'fix_stuck_reports')
            logger.warning(f"Could not fix stuck reports: {e}")
        finally:
            self._cleanup_transaction_state()

        return fixed_count

    def get_cloud_pending_recovery_candidates(
        self,
        min_age_minutes: int = 20,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Return stuck pending/generating reports that have an original image in
        cloud storage but no report HTML yet.  These are safely recoverable by
        downloading the image and re-running the report worker.

        Args:
            min_age_minutes: Minimum age (minutes) before a report is
                considered stalled and eligible for recovery.
            limit: Maximum number of candidates to return per call.

        Returns:
            List of dicts with keys: report_id, original_image_key,
            annotated_image_key, detection_data, timestamp, status.
        """
        self._ensure_connection()
        statement_timeout_ms = int(os.getenv('SUPABASE_DB_STATEMENT_TIMEOUT_MS', '10000'))
        lock_timeout_ms = int(os.getenv('SUPABASE_DB_LOCK_TIMEOUT_MS', '5000'))
        safe_limit = max(1, min(50, int(limit)))

        try:
            with self.conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = %s", (statement_timeout_ms,))
                cur.execute("SET LOCAL lock_timeout = %s", (lock_timeout_ms,))
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
                    WHERE (de.status IS NULL OR de.status IN
                           ('pending', 'generating', 'unknown', 'failed', 'partial'))
                      AND v.original_image_key IS NOT NULL
                      AND v.report_html_key IS NULL
                      AND (
                          de.timestamp < NOW() - (INTERVAL '1 minute' * %s)
                          OR v.detection_data->>'sync_source' IN (
                              'sync_local_cache_partial',
                              'browser_local_draft_handoff',
                              'cloud_pending_local_handoff'
                          )
                      )
                      AND (
                          (
                              (
                                  v.detection_data IS NULL
                                  OR v.detection_data->>'source_scope' IS NULL
                                  OR v.detection_data->>'source_scope' = 'cloud'
                              )
                              AND (
                                  v.detection_data IS NULL
                                  OR v.detection_data->>'sync_source' IS NULL
                                  OR v.detection_data->>'sync_source' NOT IN (
                                      'sync_local_cache', 'local_cache', 'local_cache_sync',
                                      'local_pending_recovery', 'local', 'auto_reconnect'
                                  )
                              )
                          )
                          OR (
                              v.detection_data->>'sync_source' IN (
                                  'sync_local_cache_partial',
                                  'browser_local_draft_handoff',
                                  'cloud_pending_local_handoff'
                              )
                          )
                      )
                    ORDER BY de.timestamp ASC
                    LIMIT %s
                """, (min_age_minutes, safe_limit))
                rows = cur.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'get_cloud_pending_recovery_candidates')
            logger.warning(f"get_cloud_pending_recovery_candidates failed: {e}")
            return []
    
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, f'get_detection_event:{report_id}')
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
        _stmt_ms = max(1000, int(os.getenv('SUPABASE_DB_STATEMENT_TIMEOUT_MS', '8000')))
        try:
            with self.conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = %s", (_stmt_ms,))
                cur.execute("""
                    SELECT * FROM public.detection_events
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (limit,))
                
                results = cur.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'get_recent_detection_events')
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
        _stmt_ms = max(1000, int(os.getenv('SUPABASE_DB_STATEMENT_TIMEOUT_MS', '8000')))
        try:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = %s", (_stmt_ms,))
                    cur.execute("SET LOCAL lock_timeout = %s", (max(500, _stmt_ms // 2),))
                    cur.execute("""
                        SELECT 
                            de.report_id,
                            de.timestamp,
                            de.person_count,
                            de.violation_count,
                            de.severity,
                            de.status,
                            de.error_message,
                            de.device_id,
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
            except Exception as primary_query_error:
                self._safe_rollback()
                self._raise_if_connection_failure(
                    primary_query_error,
                    'get_all_violations_with_status.primary_query'
                )
                with self.conn.cursor() as fallback_cur:
                    fallback_cur.execute("SET LOCAL statement_timeout = %s", (_stmt_ms,))
                    fallback_cur.execute("""
                        SELECT 
                            de.report_id,
                            de.timestamp,
                            de.person_count,
                            de.violation_count,
                            de.severity,
                            'unknown' as status,
                            NULL as error_message,
                            de.device_id,
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
                    results = fallback_cur.fetchall()
                    return [dict(row) for row in results]

        except Exception as e:
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'get_all_violations_with_status')
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
        report_pdf_key: Optional[str] = None,
        device_id: Optional[str] = None,
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
            device_id: Optional camera/source device identifier
        
        Returns:
            UUID of inserted violation or None
        """
        self._ensure_connection()
        
        normalized_device_id = self._normalize_device_id(device_id)

        insert_attempts = []
        if normalized_device_id:
            insert_attempts.append((
                """
                INSERT INTO public.violations
                (report_id, violation_summary, caption, nlp_analysis, detection_data,
                 original_image_key, annotated_image_key, report_html_key, report_pdf_key, device_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    report_id,
                    violation_summary,
                    caption,
                    Json(nlp_analysis) if nlp_analysis else None,
                    Json(detection_data) if detection_data else None,
                    original_image_key,
                    annotated_image_key,
                    report_html_key,
                    report_pdf_key,
                    normalized_device_id,
                ),
            ))

        insert_attempts.append((
            """
            INSERT INTO public.violations
            (report_id, violation_summary, caption, nlp_analysis, detection_data,
             original_image_key, annotated_image_key, report_html_key, report_pdf_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                report_id,
                violation_summary,
                caption,
                Json(nlp_analysis) if nlp_analysis else None,
                Json(detection_data) if detection_data else None,
                original_image_key,
                annotated_image_key,
                report_html_key,
                report_pdf_key,
            ),
        ))

        result = None
        last_error = None
        for query, params in insert_attempts:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(query, params)
                    result = cur.fetchone()
                self.conn.commit()
                break
            except Exception as attempt_error:
                self._safe_rollback()
                if self._is_unique_constraint_violation(attempt_error):
                    existing_violation_id = self._get_existing_violation_id(report_id)
                    if existing_violation_id:
                        logger.info(
                            f"Violation already exists for {report_id}; using existing row"
                        )
                        if normalized_device_id:
                            self._upsert_device_presence(normalized_device_id)
                        return existing_violation_id
                last_error = attempt_error
                result = None

        if not result:
            self._raise_if_connection_failure(last_error, 'insert_violation')
            logger.error(f"Failed to insert violation: {last_error}")
            return None

        if normalized_device_id:
            self._upsert_device_presence(normalized_device_id)

        logger.info(
            f"Inserted violation: {report_id} "
            f"(device_id: {normalized_device_id or 'n/a'})"
        )
        return str(result['id']) if result else None
    
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, f'get_violation:{report_id}')
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'get_recent_violations')
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'update_violation_storage_keys')
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'update_violation')
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'delete_violation')
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
        device_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log a system event to flood_logs table.
        
        Args:
            event_type: Event type (e.g., 'upload', 'error', 'violation')
            message: Event message
            report_id: Associated report ID (optional)
            device_id: Optional camera/source device identifier
            metadata: Additional metadata (stored as JSONB)
        
        Returns:
            True if successful, False otherwise
        """
        self._ensure_connection()
        
        normalized_device_id = self._normalize_device_id(device_id)

        insert_attempts = []
        if normalized_device_id:
            insert_attempts.append((
                """
                INSERT INTO public.flood_logs
                (event_type, report_id, device_id, message, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    event_type,
                    report_id,
                    normalized_device_id,
                    message,
                    Json(metadata) if metadata else None,
                ),
            ))

        insert_attempts.append((
            """
            INSERT INTO public.flood_logs
            (event_type, report_id, message, metadata)
            VALUES (%s, %s, %s, %s)
            """,
            (
                event_type,
                report_id,
                message,
                Json(metadata) if metadata else None,
            ),
        ))

        last_error = None
        for query, params in insert_attempts:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(query, params)
                self.conn.commit()
                logger.debug(
                    f"Logged event: {event_type} "
                    f"(device_id: {normalized_device_id or 'n/a'})"
                )
                if normalized_device_id:
                    self._upsert_device_presence(normalized_device_id)
                return True
            except Exception as attempt_error:
                self._safe_rollback()
                last_error = attempt_error

        self._raise_if_connection_failure(last_error, 'log_event')
        logger.error(f"Failed to log event: {last_error}")
        return False

    def get_device_stats(self, device_id: str) -> Dict[str, Any]:
        """Get aggregated status/severity counters for one camera device_id."""
        self._ensure_connection()

        normalized_device_id = self._normalize_device_id(device_id)
        if not normalized_device_id:
            return {
                'device_id': str(device_id or '').strip(),
                'total': 0,
                'completed': 0,
                'pending': 0,
                'failed': 0,
                'critical': 0,
                'high': 0,
                'last_detection': None,
                'error': 'Invalid device_id format',
            }

        try:
            with self.conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*)::BIGINT AS total,
                            COUNT(*) FILTER (WHERE status = 'completed')::BIGINT AS completed,
                            COUNT(*) FILTER (WHERE status IN ('pending', 'generating'))::BIGINT AS pending,
                            COUNT(*) FILTER (WHERE status = 'failed')::BIGINT AS failed,
                            COUNT(*) FILTER (WHERE severity = 'CRITICAL')::BIGINT AS critical,
                            COUNT(*) FILTER (WHERE severity = 'HIGH')::BIGINT AS high,
                            MAX(timestamp) AS last_detection
                        FROM public.detection_events
                        WHERE device_id = %s
                        """,
                        (normalized_device_id,),
                    )
                except Exception as primary_query_error:
                    self._safe_rollback()
                    self._raise_if_connection_failure(
                        primary_query_error,
                        f'get_device_stats.primary_query:{normalized_device_id}'
                    )
                    with self.conn.cursor() as fallback_cur:
                        fallback_cur.execute(
                            """
                            SELECT
                                COUNT(*)::BIGINT AS total,
                                0::BIGINT AS completed,
                                0::BIGINT AS pending,
                                0::BIGINT AS failed,
                                COUNT(*) FILTER (WHERE severity = 'CRITICAL')::BIGINT AS critical,
                                COUNT(*) FILTER (WHERE severity = 'HIGH')::BIGINT AS high,
                                MAX(timestamp) AS last_detection
                            FROM public.detection_events
                            WHERE device_id = %s
                            """,
                            (normalized_device_id,),
                        )
                        row = fallback_cur.fetchone() or {}
                        return {
                            'device_id': normalized_device_id,
                            'total': int(row.get('total') or 0),
                            'completed': int(row.get('completed') or 0),
                            'pending': int(row.get('pending') or 0),
                            'failed': int(row.get('failed') or 0),
                            'critical': int(row.get('critical') or 0),
                            'high': int(row.get('high') or 0),
                            'last_detection': row.get('last_detection').isoformat() if row.get('last_detection') else None,
                        }

                row = cur.fetchone() or {}
                return {
                    'device_id': normalized_device_id,
                    'total': int(row.get('total') or 0),
                    'completed': int(row.get('completed') or 0),
                    'pending': int(row.get('pending') or 0),
                    'failed': int(row.get('failed') or 0),
                    'critical': int(row.get('critical') or 0),
                    'high': int(row.get('high') or 0),
                    'last_detection': row.get('last_detection').isoformat() if row.get('last_detection') else None,
                }
        except Exception as e:
            self._safe_rollback()
            self._raise_if_connection_failure(e, f'get_device_stats:{normalized_device_id}')
            logger.error(f"Failed to get device stats for {normalized_device_id}: {e}")
            return {
                'device_id': normalized_device_id,
                'total': 0,
                'completed': 0,
                'pending': 0,
                'failed': 0,
                'critical': 0,
                'high': 0,
                'last_detection': None,
                'error': str(e),
            }
    
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
            self._safe_rollback()
            self._raise_if_connection_failure(e, 'get_recent_logs')
            logger.error(f"Failed to get recent logs: {e}")
            return []


def _serialize_db_operation(method):
    """Serialize access to the shared psycopg2 connection and clean aborted tx state."""
    @wraps(method)
    def _wrapped(self, *args, **kwargs):
        lock = getattr(self, '_operation_lock', None)
        if lock is None:
            return method(self, *args, **kwargs)

        with lock:
            try:
                return method(self, *args, **kwargs)
            except Exception:
                self._safe_rollback()
                raise
            finally:
                self._cleanup_transaction_state()

    return _wrapped


for _db_method_name in (
    '_get_existing_detection_event_report_id',
    '_get_existing_violation_id',
    '_upsert_device_presence',
    'insert_detection_event',
    'update_detection_status',
    'update_detection_event',
    'fix_stuck_reports',
    'get_cloud_pending_recovery_candidates',
    'get_detection_event',
    'get_recent_detection_events',
    'get_all_violations_with_status',
    'insert_violation',
    'get_violation',
    'get_recent_violations',
    'update_violation_storage_keys',
    'update_violation',
    'delete_violation',
    'log_event',
    'get_device_stats',
    'get_recent_logs',
):
    setattr(
        SupabaseDatabaseManager,
        _db_method_name,
        _serialize_db_operation(getattr(SupabaseDatabaseManager, _db_method_name)),
    )


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

    normalized = str(db_url or '').strip().lower()
    placeholder_markers = (
        'your-project-id',
        'your-db-password',
        'example.supabase.co',
    )

    if not db_url or any(marker in normalized for marker in placeholder_markers):
        raise ValueError("SUPABASE_DB_URL must be set to a real project connection string")
    
    connect_timeout = int(os.getenv('SUPABASE_DB_CONNECT_TIMEOUT_SECONDS', '10'))
    return SupabaseDatabaseManager(db_url, connect_timeout=connect_timeout)


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
