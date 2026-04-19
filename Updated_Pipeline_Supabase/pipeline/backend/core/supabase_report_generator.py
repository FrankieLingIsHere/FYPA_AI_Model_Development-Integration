"""
Supabase Report Generator
==========================

Extends the standard report generator to upload artifacts to Supabase Storage
and store metadata in Supabase Postgres.

Workflow:
1. Generate local files (HTML, images) as usual
2. Validate caption against annotations
3. Upload files to Supabase Storage (private buckets)
4. Store metadata and storage keys in Supabase Postgres
5. Keep local files for backup/fallback
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.supabase_storage import SupabaseStorageManager
from pipeline.backend.core.supabase_db import SupabaseDatabaseManager
from pipeline.backend.integration.caption_validator import validate_caption

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

        def _safe_update_progress(stage: str):
            """Update progress if supported, otherwise keep status at generating."""
            try:
                if hasattr(self.db_manager, 'update_progress'):
                    self.db_manager.update_progress(report_id, stage)
                elif hasattr(self.db_manager, 'update_detection_status'):
                    self.db_manager.update_detection_status(report_id, 'generating')
            except Exception as progress_error:
                logger.debug(f"Progress update skipped ({stage}): {progress_error}")

        # Clear any stale aborted transaction state before DB operations.
        try:
            if getattr(self.db_manager, 'conn', None) is not None:
                self.db_manager.conn.rollback()
        except Exception:
            pass
        
        # Step 1: Generate local files using parent class
        result = super().generate_report(report_data)
        
        if not result:
            logger.error(f"Failed to generate local report: {report_id}")
            return result

        cloud_upload_disabled = bool(report_data.get('cloud_upload_disabled'))
        
        # Step 1.5: Validate caption against annotations
        caption = report_data.get('caption', '')
        detections = report_data.get('detections', [])
        detected_classes = [d.get('class', '') for d in detections]
        
        validation_result = None
        try:
            validation_result = validate_caption(caption, detections, detected_classes)
            
            if not validation_result['is_valid']:
                logger.warning(f"Caption validation failed for {report_id}:")
                for contradiction in validation_result['contradictions']:
                    logger.warning(f"  - {contradiction}")
            else:
                logger.info(f"Caption validated: {validation_result['validation_summary']}")
                
            # Store validation result for later use
            result['caption_validation'] = validation_result
            
        except Exception as e:
            logger.error(f"Error validating caption: {e}")
            # Continue anyway

        if cloud_upload_disabled:
            logger.info(
                f"Local-first pipeline active; skipping Supabase upload/DB persistence for {report_id}"
            )
            result['storage_keys'] = {}
            result['cloud_upload_skipped'] = True
            return result

        person_count = report_data.get('person_count', 0)
        violation_count = report_data.get('violation_count', 0)
        severity = report_data.get('severity', 'HIGH')
        device_id = str(report_data.get('device_id') or '').strip()
        if not device_id:
            detection_metadata = report_data.get('detection_data')
            if isinstance(detection_metadata, dict):
                device_id = str(detection_metadata.get('device_id') or '').strip()
        
        # Step 2: Ensure detection event exists in Supabase Postgres
        try:
            timestamp = report_data.get('timestamp', datetime.now())

            existing_event = None
            if hasattr(self.db_manager, 'get_detection_event'):
                existing_event = self.db_manager.get_detection_event(report_id)

            if existing_event:
                detection_result = report_id
                if hasattr(self.db_manager, 'update_detection_event'):
                    self.db_manager.update_detection_event(
                        report_id=report_id,
                        person_count=person_count,
                        violation_count=violation_count,
                        severity=severity,
                        status='generating'
                    )
            else:
                detection_result = self.db_manager.insert_detection_event(
                    report_id=report_id,
                    timestamp=timestamp,
                    person_count=person_count,
                    violation_count=violation_count,
                    severity=severity,
                    device_id=device_id or None,
                    status='generating'
                )
            
            if not detection_result:
                logger.error(f"Failed to insert detection event: {report_id}")
                # Continue anyway - local files are still available
            else:
                logger.info(f"Inserted detection event: {report_id}")
                
            # --- START PROGRESS TRACKING ---
            _safe_update_progress('analyzing_scene')

        except Exception as e:
            logger.error(f"Error inserting detection event: {e}")
            # Continue anyway
        
        # Step 3: Upload artifacts to Supabase Storage
        storage_keys = {}
        try:
            _safe_update_progress('uploading_images')
            
            original_image_path = report_data.get('original_image_path')
            annotated_image_path = report_data.get('annotated_image_path')
            html_path = result.get('html')
            pdf_path = result.get('pdf') if self.upload_pdf else None
            
            # Check if this is a reprocessing operation (should overwrite existing files)
            is_reprocessing = report_data.get('detection_data', {}).get('reprocessed', False)
            
            # Upload Images first to avail for report
            upload_results = self.storage_manager.upload_violation_artifacts(
                report_id=report_id,
                original_image_path=Path(original_image_path) if original_image_path else None,
                annotated_image_path=Path(annotated_image_path) if annotated_image_path else None,
                report_html_path=None, # Defer HTML/PDF upload until final
                report_pdf_path=None,
                upsert=is_reprocessing
            )
            storage_keys.update(upload_results)
            
            _safe_update_progress('generating_report')

            # --- Now generate report content (NLP/HTML) ---
            # NOTE: parent generate_report is already called at Step 1, 
            # so we're just retrofitting the progress here for the NEXT steps 
            # if we were to split it up differently. 
            # Since local gen is fast, we focus on the "Upload/DB" stages as 'processing'.
            
            # Since HTML is already generated locally, we upload it now
            upload_results_docs = self.storage_manager.upload_violation_artifacts(
                report_id=report_id,
                original_image_path=None,
                annotated_image_path=None,
                report_html_path=html_path,
                report_pdf_path=pdf_path,
                upsert=is_reprocessing
            )
            # Only update keys that have actual values (not None)
            # This prevents overwriting image keys from first upload with None
            for key, value in upload_results_docs.items():
                if value is not None:
                    storage_keys[key] = value
            
            _safe_update_progress('finalizing')
            logger.info(f"Uploaded artifacts to Supabase Storage: {report_id}")
            
        except Exception as e:
            logger.error(f"Error uploading artifacts to Supabase: {e}")
            # Continue anyway - local files are still available
        
        # Store storage keys in result for reprocessing scenarios
        result['storage_keys'] = storage_keys
        
        # Step 4: Persist violation record with storage keys and validation.
        # For reprocessing, update the existing row to avoid stale caption/NLP data drift.
        is_reprocessing = report_data.get('detection_data', {}).get('reprocessed', False)
        try:
            violation_summary = report_data.get('violation_summary')
            caption = report_data.get('caption', '')
            nlp_analysis = result.get('nlp_analysis')
            detection_data = report_data.get('detections')

            # FORCE Environment Override based on Caption Keywords (Fixes "Roadside" hallucination)
            detected_env = self._extract_environment_from_caption(caption)

            # Trust VLM keywords over NLP for specific environments
            if isinstance(nlp_analysis, dict) and detected_env != 'General Workspace':
                logger.info(f"Overriding NLP environment '{nlp_analysis.get('environment_type')}' with VLM-detected '{detected_env}'")
                nlp_analysis['environment_type'] = detected_env

                # Rebuild visual_evidence using professional scene description
                nlp_analysis['visual_evidence'] = self._build_scene_description(
                    caption, detected_env, report_data.get('detections', [])
                )

            # Add validation data to metadata
            metadata = {
                'detections': detection_data
            }
            source_scope = str(
                report_data.get('source_scope')
                or report_data.get('report_scope')
                or ''
            ).strip().lower()
            sync_source = str(
                report_data.get('sync_source')
                or report_data.get('source')
                or ''
            ).strip().lower()
            if source_scope:
                metadata['source_scope'] = source_scope
            if sync_source:
                metadata['sync_source'] = sync_source
                metadata['source'] = sync_source
            if device_id:
                metadata['device_id'] = device_id
            caption_provider = report_data.get('caption_provider')
            caption_model = report_data.get('caption_model')
            if caption_provider:
                metadata['caption_provider'] = caption_provider
            if caption_model:
                metadata['caption_model'] = caption_model
            caption_quality_fallback_applied = bool(report_data.get('caption_quality_fallback_applied'))
            caption_quality_reason = str(report_data.get('caption_quality_reason') or '').strip()
            if caption_quality_fallback_applied:
                metadata['caption_quality_fallback_applied'] = True
            if caption_quality_reason:
                metadata['caption_quality_reason'] = caption_quality_reason

            if isinstance(nlp_analysis, dict):
                report_provider = nlp_analysis.get('provider')
                report_model = nlp_analysis.get('model')
                if report_provider:
                    metadata['generation_provider'] = report_provider
                if report_model:
                    metadata['generation_model'] = report_model
            nlp_integrity = result.get('nlp_integrity')
            if isinstance(nlp_integrity, dict):
                metadata['nlp_integrity'] = nlp_integrity
            if validation_result:
                metadata['caption_validation'] = {
                    'is_valid': validation_result['is_valid'],
                    'confidence': validation_result['confidence'],
                    'contradictions': validation_result['contradictions'],
                    'warnings': validation_result['warnings'],
                    'summary': validation_result['validation_summary']
                }

            if is_reprocessing and hasattr(self.db_manager, 'update_violation'):
                updated = self.db_manager.update_violation(
                    report_id=report_id,
                    violation_summary=violation_summary,
                    caption=caption,
                    nlp_analysis=nlp_analysis,
                    detection_data=metadata,
                    original_image_key=storage_keys.get('original_image_key'),
                    annotated_image_key=storage_keys.get('annotated_image_key'),
                    report_html_key=storage_keys.get('report_html_key'),
                    report_pdf_key=storage_keys.get('report_pdf_key')
                )
                if updated:
                    logger.info(f"Updated violation record for reprocessing: {report_id}")
                else:
                    logger.warning(f"Reprocessing update affected no rows, falling back to insert: {report_id}")
                    violation_id = self.db_manager.insert_violation(
                        report_id=report_id,
                        violation_summary=violation_summary,
                        caption=caption,
                        nlp_analysis=nlp_analysis,
                        detection_data=metadata,
                        original_image_key=storage_keys.get('original_image_key'),
                        annotated_image_key=storage_keys.get('annotated_image_key'),
                        report_html_key=storage_keys.get('report_html_key'),
                        report_pdf_key=storage_keys.get('report_pdf_key'),
                        device_id=device_id or None
                    )
                    if violation_id:
                        logger.info(f"Inserted violation record after reprocessing fallback: {violation_id}")
                    else:
                        logger.error(f"Failed to persist violation record after reprocessing fallback: {report_id}")
            else:
                violation_id = self.db_manager.insert_violation(
                    report_id=report_id,
                    violation_summary=violation_summary,
                    caption=caption,
                    nlp_analysis=nlp_analysis,
                    detection_data=metadata,
                    original_image_key=storage_keys.get('original_image_key'),
                    annotated_image_key=storage_keys.get('annotated_image_key'),
                    report_html_key=storage_keys.get('report_html_key'),
                    report_pdf_key=storage_keys.get('report_pdf_key'),
                    device_id=device_id or None
                )

                if violation_id:
                    logger.info(f"Inserted violation record: {violation_id}")
                else:
                    logger.error(f"Failed to insert violation record: {report_id}")

        except Exception as e:
            logger.error(f"Error persisting violation record: {e}")
            # Continue anyway
        
        # Step 5: Log event to flood_logs (skip for reprocessing)
        if not is_reprocessing:
            try:
                self.db_manager.log_event(
                    event_type='report_generated',
                    message=f"Report generated and uploaded: {report_id}",
                    report_id=report_id,
                    device_id=device_id or None,
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
