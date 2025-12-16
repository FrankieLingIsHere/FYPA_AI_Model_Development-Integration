"""
Supabase Report Generator
==========================

Extends the standard report generator to upload artifacts to Supabase Storage
and store metadata in Supabase Postgres.

Workflow:
1. Generate local files (HTML, images) as usual
2. Upload files to Supabase Storage (private buckets)
3. Store metadata and storage keys in Supabase Postgres
4. Keep local files for backup/fallback
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.supabase_storage import SupabaseStorageManager
from pipeline.backend.core.supabase_db import SupabaseDatabaseManager

logger = logging.getLogger(__name__)


class SupabaseReportGenerator(ReportGenerator):
    """
    Report generator with Supabase cloud backend integration.
    
    Extends the standard ReportGenerator to:
    - Upload generated artifacts to Supabase Storage
    - Store metadata in Supabase Postgres
    - Generate signed URLs for secure access
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        storage_manager: SupabaseStorageManager,
        db_manager: SupabaseDatabaseManager
    ):
        """
        Initialize Supabase Report Generator.
        
        Args:
            config: Configuration dictionary
            storage_manager: Supabase Storage Manager instance
            db_manager: Supabase Database Manager instance
        """
        super().__init__(config)
        
        self.storage_manager = storage_manager
        self.db_manager = db_manager
        self.upload_pdf = config.get('SUPABASE_CONFIG', {}).get('upload_pdf', False)
        
        logger.info("Supabase Report Generator initialized")
        logger.info(f"PDF upload: {'enabled' if self.upload_pdf else 'disabled'}")
    
    def generate_report(self, report_data: Dict[str, Any]) -> Dict[str, Optional[Path]]:
        """
        Generate complete violation report and upload to Supabase.
        
        Workflow:
        1. Generate local files using parent class
        2. Insert detection event in Supabase Postgres
        3. Upload artifacts to Supabase Storage
        4. Insert violation record with storage keys
        5. Log event to flood_logs
        
        Args:
            report_data: Dictionary containing:
                - report_id: Unique identifier
                - timestamp: Datetime of violation
                - caption: Image caption from LLaVA
                - detections: List of YOLO detections
                - violation_summary: Summary of violations
                - person_count: Number of people detected
                - violation_count: Number of violations
                - severity: Violation severity
                - original_image_path: Path to original image
                - annotated_image_path: Path to annotated image
        
        Returns:
            Dictionary with paths and storage keys:
                - html: Path to local HTML report
                - pdf: Path to local PDF report (if enabled)
                - nlp_analysis: NLP analysis data
                - storage_keys: Dict of Supabase storage keys
        """
        report_id = report_data.get('report_id')
        logger.info(f"Generating Supabase-backed report: {report_id}")
        
        # Step 1: Generate local files using parent class
        result = super().generate_report(report_data)
        
        if not result:
            logger.error(f"Failed to generate local report: {report_id}")
            return result
        
        # Step 2: Insert detection event in Supabase Postgres
        try:
            timestamp = report_data.get('timestamp', datetime.now())
            person_count = report_data.get('person_count', 0)
            violation_count = report_data.get('violation_count', 0)
            severity = report_data.get('severity', 'HIGH')
            
            detection_result = self.db_manager.insert_detection_event(
                report_id=report_id,
                timestamp=timestamp,
                person_count=person_count,
                violation_count=violation_count,
                severity=severity
            )
            
            if not detection_result:
                logger.error(f"Failed to insert detection event: {report_id}")
                # Continue anyway - local files are still available
            else:
                logger.info(f"Inserted detection event: {report_id}")
                
        except Exception as e:
            logger.error(f"Error inserting detection event: {e}")
            # Continue anyway
        
        # Step 3: Upload artifacts to Supabase Storage
        storage_keys = {}
        try:
            original_image_path = report_data.get('original_image_path')
            annotated_image_path = report_data.get('annotated_image_path')
            html_path = result.get('html')
            pdf_path = result.get('pdf') if self.upload_pdf else None
            
            upload_results = self.storage_manager.upload_violation_artifacts(
                report_id=report_id,
                original_image_path=Path(original_image_path) if original_image_path else None,
                annotated_image_path=Path(annotated_image_path) if annotated_image_path else None,
                report_html_path=html_path,
                report_pdf_path=pdf_path
            )
            
            storage_keys = upload_results
            logger.info(f"Uploaded artifacts to Supabase Storage: {report_id}")
            
        except Exception as e:
            logger.error(f"Error uploading artifacts to Supabase: {e}")
            # Continue anyway - local files are still available
        
        # Step 4: Insert violation record with storage keys
        try:
            violation_summary = report_data.get('violation_summary')
            caption = report_data.get('caption')
            nlp_analysis = result.get('nlp_analysis')
            detection_data = report_data.get('detections')
            
            violation_id = self.db_manager.insert_violation(
                report_id=report_id,
                violation_summary=violation_summary,
                caption=caption,
                nlp_analysis=nlp_analysis,
                detection_data={'detections': detection_data} if detection_data else None,
                original_image_key=storage_keys.get('original_image_key'),
                annotated_image_key=storage_keys.get('annotated_image_key'),
                report_html_key=storage_keys.get('report_html_key'),
                report_pdf_key=storage_keys.get('report_pdf_key')
            )
            
            if violation_id:
                logger.info(f"Inserted violation record: {violation_id}")
            else:
                logger.error(f"Failed to insert violation record: {report_id}")
                
        except Exception as e:
            logger.error(f"Error inserting violation record: {e}")
            # Continue anyway
        
        # Step 5: Log event to flood_logs
        try:
            self.db_manager.log_event(
                event_type='report_generated',
                message=f"Report generated and uploaded: {report_id}",
                report_id=report_id,
                metadata={
                    'person_count': person_count,
                    'violation_count': violation_count,
                    'severity': severity,
                    'storage_keys': storage_keys
                }
            )
        except Exception as e:
            logger.error(f"Error logging event: {e}")
            # Continue anyway
        
        # Add storage keys to result
        result['storage_keys'] = storage_keys
        
        logger.info(f"[OK] Supabase-backed report completed: {report_id}")
        return result


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_supabase_report_generator(config: Dict[str, Any]) -> SupabaseReportGenerator:
    """
    Create SupabaseReportGenerator with all dependencies.
    
    Args:
        config: Configuration dictionary including SUPABASE_CONFIG
    
    Returns:
        SupabaseReportGenerator instance
    """
    from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    
    storage_manager = create_storage_manager_from_env()
    db_manager = create_db_manager_from_env()
    
    return SupabaseReportGenerator(
        config=config,
        storage_manager=storage_manager,
        db_manager=db_manager
    )


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    from dotenv import load_dotenv
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load environment variables
    load_dotenv()
    
    print("=" * 70)
    print("SUPABASE REPORT GENERATOR TEST")
    print("=" * 70)
    
    # Add parent to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))
    
    from pipeline.config import (
        OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, 
        VIOLATIONS_DIR, REPORTS_DIR, SUPABASE_CONFIG
    )
    
    try:
        # Create config
        config = {
            'OLLAMA_CONFIG': OLLAMA_CONFIG,
            'RAG_CONFIG': RAG_CONFIG,
            'REPORT_CONFIG': REPORT_CONFIG,
            'BRAND_COLORS': BRAND_COLORS,
            'REPORTS_DIR': REPORTS_DIR,
            'VIOLATIONS_DIR': VIOLATIONS_DIR,
            'SUPABASE_CONFIG': SUPABASE_CONFIG
        }
        
        # Create generator
        generator = create_supabase_report_generator(config)
        
        print(f"\n[OK] Supabase Report Generator initialized")
        print(f"Storage manager: {generator.storage_manager.__class__.__name__}")
        print(f"DB manager: {generator.db_manager.__class__.__name__}")
        print(f"PDF upload: {generator.upload_pdf}")
        
        print("\n[OK] All tests passed!")
        
    except Exception as e:
        print(f"\n[X] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("=" * 70)
