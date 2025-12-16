"""
Example Usage - Supabase Report Generator
==========================================

Demonstrates how to use the Supabase-backed report generator
to create and upload violation reports.

This is a simplified example showing the key integration points.
"""

import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_generate_report():
    """
    Example: Generate a violation report and upload to Supabase.
    
    This shows the minimal code needed to:
    1. Create report data from detections
    2. Generate local files
    3. Upload to Supabase Storage
    4. Store metadata in Supabase Postgres
    """
    
    # Import configuration
    from pipeline.config import (
        OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, 
        BRAND_COLORS, VIOLATIONS_DIR, REPORTS_DIR,
        SUPABASE_CONFIG
    )
    
    # Import Supabase report generator
    from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
    
    logger.info("=" * 70)
    logger.info("EXAMPLE: Generating Supabase-Backed Report")
    logger.info("=" * 70)
    
    # Step 1: Create configuration
    config = {
        'OLLAMA_CONFIG': OLLAMA_CONFIG,
        'RAG_CONFIG': RAG_CONFIG,
        'REPORT_CONFIG': REPORT_CONFIG,
        'BRAND_COLORS': BRAND_COLORS,
        'REPORTS_DIR': REPORTS_DIR,
        'VIOLATIONS_DIR': VIOLATIONS_DIR,
        'SUPABASE_CONFIG': SUPABASE_CONFIG
    }
    
    # Step 2: Initialize generator
    logger.info("\nInitializing Supabase report generator...")
    generator = create_supabase_report_generator(config)
    logger.info("✓ Generator initialized")
    
    # Step 3: Prepare report data
    # This would normally come from your YOLO detection pipeline
    report_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    report_data = {
        'report_id': report_id,
        'timestamp': datetime.now(),
        'caption': 'Worker in construction site without required safety equipment. Worker wearing dark blue shirt, no hardhat, no safety vest visible.',
        'detections': [
            {
                'class_name': 'Person',
                'confidence': 0.95,
                'bbox': [100, 100, 300, 400]
            },
            {
                'class_name': 'NO-Hardhat',
                'confidence': 0.87,
                'bbox': [120, 110, 180, 160]
            },
            {
                'class_name': 'NO-Safety Vest',
                'confidence': 0.82,
                'bbox': [110, 180, 290, 380]
            }
        ],
        'violation_summary': 'Missing hardhat and safety vest',
        'person_count': 1,
        'violation_count': 2,
        'severity': 'HIGH',
        
        # NOTE: In real usage, these would be paths to actual captured images
        # For this example, you would need to provide real image paths
        'original_image_path': 'path/to/original/image.jpg',  # Replace with actual path
        'annotated_image_path': 'path/to/annotated/image.jpg'  # Replace with actual path
    }
    
    logger.info(f"\nReport ID: {report_id}")
    logger.info(f"Violations: {report_data['violation_count']}")
    logger.info(f"Severity: {report_data['severity']}")
    
    # Step 4: Generate report (uploads to Supabase automatically)
    logger.info("\nGenerating report and uploading to Supabase...")
    logger.info("This will:")
    logger.info("  1. Generate local HTML report")
    logger.info("  2. Insert detection event in Postgres")
    logger.info("  3. Upload images to Supabase Storage")
    logger.info("  4. Upload HTML report to Supabase Storage")
    logger.info("  5. Insert violation record with storage keys")
    logger.info("  6. Log event to flood_logs")
    
    try:
        result = generator.generate_report(report_data)
        
        if result:
            logger.info("\n✓ Report generated successfully!")
            logger.info(f"  Local HTML: {result.get('html')}")
            
            storage_keys = result.get('storage_keys', {})
            if storage_keys:
                logger.info("\n  Uploaded to Supabase:")
                for key, value in storage_keys.items():
                    if value:
                        logger.info(f"    - {key}: {value}")
            
            logger.info(f"\nView report at: http://localhost:5001/report/{report_id}")
        else:
            logger.error("\n✗ Report generation failed")
            
    except Exception as e:
        logger.error(f"\n✗ Error generating report: {e}")
        import traceback
        traceback.print_exc()
    
    logger.info("\n" + "=" * 70)


def example_query_reports():
    """
    Example: Query reports from Supabase database.
    
    Shows how to retrieve and display violation data.
    """
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    
    logger.info("=" * 70)
    logger.info("EXAMPLE: Querying Reports from Supabase")
    logger.info("=" * 70)
    
    # Initialize database manager
    db = create_db_manager_from_env()
    
    # Get recent violations
    logger.info("\nFetching recent violations...")
    violations = db.get_recent_violations(limit=5)
    
    logger.info(f"Found {len(violations)} recent violations:\n")
    
    for i, v in enumerate(violations, 1):
        logger.info(f"{i}. Report: {v['report_id']}")
        logger.info(f"   Time: {v.get('timestamp')}")
        logger.info(f"   People: {v.get('person_count')}")
        logger.info(f"   Violations: {v.get('violation_count')}")
        logger.info(f"   Severity: {v.get('severity')}")
        logger.info(f"   Summary: {v.get('violation_summary', 'N/A')[:60]}...")
        logger.info("")
    
    db.close()
    logger.info("=" * 70)


def example_generate_signed_urls():
    """
    Example: Generate signed URLs for accessing private storage.
    
    Shows how to create temporary secure URLs for images and reports.
    """
    from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    
    logger.info("=" * 70)
    logger.info("EXAMPLE: Generating Signed URLs")
    logger.info("=" * 70)
    
    # Initialize managers
    storage = create_storage_manager_from_env()
    db = create_db_manager_from_env()
    
    # Get a recent violation
    violations = db.get_recent_violations(limit=1)
    
    if not violations:
        logger.info("\nNo violations found in database")
        return
    
    violation = violations[0]
    report_id = violation['report_id']
    
    logger.info(f"\nGenerating signed URLs for report: {report_id}")
    
    # Generate signed URLs
    original_url = storage.get_signed_url(violation.get('original_image_key'))
    annotated_url = storage.get_signed_url(violation.get('annotated_image_key'))
    report_url = storage.get_signed_url(violation.get('report_html_key'))
    
    logger.info(f"\nSigned URLs (valid for {storage.signed_url_ttl} seconds):")
    logger.info(f"\n  Original image:")
    logger.info(f"    {original_url[:80]}..." if original_url else "    Not available")
    logger.info(f"\n  Annotated image:")
    logger.info(f"    {annotated_url[:80]}..." if annotated_url else "    Not available")
    logger.info(f"\n  HTML report:")
    logger.info(f"    {report_url[:80]}..." if report_url else "    Not available")
    
    db.close()
    logger.info("\n" + "=" * 70)


def main():
    """Run all examples."""
    print("\n")
    print("=" * 70)
    print("SUPABASE INTEGRATION EXAMPLES")
    print("=" * 70)
    print("\nThese examples demonstrate how to use the Supabase-backed")
    print("report generator in your own code.")
    print("\nNOTE: example_generate_report() requires actual image files.")
    print("      Update the image paths in the code before running.")
    print("\n" + "=" * 70)
    
    # Example 1: Query existing reports
    try:
        example_query_reports()
    except Exception as e:
        logger.error(f"Query example failed: {e}")
    
    # Example 2: Generate signed URLs
    try:
        example_generate_signed_urls()
    except Exception as e:
        logger.error(f"Signed URLs example failed: {e}")
    
    # Example 3: Generate new report (commented out by default)
    # Uncomment and provide real image paths to test
    # try:
    #     example_generate_report()
    # except Exception as e:
    #     logger.error(f"Generate report example failed: {e}")
    
    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()
