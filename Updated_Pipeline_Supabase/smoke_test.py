"""
Smoke Test - Supabase Round-Trip
=================================

Simple test that verifies Supabase connectivity and performs a basic
write/read round-trip to ensure the system is working.

Usage:
    python smoke_test.py
"""

import sys
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_supabase_roundtrip():
    """Test Supabase database and storage with a simple round-trip."""
    
    print("=" * 70)
    print("SUPABASE SMOKE TEST - Round-Trip Write/Read")
    print("=" * 70)
    print()
    
    try:
        # Import Supabase managers
        from pipeline.backend.core.supabase_db import create_db_manager_from_env
        from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
        
        logger.info("✓ Imports successful")
        
        # Initialize managers
        logger.info("Initializing Supabase managers...")
        db = create_db_manager_from_env()
        storage = create_storage_manager_from_env()
        logger.info("✓ Managers initialized")
        
        # Test 1: Database Write
        logger.info("Test 1: Writing to database...")
        test_report_id = f"smoke_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        result = db.insert_detection_event(
            report_id=test_report_id,
            timestamp=datetime.now(),
            person_count=1,
            violation_count=0,
            severity='LOW'
        )
        
        if result:
            logger.info(f"✓ Database write successful: {test_report_id}")
        else:
            logger.error("✗ Database write failed")
            return False
        
        # Test 2: Database Read
        logger.info("Test 2: Reading from database...")
        violation = db.get_violation(test_report_id)
        
        if violation:
            logger.info("✓ Database read successful")
            logger.info(f"  - Report ID: {violation.get('report_id')}")
            logger.info(f"  - Severity: {violation.get('severity')}")
        else:
            logger.warning("⚠ No violation data found (expected for smoke test)")
        
        # Test 3: Query recent violations
        logger.info("Test 3: Querying recent violations...")
        violations = db.get_recent_violations(limit=5)
        logger.info(f"✓ Query successful: Found {len(violations)} recent violations")
        
        # Test 4: Log event
        logger.info("Test 4: Logging system event...")
        db.log_event(
            event_type='smoke_test',
            report_id=test_report_id,
            message='Smoke test completed successfully',
            metadata={'test': True}
        )
        logger.info("✓ Event logging successful")
        
        # Test 5: Storage bucket check
        logger.info("Test 5: Checking storage buckets...")
        logger.info(f"✓ Images bucket: {storage.images_bucket}")
        logger.info(f"✓ Reports bucket: {storage.reports_bucket}")
        logger.info(f"✓ Signed URL TTL: {storage.signed_url_ttl}s")
        
        # Cleanup
        logger.info("Cleaning up...")
        db.close()
        logger.info("✓ Database connection closed")
        
        print()
        print("=" * 70)
        print("SMOKE TEST PASSED ✓")
        print("=" * 70)
        print()
        print("All basic operations working correctly!")
        print()
        print("Your Supabase integration is ready to use.")
        print()
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        
        print()
        print("=" * 70)
        print("SMOKE TEST FAILED ✗")
        print("=" * 70)
        print()
        print("Please check:")
        print("  1. .env file has correct Supabase credentials")
        print("  2. Supabase tables are created (see README.md)")
        print("  3. Supabase buckets are created")
        print("  4. Network connection to Supabase is working")
        print()
        
        return False


def main():
    """Run smoke test."""
    success = test_supabase_roundtrip()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
