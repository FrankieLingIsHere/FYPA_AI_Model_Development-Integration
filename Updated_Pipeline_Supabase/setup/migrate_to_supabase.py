"""
Migration Script: SQLite → Supabase
====================================

Migrates existing violation reports from the local SQLite database
to Supabase Postgres + Storage.

Usage:
    python migrate_to_supabase.py [--dry-run] [--limit N]
    
Options:
    --dry-run: Preview what would be migrated without actually migrating
    --limit N: Only migrate the first N violations (for testing)
"""
# Readability: Setup helper: prepare project dependencies, data, or cloud resources.

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import json
from dotenv import load_dotenv

# Add project root to path (file is in setup/, project root is parent dir)
# Trigger the side effect required for this stage.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
from pipeline.backend.core.supabase_db import create_db_manager_from_env

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# Prepare logger for the next step.
logger = logging.getLogger(__name__)


# Section: group sqlite to supabase migrator state and behaviour in one readable unit.
class SQLiteToSupabaseMigrator:
    """Migrates violations from SQLite to Supabase."""
    
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, sqlite_db_path: str, violations_dir: str):
        """
        Initialize migrator.
        
        Args:
            sqlite_db_path: Path to SQLite database file
            violations_dir: Path to local violations directory
        """
        # Prepare sqlite db path for the next step.
        self.sqlite_db_path = Path(sqlite_db_path)
        self.violations_dir = Path(violations_dir)
        
        # Initialize Supabase managers
        self.storage_manager = create_storage_manager_from_env()
        self.db_manager = create_db_manager_from_env()
        
        logger.info(f"SQLite DB: {self.sqlite_db_path}")
        logger.info(f"Violations dir: {self.violations_dir}")
    
    # Section: run the get sqlite violations workflow with clear inputs and outputs.
    def get_sqlite_violations(self) -> List[Dict[str, Any]]:
        """Fetch all violations from SQLite database."""
        # Choose the correct branch before the workflow continues.
        if not self.sqlite_db_path.exists():
            # Trigger the side effect required for this stage.
            logger.error(f"SQLite database not found: {self.sqlite_db_path}")
            return []
        
        try:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM violations ORDER BY created_at DESC")
            # Prepare rows for the next step.
            rows = cursor.fetchall()
            
            violations = []
            for row in rows:
                # Prepare violation for the next step.
                violation = dict(row)
                
                # Parse JSON fields
                if violation.get('nlp_analysis'):
                    try:
                        violation['nlp_analysis'] = json.loads(violation['nlp_analysis'])
                    except:
                        pass
                
                # Choose the correct branch before the workflow continues.
                if violation.get('detection_data'):
                    try:
                        violation['detection_data'] = json.loads(violation['detection_data'])
                    except:
                        pass
                
                violations.append(violation)
            
            # Trigger the side effect required for this stage.
            conn.close()
            logger.info(f"Found {len(violations)} violations in SQLite")
            return violations
            
        except Exception as e:
            logger.error(f"Error reading SQLite database: {e}")
            return []
    
    # Section: run the migrate violation workflow with clear inputs and outputs.
    def migrate_violation(self, violation: Dict[str, Any], dry_run: bool = False) -> bool:
        """
        Migrate a single violation to Supabase.
        
        Args:
            violation: Violation dictionary from SQLite
            dry_run: If True, only preview without actually migrating
        
        Returns:
            True if successful, False otherwise
        """
        # Prepare report id for the next step.
        report_id = violation['report_id']
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Migrating: {report_id}")
        
        if dry_run:
            # Return the prepared result to the caller.
            return True
        
        try:
            # Step 1: Insert detection event
            timestamp = datetime.fromisoformat(violation['timeframe'])
            
            detection_result = self.db_manager.insert_detection_event(
                report_id=report_id,
                timestamp=timestamp,
                person_count=violation.get('person_count', 0),
                violation_count=violation.get('violation_count', 0),
                severity='HIGH'  # Default severity
            )
            
            # Choose the correct branch before the workflow continues.
            if not detection_result:
                # Trigger the side effect required for this stage.
                logger.error(f"Failed to insert detection event: {report_id}")
                return False
            
            # Step 2: Upload files to Supabase Storage
            violation_dir = self.violations_dir / report_id
            
            original_image = violation_dir / 'original.jpg'
            annotated_image = violation_dir / 'annotated.jpg'
            # Prepare report html for the next step.
            report_html = violation_dir / 'report.html'
            report_pdf = violation_dir / 'report.pdf'
            
            upload_results = self.storage_manager.upload_violation_artifacts(
                report_id=report_id,
                original_image_path=original_image if original_image.exists() else None,
                annotated_image_path=annotated_image if annotated_image.exists() else None,
                report_html_path=report_html if report_html.exists() else None,
                report_pdf_path=report_pdf if report_pdf.exists() else None
            )
            
            # Step 3: Insert violation record
            # Prepare violation id for the next step.
            violation_id = self.db_manager.insert_violation(
                report_id=report_id,
                violation_summary=violation.get('violation_summary'),
                caption=violation.get('caption'),
                nlp_analysis=violation.get('nlp_analysis'),
                detection_data=violation.get('detection_data'),
                original_image_key=upload_results.get('original_image_key'),
                annotated_image_key=upload_results.get('annotated_image_key'),
                report_html_key=upload_results.get('report_html_key'),
                report_pdf_key=upload_results.get('report_pdf_key')
            )
            
            # Choose the correct branch before the workflow continues.
            if violation_id:
                # Trigger the side effect required for this stage.
                logger.info(f"✓ Migrated: {report_id}")
                return True
            else:
                logger.error(f"Failed to insert violation: {report_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error migrating {report_id}: {e}")
            # Return the prepared result to the caller.
            return False
    
    # Section: run the migrate all workflow with clear inputs and outputs.
    def migrate_all(self, limit: int = None, dry_run: bool = False):
        """
        Migrate all violations from SQLite to Supabase.
        
        Args:
            limit: Maximum number of violations to migrate
            dry_run: If True, only preview without actually migrating
        """
        # Prepare violations for the next step.
        violations = self.get_sqlite_violations()
        
        if limit:
            # Prepare violations for the next step.
            violations = violations[:limit]
            logger.info(f"Limited to first {limit} violations")
        
        if dry_run:
            logger.info("=" * 70)
            logger.info("DRY RUN MODE - No changes will be made")
            logger.info("=" * 70)
        
        # Prepare total for the next step.
        total = len(violations)
        success_count = 0
        
        for i, violation in enumerate(violations, 1):
            # Trigger the side effect required for this stage.
            logger.info(f"\n[{i}/{total}] Processing {violation['report_id']}")
            
            if self.migrate_violation(violation, dry_run):
                success_count += 1
        
        # Trigger the side effect required for this stage.
        logger.info("\n" + "=" * 70)
        logger.info("MIGRATION SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total violations: {total}")
        logger.info(f"Successfully migrated: {success_count}")
        logger.info(f"Failed: {total - success_count}")
        logger.info("=" * 70)


# Section: run the main workflow with clear inputs and outputs.
def main():
    """Main entry point."""
    # Prepare parser for the next step.
    parser = argparse.ArgumentParser(description='Migrate violations from SQLite to Supabase')
    parser.add_argument('--dry-run', action='store_true', help='Preview migration without making changes')
    parser.add_argument('--limit', type=int, help='Limit number of violations to migrate')
    parser.add_argument('--sqlite-db', default='../Updated_Pipeline/pipeline/violations.db', 
                       help='Path to SQLite database')
    parser.add_argument('--violations-dir', default='../Updated_Pipeline/pipeline/violations',
                       help='Path to violations directory')
    
    args = parser.parse_args()
    
    # Load environment variables
    # Trigger the side effect required for this stage.
    load_dotenv()
    
    print("=" * 70)
    print("SQLite → Supabase Migration Tool")
    print("=" * 70)
    
    try:
        # Prepare migrator for the next step.
        migrator = SQLiteToSupabaseMigrator(
            sqlite_db_path=args.sqlite_db,
            violations_dir=args.violations_dir
        )
        
        migrator.migrate_all(limit=args.limit, dry_run=args.dry_run)
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        # Trigger the side effect required for this stage.
        traceback.print_exc()
        return 1
    
    # Return the prepared result to the caller.
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == '__main__':
    exit(main())
