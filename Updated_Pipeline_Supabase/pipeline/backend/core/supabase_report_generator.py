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
# Readability: Backend core: coordinate detection, persistence, and report workflow concerns.

import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import time

from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.supabase_storage import SupabaseStorageManager
from pipeline.backend.core.supabase_db import SupabaseDatabaseManager
from pipeline.backend.integration.caption_validator import validate_caption

# Prepare logger for the next step.
logger = logging.getLogger(__name__)


# Section: group supabase report generator state and behaviour in one readable unit.
class SupabaseReportGenerator(ReportGenerator):
    """
    Report generator with Supabase cloud backend integration.
    
    Extends the standard ReportGenerator to:
    - Upload generated artifacts to Supabase Storage
    - Store metadata in Supabase Postgres
    - Generate signed URLs for secure access
    """
    
    # Section: run the init workflow with clear inputs and outputs.
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
        # Trigger the side effect required for this stage.
        super().__init__(config)
        
        self.storage_manager = storage_manager
        self.db_manager = db_manager
        self.upload_pdf = config.get('SUPABASE_CONFIG', {}).get('upload_pdf', False)
        
        logger.info("Supabase Report Generator initialized")
        logger.info(f"PDF upload: {'enabled' if self.upload_pdf else 'disabled'}")
    
    # Section: run the generate report workflow with clear inputs and outputs.
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
        # Prepare report id for the next step.
        report_id = report_data.get('report_id')
        generation_started = time.perf_counter()
        generation_timings: Dict[str, float] = {}

        # Section: run the record timing workflow with clear inputs and outputs.
        def _record_timing(stage: str, started_at: float) -> None:
            # Prepare values needed by the next step.
            generation_timings[stage] = round(time.perf_counter() - started_at, 3)

        logger.info(f"Generating Supabase-backed report: {report_id}")

        progress_status_marked = False
        early_ready_signaled = False

        # Section: run the safe update progress workflow with clear inputs and outputs.
        def _safe_update_progress(stage: str):
            """Update progress if supported, otherwise keep status at generating."""
            nonlocal progress_status_marked, early_ready_signaled
            # Choose the correct branch before the workflow continues.
            if early_ready_signaled:
                # Return the prepared result to the caller.
                return
            try:
                if hasattr(self.db_manager, 'update_progress'):
                    # Trigger the side effect required for this stage.
                    self.db_manager.update_progress(report_id, stage)
                elif hasattr(self.db_manager, 'update_detection_status'):
                    if not progress_status_marked:
                        # Trigger the side effect required for this stage.
                        self.db_manager.update_detection_status(report_id, 'generating')
                        progress_status_marked = True
            except Exception as progress_error:
                # Trigger the side effect required for this stage.
                logger.debug(f"Progress update skipped ({stage}): {progress_error}")

        # Clear any stale aborted transaction state before DB operations.
        # Protect this step so expected failures can fall back cleanly.
        try:
            safe_rollback = getattr(self.db_manager, '_safe_rollback', None)
            if callable(safe_rollback):
                safe_rollback()
            elif getattr(self.db_manager, 'conn', None) is not None:
                self.db_manager.conn.rollback()
        except Exception:
            pass

        # Prepare cloud upload disabled for the next step.
        cloud_upload_disabled = bool(report_data.get('cloud_upload_disabled'))
        person_count = report_data.get('person_count', 0)
        violation_count = report_data.get('violation_count', 0)
        severity = report_data.get('severity', 'HIGH')
        device_id = str(report_data.get('device_id') or '').strip()
        if not device_id:
            # Prepare detection metadata for the next step.
            detection_metadata = report_data.get('detection_data')
            if isinstance(detection_metadata, dict):
                # Prepare device id for the next step.
                device_id = str(detection_metadata.get('device_id') or '').strip()

        # Section: run the ensure detection event started workflow with clear inputs and outputs.
        def _ensure_detection_event_started() -> bool:
            """Persist the cloud row before slow NLP/storage work begins."""
            nonlocal progress_status_marked
            if cloud_upload_disabled:
                return False
            # Choose the correct branch before the workflow continues.
            if not report_id or self.db_manager is None:
                return False

            try:
                # Prepare timestamp for the next step.
                timestamp = report_data.get('timestamp', datetime.now())
                persisted = False

                existing_event = None
                if hasattr(self.db_manager, 'get_detection_event'):
                    # Prepare existing event for the next step.
                    existing_event = self.db_manager.get_detection_event(report_id)

                if existing_event and hasattr(self.db_manager, 'update_detection_event'):
                    self.db_manager.update_detection_event(
                        report_id=report_id,
                        person_count=person_count,
                        violation_count=violation_count,
                        severity=severity,
                        status='generating'
                    )
                    # Trigger the side effect required for this stage.
                    logger.info(f"Marked detection event generating before report work: {report_id}")
                    persisted = True
                    progress_status_marked = True
                # Choose the correct branch before the workflow continues.
                elif not existing_event and hasattr(self.db_manager, 'insert_detection_event'):
                    detection_result = self.db_manager.insert_detection_event(
                        report_id=report_id,
                        timestamp=timestamp,
                        person_count=person_count,
                        violation_count=violation_count,
                        severity=severity,
                        device_id=device_id or None,
                        status='generating'
                    )
                    # Choose the correct branch before the workflow continues.
                    if detection_result:
                        # Trigger the side effect required for this stage.
                        logger.info(f"Inserted detection event before report work: {report_id}")
                        persisted = True
                        progress_status_marked = True
                    else:
                        logger.warning(f"Initial detection event insert returned empty: {report_id}")

                # Trigger the side effect required for this stage.
                _safe_update_progress('generating_report')
                return persisted
            except Exception as e:
                logger.error(f"Error ensuring initial detection event for {report_id}: {e}")
                return False

        # Prepare timing started for the next step.
        timing_started = time.perf_counter()
        initial_event_ready = _ensure_detection_event_started()
        _record_timing('supabase_initial_event_seconds', timing_started)
        
        # Step 1: Generate local files using parent class
        timing_started = time.perf_counter()
        result = super().generate_report(report_data)
        _record_timing('local_report_generate_seconds', timing_started)
        
        # Choose the correct branch before the workflow continues.
        if not result:
            # Trigger the side effect required for this stage.
            logger.error(f"Failed to generate local report: {report_id}")
            return result
        parent_timings = result.get('generation_timings') if isinstance(result, dict) else None
        if isinstance(parent_timings, dict):
            for key, value in parent_timings.items():
                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Prepare values needed by the next step.
                    generation_timings[f"local_{key}"] = round(float(value), 3)
                except Exception:
                    pass

        # The local HTML is openable at this point. Notify the queue/UI before
        # slower storage upload, violation persistence, and flood-log work.
        ready_callback = report_data.get('report_ready_callback')
        if callable(ready_callback):
            try:
                # Prepare html path for the next step.
                html_path = result.get('html') if isinstance(result, dict) else None
                if html_path and Path(html_path).exists():
                    # Prepare callback started for the next step.
                    callback_started = time.perf_counter()
                    early_ready_signaled = bool(ready_callback('supabase_local_report_html_written'))
                    if early_ready_signaled:
                        # Prepare progress status marked for the next step.
                        progress_status_marked = True
                    _record_timing('early_ready_callback_seconds', callback_started)
            except Exception as callback_err:
                logger.debug(f"Early report-ready callback skipped for {report_id}: {callback_err}")

        # Step 1.5: Validate caption against annotations
        # Prepare caption for the next step.
        caption = report_data.get('caption', '')
        detections = report_data.get('detections', [])
        detected_classes = [d.get('class', '') for d in detections]
        
        validation_result = None
        try:
            # Prepare timing started for the next step.
            timing_started = time.perf_counter()
            validation_result = validate_caption(caption, detections, detected_classes)
            _record_timing('caption_validation_seconds', timing_started)
            
            if not validation_result['is_valid']:
                # Trigger the side effect required for this stage.
                logger.warning(f"Caption validation failed for {report_id}:")
                for contradiction in validation_result['contradictions']:
                    # Trigger the side effect required for this stage.
                    logger.warning(f"  - {contradiction}")
            else:
                logger.info(f"Caption validated: {validation_result['validation_summary']}")
                
            # Store validation result for later use
            # Prepare values needed by the next step.
            result['caption_validation'] = validation_result
            
        except Exception as e:
            logger.error(f"Error validating caption: {e}")
            # Continue anyway

        # Choose the correct branch before the workflow continues.
        if cloud_upload_disabled:
            logger.info(
                f"Local-first pipeline active; skipping Supabase upload/DB persistence for {report_id}"
            )
            # Prepare values needed by the next step.
            result['storage_keys'] = {}
            result['cloud_upload_skipped'] = True
            return result

        # Step 2: Ensure detection event exists in Supabase Postgres
        # Protect this step so expected failures can fall back cleanly.
        try:
            timing_started = time.perf_counter()
            timestamp = report_data.get('timestamp', datetime.now())

            # Prepare existing event for the next step.
            existing_event = {'report_id': report_id} if initial_event_ready else None
            if not existing_event and hasattr(self.db_manager, 'get_detection_event'):
                # Prepare existing event for the next step.
                existing_event = self.db_manager.get_detection_event(report_id)

            if existing_event:
                detection_result = report_id
                if not initial_event_ready and hasattr(self.db_manager, 'update_detection_event'):
                    # Trigger the side effect required for this stage.
                    self.db_manager.update_detection_event(
                        report_id=report_id,
                        person_count=person_count,
                        violation_count=violation_count,
                        severity=severity,
                        status='completed' if early_ready_signaled else 'generating'
                    )
                    progress_status_marked = True
            else:
                # Prepare detection result for the next step.
                detection_result = self.db_manager.insert_detection_event(
                    report_id=report_id,
                    timestamp=timestamp,
                    person_count=person_count,
                    violation_count=violation_count,
                    severity=severity,
                    device_id=device_id or None,
                    status='completed' if early_ready_signaled else 'generating'
                )
            
            # Choose the correct branch before the workflow continues.
            if not detection_result:
                # Trigger the side effect required for this stage.
                logger.error(f"Failed to insert detection event: {report_id}")
                # Continue anyway - local files are still available
            else:
                logger.info(f"Inserted detection event: {report_id}")
                
            # --- START PROGRESS TRACKING ---
            _safe_update_progress('analyzing_scene')
            _record_timing('supabase_detection_event_seconds', timing_started)

        except Exception as e:
            # Trigger the side effect required for this stage.
            logger.error(f"Error inserting detection event: {e}")
            # Continue anyway
        
        # Step 3: Upload artifacts to Supabase Storage
        storage_keys = {}
        try:
            _safe_update_progress('uploading_artifacts')
            timing_started = time.perf_counter()
            
            # Prepare original image path for the next step.
            original_image_path = report_data.get('original_image_path')
            annotated_image_path = report_data.get('annotated_image_path')
            html_path = result.get('html')
            pdf_path = result.get('pdf') if self.upload_pdf else None
            
            # Check if this is a reprocessing operation (should overwrite existing files)
            is_reprocessing = report_data.get('detection_data', {}).get('reprocessed', False)
            
            # The parent generator has already written all local artifacts, so upload
            # them in one pass and avoid extra progress/status round trips.
            upload_results = self.storage_manager.upload_violation_artifacts(
                report_id=report_id,
                original_image_path=Path(original_image_path) if original_image_path else None,
                annotated_image_path=Path(annotated_image_path) if annotated_image_path else None,
                report_html_path=html_path,
                report_pdf_path=pdf_path,
                upsert=is_reprocessing
            )
            for key, value in upload_results.items():
                # Choose the correct branch before the workflow continues.
                if value is not None:
                    # Prepare values needed by the next step.
                    storage_keys[key] = value
            # Trigger the side effect required for this stage.
            _record_timing('supabase_storage_upload_seconds', timing_started)
            
            _safe_update_progress('finalizing')
            logger.info(f"Uploaded artifacts to Supabase Storage: {report_id}")
            
        except Exception as e:
            logger.error(f"Error uploading artifacts to Supabase: {e}")
            # Continue anyway - local files are still available
        
        # Store storage keys in result for reprocessing scenarios
        result['storage_keys'] = storage_keys
        result['generation_timings'] = generation_timings
        
        # Step 4: Persist violation record with storage keys and validation.
        # For reprocessing, update the existing row to avoid stale caption/NLP data drift.
        is_reprocessing = report_data.get('detection_data', {}).get('reprocessed', False)
        try:
            timing_started = time.perf_counter()
            violation_summary = report_data.get('violation_summary')
            caption = report_data.get('caption', '')
            nlp_analysis = result.get('nlp_analysis')
            detection_data = report_data.get('detections')

            # Keep persisted metadata aligned with the already-rendered HTML.
            # The parent generator stabilizes environment_type before HTML render;
            # this guard only catches unexpected legacy paths.
            if isinstance(nlp_analysis, dict):
                stable_env = self._resolve_stable_environment_type(
                    caption,
                    report_data.get('detections', []),
                    nlp_analysis.get('environment_type')
                )
                current_env = str(nlp_analysis.get('environment_type') or '').strip()
                if stable_env and stable_env != current_env:
                    # Trigger the side effect required for this stage.
                    logger.info(
                        f"Stabilizing persisted environment '{current_env}' -> '{stable_env}'"
                    )
                    nlp_analysis['environment_type'] = stable_env
                    nlp_analysis['visual_evidence'] = self._build_scene_description(
                        caption, stable_env, report_data.get('detections', [])
                    )

            # Add validation data to metadata
            # Prepare metadata for the next step.
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
            # Choose the correct branch before the workflow continues.
            if source_scope:
                # Prepare values needed by the next step.
                metadata['source_scope'] = source_scope
            if sync_source:
                metadata['sync_source'] = sync_source
                metadata['source'] = sync_source
            if device_id:
                metadata['device_id'] = device_id
            caption_provider = report_data.get('caption_provider')
            caption_model = report_data.get('caption_model')
            # Choose the correct branch before the workflow continues.
            if caption_provider:
                # Prepare values needed by the next step.
                metadata['caption_provider'] = caption_provider
            if caption_model:
                metadata['caption_model'] = caption_model
            caption_quality_fallback_applied = bool(report_data.get('caption_quality_fallback_applied'))
            caption_quality_reason = str(report_data.get('caption_quality_reason') or '').strip()
            if caption_quality_fallback_applied:
                metadata['caption_quality_fallback_applied'] = True
            if caption_quality_reason:
                metadata['caption_quality_reason'] = caption_quality_reason

            # Choose the correct branch before the workflow continues.
            if isinstance(nlp_analysis, dict):
                # Prepare report provider for the next step.
                report_provider = nlp_analysis.get('provider')
                report_model = nlp_analysis.get('model')
                if report_provider:
                    # Prepare values needed by the next step.
                    metadata['generation_provider'] = report_provider
                if report_model:
                    metadata['generation_model'] = report_model
            nlp_integrity = result.get('nlp_integrity')
            if isinstance(nlp_integrity, dict):
                metadata['nlp_integrity'] = nlp_integrity
            # Choose the correct branch before the workflow continues.
            if validation_result:
                # Prepare values needed by the next step.
                metadata['caption_validation'] = {
                    'is_valid': validation_result['is_valid'],
                    'confidence': validation_result['confidence'],
                    'contradictions': validation_result['contradictions'],
                    'warnings': validation_result['warnings'],
                    'summary': validation_result['validation_summary']
                }
            metadata['generation_timings'] = generation_timings

            # Prepare existing violation for the next step.
            existing_violation = None
            if hasattr(self.db_manager, 'get_violation'):
                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Prepare existing violation for the next step.
                    existing_violation = self.db_manager.get_violation(report_id)
                except Exception as existing_lookup_err:
                    logger.debug(
                        f"Could not check existing violation before persistence for {report_id}: "
                        f"{existing_lookup_err}"
                    )

            # Prepare should update existing for the next step.
            should_update_existing = bool(is_reprocessing or existing_violation)

            if should_update_existing and hasattr(self.db_manager, 'update_violation'):
                # Prepare updated for the next step.
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
                # Choose the correct branch before the workflow continues.
                if updated:
                    # Trigger the side effect required for this stage.
                    logger.info(f"Updated violation record with generated report artifacts: {report_id}")
                else:
                    logger.warning(f"Violation update affected no rows, falling back to insert: {report_id}")
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
                    # Choose the correct branch before the workflow continues.
                    if violation_id:
                        # Trigger the side effect required for this stage.
                        logger.info(f"Inserted violation record after reprocessing fallback: {violation_id}")
                    else:
                        logger.error(f"Failed to persist violation record after reprocessing fallback: {report_id}")
            else:
                # Prepare violation id for the next step.
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

                # Choose the correct branch before the workflow continues.
                if violation_id:
                    # Trigger the side effect required for this stage.
                    logger.info(f"Inserted violation record: {violation_id}")
                else:
                    logger.error(f"Failed to insert violation record: {report_id}")
            # Trigger the side effect required for this stage.
            _record_timing('supabase_violation_persist_seconds', timing_started)

        except Exception as e:
            logger.error(f"Error persisting violation record: {e}")
            # Continue anyway
        
        # Step 5: Log event to flood_logs (skip for reprocessing)
        if not is_reprocessing:
            try:
                timing_started = time.perf_counter()
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
                # Trigger the side effect required for this stage.
                _record_timing('supabase_flood_log_seconds', timing_started)
            except Exception as e:
                logger.error(f"Error logging event: {e}")
                # Continue anyway
        
        # Trigger the side effect required for this stage.
        _record_timing('supabase_report_total_seconds', generation_started)
        result['generation_timings'] = generation_timings
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
    
    # Prepare storage manager for the next step.
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
    
    # Trigger the side effect required for this stage.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load environment variables
    load_dotenv()
    
    print("=" * 70)
    # Trigger the side effect required for this stage.
    print("SUPABASE REPORT GENERATOR TEST")
    print("=" * 70)
    
    # Add parent to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))
    
    from pipeline.config import (
        OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, 
        VIOLATIONS_DIR, REPORTS_DIR, SUPABASE_CONFIG
    )
    
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Create config
        # Prepare config for the next step.
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
        # Prepare generator for the next step.
        generator = create_supabase_report_generator(config)
        
        print(f"\n[OK] Supabase Report Generator initialized")
        print(f"Storage manager: {generator.storage_manager.__class__.__name__}")
        print(f"DB manager: {generator.db_manager.__class__.__name__}")
        print(f"PDF upload: {generator.upload_pdf}")
        
        print("\n[OK] All tests passed!")
        
    except Exception as e:
        # Trigger the side effect required for this stage.
        print(f"\n[X] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Trigger the side effect required for this stage.
    print("=" * 70)
