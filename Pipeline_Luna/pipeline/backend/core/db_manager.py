"""
Database Manager - Simplified database access wrapper
======================================================
Simple interface for database operations used throughout the pipeline.
Automatically handles connection management and error handling.

Usage:
    from pipeline.backend.core.db_manager import db_manager
    
    # Insert violation
    report_id = db_manager.save_violation(violation_data)
    
    # Retrieve violation
    violation = db_manager.get_violation(report_id)
    
    # Get recent violations
    recent = db_manager.get_recent(limit=5)
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))

from config import DATABASE_CONFIG
from pipeline.backend.core.database import get_database, DatabaseInterface

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Simplified database manager with automatic connection handling."""
    
    def __init__(self):
        self.config = DATABASE_CONFIG
        self.db: Optional[DatabaseInterface] = None
        self._connected = False
        
        # Initialize database if enabled
        if self.config.get('enabled', False):
            self._initialize()
        else:
            # Always use SQLite fallback for development
            logger.info("Database not enabled in config, using SQLite fallback")
            self.config['type'] = 'sqlite'
            self._initialize()
    
    def _initialize(self):
        """Initialize database connection."""
        try:
            self.db = get_database(self.config)
            self.db.connect()
            self._connected = True
            logger.info(f"Database manager initialized: {self.config.get('type', 'sqlite')}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            logger.warning("Database operations will fail - check configuration")
            self._connected = False
    
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._connected and self.db is not None
    
    def save_violation(self, violation_data: Dict[str, Any]) -> Optional[str]:
        """
        Save a violation to the database.
        
        Args:
            violation_data: Dictionary with violation information
                Required: report_id, timeframe
                Optional: violation_summary, person_count, violation_count,
                         image_path, annotated_image_path, caption, nlp_analysis,
                         report_html_path, report_pdf_path, detection_data
        
        Returns:
            report_id if successful, None if failed
        """
        if not self.is_connected():
            logger.warning("Database not connected, cannot save violation")
            return None
        
        try:
            return self.db.insert_violation(violation_data)
        except Exception as e:
            logger.error(f"Failed to save violation: {e}")
            return None
    
    def get_violation(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a violation by report_id.
        
        Args:
            report_id: Unique report identifier
        
        Returns:
            Violation data dictionary or None if not found
        """
        if not self.is_connected():
            logger.warning("Database not connected, cannot retrieve violation")
            return None
        
        try:
            return self.db.get_violation(report_id)
        except Exception as e:
            logger.error(f"Failed to retrieve violation {report_id}: {e}")
            return None
    
    def get_violations_by_timeframe(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        """
        Retrieve violations within a timeframe.
        
        Args:
            start: Start datetime
            end: End datetime
        
        Returns:
            List of violation dictionaries
        """
        if not self.is_connected():
            logger.warning("Database not connected, cannot retrieve violations")
            return []
        
        try:
            return self.db.get_violations_by_timeframe(start, end)
        except Exception as e:
            logger.error(f"Failed to retrieve violations by timeframe: {e}")
            return []
    
    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve most recent violations.
        
        Args:
            limit: Maximum number of violations to retrieve
        
        Returns:
            List of violation dictionaries
        """
        if not self.is_connected():
            logger.warning("Database not connected, cannot retrieve violations")
            return []
        
        try:
            return self.db.get_recent_violations(limit)
        except Exception as e:
            logger.error(f"Failed to retrieve recent violations: {e}")
            return []
    
    def update_violation(self, report_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a violation record.
        
        Args:
            report_id: Report to update
            updates: Dictionary of fields to update
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning("Database not connected, cannot update violation")
            return False
        
        try:
            return self.db.update_violation(report_id, updates)
        except Exception as e:
            logger.error(f"Failed to update violation {report_id}: {e}")
            return False
    
    def delete_violation(self, report_id: str) -> bool:
        """
        Delete a violation record.
        
        Args:
            report_id: Report to delete
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning("Database not connected, cannot delete violation")
            return False
        
        try:
            return self.db.delete_violation(report_id)
        except Exception as e:
            logger.error(f"Failed to delete violation {report_id}: {e}")
            return False
    
    def close(self):
        """Close database connection."""
        if self.db and self._connected:
            self.db.disconnect()
            self._connected = False
            logger.info("Database connection closed")


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

# Singleton instance for easy access throughout the application
db_manager = DatabaseManager()

# Cleanup on module unload
import atexit
atexit.register(db_manager.close)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("DATABASE MANAGER TEST")
    print("=" * 70)
    
    # Test connection
    print(f"\nConnected: {db_manager.is_connected()}")
    print(f"Database type: {db_manager.config.get('type', 'unknown')}")
    
    # Test insert
    print("\n--- Testing Insert ---")
    test_violation = {
        'report_id': f'TEST_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
        'timeframe': datetime.now(),
        'violation_summary': 'Test violation for database manager',
        'person_count': 2,
        'violation_count': 3,
        'caption': 'Test image caption',
    }
    
    report_id = db_manager.save_violation(test_violation)
    if report_id:
        print(f"[OK] Saved violation: {report_id}")
    else:
        print("[X] Failed to save violation")
    
    # Test retrieve
    if report_id:
        print("\n--- Testing Retrieve ---")
        violation = db_manager.get_violation(report_id)
        if violation:
            print(f"[OK] Retrieved violation: {violation['report_id']}")
            print(f"   Summary: {violation.get('violation_summary')}")
            print(f"   Persons: {violation.get('person_count')}")
            print(f"   Violations: {violation.get('violation_count')}")
        else:
            print("[X] Failed to retrieve violation")
    
    # Test recent
    print("\n--- Testing Recent Violations ---")
    recent = db_manager.get_recent(limit=5)
    print(f"[OK] Found {len(recent)} recent violations")
    for v in recent[:3]:  # Show first 3
        print(f"   - {v['report_id']}: {v.get('violation_summary', 'No summary')}")
    
    # Test update
    if report_id:
        print("\n--- Testing Update ---")
        success = db_manager.update_violation(report_id, {
            'violation_summary': 'UPDATED: Test violation'
        })
        if success:
            print(f"[OK] Updated violation: {report_id}")
            updated = db_manager.get_violation(report_id)
            print(f"   New summary: {updated.get('violation_summary')}")
        else:
            print("[X] Failed to update violation")
    
    # Test delete
    if report_id:
        print("\n--- Testing Delete ---")
        success = db_manager.delete_violation(report_id)
        if success:
            print(f"[OK] Deleted violation: {report_id}")
        else:
            print("[X] Failed to delete violation")
    
    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)
