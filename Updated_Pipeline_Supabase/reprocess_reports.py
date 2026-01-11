"""
Reprocess All Reports with Latest Pipeline
===========================================

This utility reprocesses all existing violation reports with the latest
pipeline configuration, including:
- Updated confidence thresholds
- New head-region validation
- Improved scene classification
- Enhanced caption generation

Usage:
    python reprocess_reports.py [--all | --since DATE | --report-id ID]
    
Examples:
    python reprocess_reports.py --all                    # Reprocess all reports
    python reprocess_reports.py --since 2026-01-01       # Reprocess since date
    python reprocess_reports.py --report-id 20251223_172006  # Single report
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime
import sys
import time
import os

# Load environment variables BEFORE importing any project modules
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Verify required environment variables
required_env_vars = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_DB_URL']
missing_vars = [var for var in required_env_vars if not os.getenv(var)]

if missing_vars:
    logger.error("=" * 70)
    logger.error("MISSING ENVIRONMENT VARIABLES")
    logger.error("=" * 70)
    logger.error(f"The following environment variables are required but not set:")
    for var in missing_vars:
        logger.error(f"  - {var}")
    logger.error("")
    logger.error("Please ensure your .env file contains all required variables:")
    logger.error("  SUPABASE_URL=your_supabase_project_url")
    logger.error("  SUPABASE_SERVICE_ROLE_KEY=your_service_role_key")
    logger.error("  SUPABASE_DB_URL=postgresql://user:pass@host:port/database")
    logger.error("=" * 70)
    sys.exit(1)

# Import project modules
try:
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
    from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    from caption_image import caption_image_llava, validate_work_environment
    from infer_image import predict_image
    from pipeline.config import VIOLATION_RULES
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}")
    logger.error("Make sure you're running from the Updated_Pipeline_Supabase directory")
    sys.exit(1)

# Initialize managers
db_manager = None
storage_manager = None
report_generator = None
caption_generator = None

def initialize_managers():
    """Initialize all required managers."""
    global db_manager, storage_manager, report_generator, caption_generator
    
    try:
        # Import configuration
        from pipeline.config import (
            OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, 
            REPORTS_DIR, VIOLATIONS_DIR, SUPABASE_CONFIG, LLAVA_CONFIG
        )
        
        db_manager = create_db_manager_from_env()
        storage_manager = create_storage_manager_from_env()
        
        # Create report config dictionary (same as luna_app.py)
        report_config = {
            'OLLAMA_CONFIG': OLLAMA_CONFIG,
            'RAG_CONFIG': RAG_CONFIG,
            'REPORT_CONFIG': REPORT_CONFIG,
            'BRAND_COLORS': BRAND_COLORS,
            'REPORTS_DIR': REPORTS_DIR,
            'VIOLATIONS_DIR': VIOLATIONS_DIR,
            'SUPABASE_CONFIG': SUPABASE_CONFIG
        }
        
        report_generator = create_supabase_report_generator(report_config)
        
        # Initialize caption generator with LLAVA config
        caption_config = {'LLAVA_CONFIG': LLAVA_CONFIG}
        caption_generator = CaptionGenerator(caption_config)
        
        logger.info("✓ All managers initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize managers: {e}")
        import traceback
        traceback.print_exc()
        return False


def reprocess_single_report(report_id: str, temp_dir: Path) -> bool:
    """
    Reprocess a single violation report.
    
    Args:
        report_id: Report ID to reprocess
        temp_dir: Temporary directory for processing
    
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"=" * 70)
    logger.info(f"Reprocessing report: {report_id}")
    logger.info(f"=" * 70)
    
    # Initialize paths before try block to avoid UnboundLocalError in finally
    temp_image = temp_dir / f"{report_id}_original.jpg"
    annotated_path = temp_dir / f"{report_id}_annotated.jpg"
    
    try:
        # 1. Get violation data from database
        violation = db_manager.get_violation(report_id)
        if not violation:
            logger.error(f"Report {report_id} not found in database")
            return False
        
        # 2. Download original image from storage
        original_image_key = violation.get('original_image_key')
        if not original_image_key:
            logger.error(f"No original image found for report {report_id}")
            return False
        
        logger.info("📥 Downloading original image...")
        image_bytes = storage_manager.download_file_content(original_image_key)
        
        if not image_bytes:
            logger.error("Failed to download original image")
            return False
        
        # Save bytes to file
        temp_image.write_bytes(image_bytes)
        
        # 3. Re-run YOLO detection with NEW pipeline settings
        logger.info("🔍 Re-running YOLO detection with updated pipeline...")
        detections, annotated = predict_image(str(temp_image), conf=0.25)  # New threshold
        logger.info(f"   Detected {len(detections)} objects")
        
        # Save new annotated image
        import cv2
        cv2.imwrite(str(annotated_path), annotated)
        
        # 4. Re-validate environment
        logger.info("🌍 Re-validating work environment...")
        env_result = validate_work_environment(str(temp_image))
        logger.info(f"   Environment: {env_result['environment_type']} (valid: {env_result['is_valid']})")
        
        if not env_result['is_valid']:
            logger.warning(f"⚠️ Report {report_id} is not a valid work environment - skipping")
            # Update status to skipped
            db_manager.update_detection_status(
                report_id,
                'skipped',
                f"Not a work environment: {env_result['environment_type']}"
            )
            return True  # Not an error, just skipped
        
        # 5. Re-generate caption with NEW prompts
        logger.info("🎨 Re-generating caption with updated prompts...")
        caption = caption_image_llava(str(temp_image))
        logger.info(f"   Caption length: {len(caption) if caption else 0} chars")
        
        # 6. Extract violation types
        violation_detections = [d for d in detections if 'no-' in d['class_name'].lower()]
        violation_types = [d['class_name'] for d in violation_detections]
        
        logger.info(f"🚨 Violations detected: {violation_types}")
        
        # If no violations detected, remove this report
        if not violation_types:
            logger.warning(f"⚠️ No violations found in report {report_id} - removing invalid report")
            # Delete from storage
            storage_manager.delete_violation_artifacts(report_id)
            # Delete from database
            db_manager.delete_violation(report_id)
            logger.info(f"🗑️ Report {report_id} deleted (no longer valid)")
            return True  # Successfully processed (deleted)
        
        # 7. Generate new report with updated data
        logger.info("📄 Generating new report...")
        report_data = {
            'report_id': report_id,
            'timestamp': violation.get('timestamp') or datetime.now(),
            'detections': detections,
            'violation_summary': f"PPE Violation Detected: {', '.join(violation_types)}" if violation_types else "No violations detected",
            'violation_count': len(violation_types),
            'caption': caption,
            'image_caption': caption,
            'original_image_path': str(temp_image),
            'annotated_image_path': str(annotated_path),
            'location': violation.get('device_id', 'Reprocessed'),
            'severity': 'HIGH' if len(violation_types) >= 2 else 'MEDIUM' if violation_types else 'LOW',
            'person_count': len([d for d in detections if 'person' in d['class_name'].lower()]),
            'detection_data': {'reprocessed': True, 'reprocess_date': datetime.now().isoformat()}
        }
        
        result = report_generator.generate_report(report_data)
        
        if result and result.get('html'):
            logger.info("✓ Report generated successfully")
            
            # 9. Update database with new data (skip report_generator's insert since record exists)
            logger.info("💾 Updating database...")
            
            # Build metadata
            metadata = {
                'detections': detections,
                'reprocessed': True,
                'reprocess_date': datetime.now().isoformat()
            }
            
            # Update violation record
            success = db_manager.update_violation(
                report_id=report_id,
                violation_summary=report_data['violation_summary'],
                caption=caption,
                nlp_analysis=result.get('nlp_analysis', {}),
                detection_data=metadata,
                original_image_key=result.get('storage_keys', {}).get('original_image_key'),
                annotated_image_key=result.get('storage_keys', {}).get('annotated_image_key'),
                report_html_key=result.get('storage_keys', {}).get('report_html_key'),
                report_pdf_key=result.get('storage_keys', {}).get('report_pdf_key')
            )
            
            # Update detection_events with new counts
            db_manager.update_detection_event(
                report_id=report_id,
                person_count=report_data['person_count'],
                violation_count=report_data['violation_count'],
                severity=report_data['severity'],
                status='completed'
            )
            
            logger.info(f"✅ Report {report_id} reprocessed successfully")
            return True
        else:
            logger.error("Failed to generate report")
            return False
            
    except Exception as e:
        logger.error(f"Error reprocessing report {report_id}: {e}", exc_info=True)
        try:
            db_manager.update_detection_status(report_id, 'failed', f"Reprocessing error: {str(e)}")
        except:
            pass
        return False
    finally:
        # Cleanup temp files
        if temp_image.exists():
            temp_image.unlink()
        if annotated_path.exists():
            annotated_path.unlink()


def reprocess_all_reports(since_date=None):
    """
    Reprocess all violation reports.
    
    Args:
        since_date: Optional datetime to filter reports (only reprocess reports after this date)
    """
    logger.info("🔄 Starting bulk report reprocessing...")
    
    # Create temp directory
    temp_dir = Path('temp_reprocess')
    temp_dir.mkdir(exist_ok=True)
    
    try:
        # Get all violations from database
        violations = db_manager.get_recent_violations(limit=10000)
        
        if since_date:
            violations = [v for v in violations if v.get('timestamp') and v['timestamp'] >= since_date]
        
        total = len(violations)
        logger.info(f"📊 Found {total} reports to reprocess")
        
        if total == 0:
            logger.info("No reports to reprocess")
            return
        
        # Process each report
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for idx, violation in enumerate(violations, 1):
            report_id = violation['report_id']
            logger.info(f"\n[{idx}/{total}] Processing {report_id}...")
            
            result = reprocess_single_report(report_id, temp_dir)
            
            if result:
                success_count += 1
            else:
                failed_count += 1
            
            # Small delay to avoid overwhelming the system
            time.sleep(1)
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("REPROCESSING SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total reports:    {total}")
        logger.info(f"✓ Successful:     {success_count}")
        logger.info(f"✗ Failed:         {failed_count}")
        logger.info(f"⊘ Skipped:        {skipped_count}")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"Error during bulk reprocessing: {e}", exc_info=True)
    finally:
        # Cleanup temp directory
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Reprocess violation reports with latest pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='Reprocess all reports')
    group.add_argument('--since', type=str, help='Reprocess reports since date (YYYY-MM-DD)')
    group.add_argument('--report-id', type=str, help='Reprocess single report by ID')
    
    args = parser.parse_args()
    
    # Initialize managers
    if not initialize_managers():
        logger.error("Failed to initialize managers. Exiting.")
        sys.exit(1)
    
    # Parse date if provided
    since_date = None
    if args.since:
        try:
            since_date = datetime.strptime(args.since, '%Y-%m-%d')
            logger.info(f"Filtering reports since: {since_date}")
        except ValueError:
            logger.error(f"Invalid date format: {args.since}. Use YYYY-MM-DD")
            sys.exit(1)
    
    # Execute based on arguments
    if args.report_id:
        # Single report
        temp_dir = Path('temp_reprocess')
        temp_dir.mkdir(exist_ok=True)
        try:
            success = reprocess_single_report(args.report_id, temp_dir)
            sys.exit(0 if success else 1)
        finally:
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        # All reports or filtered by date
        reprocess_all_reports(since_date=since_date)


if __name__ == '__main__':
    main()
