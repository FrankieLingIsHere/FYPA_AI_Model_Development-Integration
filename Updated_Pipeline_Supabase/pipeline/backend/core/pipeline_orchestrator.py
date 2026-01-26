"""
Pipeline Orchestrator - Main coordinator for the PPE compliance detection system
=================================================================================

This is the HEART of the backend system. It coordinates:
1. YOLO live detection stream
2. Violation detection logic
3. Image capture & pause
4. LLaVA captioning
5. NLP report generation (with RAG)
6. Database logging
7. Resume detection

State Machine:
    IDLE -> DETECTING -> VIOLATION_DETECTED -> PROCESSING -> GENERATING_REPORT -> IDLE

Thread-safe with queues to handle multiple violations.
"""

import logging
import threading
import queue
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from enum import Enum
import cv2
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# STATE DEFINITIONS
# =============================================================================

class PipelineState(Enum):
    """Pipeline state machine states."""
    IDLE = "idle"
    DETECTING = "detecting"
    VIOLATION_DETECTED = "violation_detected"
    PROCESSING = "processing"
    GENERATING_REPORT = "generating_report"
    ERROR = "error"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass
class ViolationEvent:
    """Container for violation event data."""
    timestamp: datetime
    frame_original: np.ndarray  # Unannotated frame
    frame_annotated: np.ndarray  # Annotated frame with bounding boxes
    detections: List[Dict[str, Any]]  # YOLO detections
    violation_summary: str
    person_count: int
    violation_count: int
    severity: str  # 'CRITICAL', 'HIGH', 'LOW'
    report_id: str  # Unique ID for this violation


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class PipelineOrchestrator:
    """
    Main pipeline coordinator.
    
    Manages the entire detection -> processing -> reporting flow.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the pipeline orchestrator.
        
        Args:
            config: Configuration dictionary from config.py
        """
        self.config = config
        self.state = PipelineState.IDLE
        self.state_lock = threading.Lock()
        
        # Violation queue (max 10 as per requirements)
        max_queue = config.get('VIOLATION_RULES', {}).get('max_queue_size', 10)
        self.violation_queue = queue.Queue(maxsize=max_queue)
        
        # Cooldown tracking (1 minute minimum between detections)
        self.last_violation_time: Optional[datetime] = None
        self.cooldown_seconds = config.get('VIOLATION_RULES', {}).get('violation_cooldown', 60)
        
        # Component references (will be injected)
        self.yolo_stream = None
        self.violation_detector = None
        self.image_processor = None
        self.caption_generator = None
        self.report_generator = None
        self.db_manager = None
        
        # Event callbacks for WebSocket notifications
        self.callbacks = {
            'on_violation_detected': [],
            'on_processing_start': [],
            'on_processing_complete': [],
            'on_report_ready': [],
            'on_error': [],
            'on_state_change': []
        }
        
        # Processing thread
        self.processing_thread: Optional[threading.Thread] = None
        self.should_stop = threading.Event()
        
        # Statistics
        self.stats = {
            'total_violations': 0,
            'total_reports': 0,
            'start_time': None,
            'errors': 0
        }
        
        logger.info("Pipeline Orchestrator initialized")
    
    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================
    
    def get_state(self) -> PipelineState:
        """Get current pipeline state (thread-safe)."""
        with self.state_lock:
            return self.state
    
    def set_state(self, new_state: PipelineState):
        """
        Set pipeline state and notify callbacks (thread-safe).
        
        Args:
            new_state: New state to transition to
        """
        with self.state_lock:
            old_state = self.state
            self.state = new_state
            logger.info(f"State transition: {old_state.value} -> {new_state.value}")
            
            # Notify callbacks
            self._trigger_callbacks('on_state_change', {
                'old_state': old_state.value,
                'new_state': new_state.value,
                'timestamp': datetime.now().isoformat()
            })
    
    def is_in_cooldown(self) -> bool:
        """Check if we're still in violation cooldown period."""
        if self.last_violation_time is None:
            return False
        
        elapsed = (datetime.now() - self.last_violation_time).total_seconds()
        return elapsed < self.cooldown_seconds
    
    # =========================================================================
    # COMPONENT INJECTION
    # =========================================================================
    
    def set_yolo_stream(self, yolo_stream):
        """Inject YOLO stream manager."""
        self.yolo_stream = yolo_stream
        logger.debug("YOLO stream manager injected")
    
    def set_violation_detector(self, violation_detector):
        """Inject violation detector."""
        self.violation_detector = violation_detector
        logger.debug("Violation detector injected")
    
    def set_image_processor(self, image_processor):
        """Inject image processor."""
        self.image_processor = image_processor
        logger.debug("Image processor injected")
    
    def set_caption_generator(self, caption_generator):
        """Inject caption generator."""
        self.caption_generator = caption_generator
        logger.debug("Caption generator injected")
    
    def set_report_generator(self, report_generator):
        """Inject report generator."""
        self.report_generator = report_generator
        logger.debug("Report generator injected")
    
    def set_db_manager(self, db_manager):
        """Inject database manager."""
        self.db_manager = db_manager
        logger.debug("Database manager injected")
    
    # =========================================================================
    # CALLBACK SYSTEM
    # =========================================================================
    
    def register_callback(self, event_type: str, callback: Callable):
        """
        Register a callback for events (WebSocket notifications).
        
        Args:
            event_type: Type of event ('on_violation_detected', etc.)
            callback: Function to call when event occurs
        """
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
            logger.debug(f"Registered callback for {event_type}")
        else:
            logger.warning(f"Unknown event type: {event_type}")
    
    def _trigger_callbacks(self, event_type: str, data: Dict[str, Any]):
        """Trigger all callbacks for an event type."""
        if event_type in self.callbacks:
            for callback in self.callbacks[event_type]:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"Callback error for {event_type}: {e}")
    
    
    def _save_metadata(self, report_id: str, data: Dict[str, Any]):
        """
        Save metadata to JSON for recovery/debugging.
        
        Args:
            report_id: Report identifier
            data: Metadata dictionary to save/update
        """
        try:
            violation_dir = self.config['VIOLATIONS_DIR'] / report_id
            violation_dir.mkdir(parents=True, exist_ok=True)
            meta_path = violation_dir / "metadata.json"
            
            # Load existing if present to merge
            current_data = {}
            if meta_path.exists():
                try:
                    with open(meta_path, 'r') as f:
                        current_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Could not read existing metadata: {e}")
            
            # Update
            current_data.update(data)
            
            # Serialize datetime objects
            def json_serial(obj):
                if isinstance(obj, (datetime, datetime.date)):
                    return obj.isoformat()
                raise TypeError (f"Type {type(obj)} not serializable")

            with open(meta_path, 'w') as f:
                json.dump(current_data, f, indent=2, default=json_serial)
                
            logger.debug(f"Saved metadata to {meta_path}")
            
        except Exception as e:
            logger.error(f"Failed to save metadata for {report_id}: {e}")

    # =========================================================================
    # MAIN PIPELINE CONTROL
    # =========================================================================
    
    def start(self):
        """Start the pipeline."""
        if self.state != PipelineState.IDLE and self.state != PipelineState.STOPPED:
            logger.warning(f"Cannot start pipeline in state: {self.state.value}")
            return False
        
        # Reset
        self.should_stop.clear()
        self.stats['start_time'] = datetime.now()
        
        # Start processing thread
        self.processing_thread = threading.Thread(
            target=self._processing_loop,
            name="PipelineProcessingThread",
            daemon=True
        )
        self.processing_thread.start()
        
        # Start YOLO stream
        if self.yolo_stream:
            self.yolo_stream.start(on_frame_callback=self._on_frame_processed)
        
        self.set_state(PipelineState.DETECTING)
        logger.info("[OK] Pipeline started")
        return True
    
    def stop(self):
        """Stop the pipeline."""
        logger.info("Stopping pipeline...")
        self.should_stop.set()
        
        # Stop YOLO stream
        if self.yolo_stream:
            self.yolo_stream.stop()
        
        # Wait for processing thread
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=5)
        
        self.set_state(PipelineState.STOPPED)
        logger.info("[OK] Pipeline stopped")
    
    def pause(self):
        """Pause detection (but continue processing queue)."""
        if self.yolo_stream:
            self.yolo_stream.pause()
        self.set_state(PipelineState.PAUSED)
        logger.info("Pipeline paused")
    
    def resume(self):
        """Resume detection."""
        if self.yolo_stream:
            self.yolo_stream.resume()
        self.set_state(PipelineState.DETECTING)
        logger.info("Pipeline resumed")
    
    # =========================================================================
    # FRAME PROCESSING (Called by YOLO Stream)
    # =========================================================================
    
    def _on_frame_processed(self, frame: np.ndarray, detections: List[Dict[str, Any]]):
        """
        Callback from YOLO stream when a frame is processed.
        
        Args:
            frame: Original frame (unannotated)
            detections: List of YOLO detections
        """
        # Check if we're in cooldown
        if self.is_in_cooldown():
            return
        
        # Check for violations
        if self.violation_detector:
            violation_results = self.violation_detector.check_violations(detections)
            
            if violation_results['has_violation']:
                # VIOLATION DETECTED!
                self._handle_violation_detected(frame, detections, violation_results)
    
    def _handle_violation_detected(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        violation_results: Dict[str, Any]
    ):
        """
        Handle a detected violation.
        
        Args:
            frame: Original frame
            detections: YOLO detections
            violation_results: Violation detection results
        """
        # Update cooldown
        self.last_violation_time = datetime.now()
        
        # Generate report ID in MYT timezone for consistency
        from zoneinfo import ZoneInfo
        myt = ZoneInfo('Asia/Kuala_Lumpur')
        now_myt = datetime.now(myt)
        report_id = now_myt.strftime('%Y%m%d_%H%M%S')
        
        # Create annotated frame (if image processor available)
        frame_annotated = frame.copy()
        if self.image_processor:
            frame_annotated = self.image_processor.annotate_frame(frame, detections)
        
        # Create violation event
        event = ViolationEvent(
            timestamp=datetime.now(),
            frame_original=frame.copy(),
            frame_annotated=frame_annotated,
            detections=detections,
            violation_summary=violation_results['summary'],
            person_count=violation_results['person_count'],
            violation_count=violation_results['violation_count'],
            severity=violation_results['severity'],
            report_id=report_id
        )
        
        # Add to queue
        try:
            self.violation_queue.put_nowait(event)
            self.stats['total_violations'] += 1
            
            logger.warning(f"[!] VIOLATION DETECTED: {event.violation_summary}")
            
            # Notify callbacks
            self._trigger_callbacks('on_violation_detected', {
                'report_id': report_id,
                'summary': event.violation_summary,
                'severity': event.severity,
                'person_count': event.person_count,
                'violation_count': event.violation_count,
                'timestamp': event.timestamp.isoformat()
            })
            
            # Pause YOLO stream (user requirement: pause on violation)
            if self.yolo_stream:
                self.yolo_stream.pause()
            
            self.set_state(PipelineState.VIOLATION_DETECTED)
            
        except queue.Full:
            logger.error("[X] Violation queue is full! Dropping violation.")
            self._trigger_callbacks('on_error', {
                'error': 'Queue full',
                'message': 'Too many violations in queue'
            })
    
    # =========================================================================
    # PROCESSING LOOP (Runs in separate thread)
    # =========================================================================
    
    def _processing_loop(self):
        """Main processing loop for handling violation events."""
        logger.info("Processing loop started")
        
        while not self.should_stop.is_set():
            try:
                # Wait for violation event (timeout to check should_stop)
                event = self.violation_queue.get(timeout=1)
                
                # Process the violation
                self._process_violation_event(event)
                
                self.violation_queue.task_done()
                
            except queue.Empty:
                # No violations in queue, continue waiting
                continue
            except Exception as e:
                logger.error(f"Error in processing loop: {e}", exc_info=True)
                self.stats['errors'] += 1
                self._trigger_callbacks('on_error', {
                    'error': str(e),
                    'context': 'processing_loop'
                })
        
        logger.info("Processing loop stopped")
    
    def _process_violation_event(self, event: ViolationEvent):
        """
        Process a violation event through the entire pipeline.
        
        Steps:
        1. Save images
        2. Generate caption (LLaVA)
        3. Generate NLP report (Llama3 with RAG)
        4. Save to database
        5. Generate PDF
        6. Resume YOLO
        
        Args:
            event: ViolationEvent to process
        """
        self.set_state(PipelineState.PROCESSING)
        
        logger.info(f"Processing violation: {event.report_id}")
        
        # Notify frontend
        self._trigger_callbacks('on_processing_start', {
            'report_id': event.report_id
        })
        
        try:
            # Step 1: Save images
            violation_dir = self.config['VIOLATIONS_DIR'] / event.report_id
            violation_dir.mkdir(parents=True, exist_ok=True)
            
            original_path = violation_dir / 'original.jpg'
            annotated_path = violation_dir / 'annotated.jpg'
            
            cv2.imwrite(str(original_path), event.frame_original)
            cv2.imwrite(str(annotated_path), event.frame_annotated)
            
            logger.debug(f"Images saved: {violation_dir}")
            
            # Save initial metadata
            self._save_metadata(event.report_id, {
                'report_id': event.report_id,
                'timestamp': event.timestamp,
                'violation_summary': event.violation_summary,
                'person_count': event.person_count,
                'violation_count': event.violation_count,
                'severity': event.severity,
                'detections': event.detections,
                'original_image_path': str(original_path),
                'annotated_image_path': str(annotated_path),
                'status': 'processing'
            })
            
            # Step 2: Generate caption
            caption = ""
            if self.caption_generator:
                self.set_state(PipelineState.GENERATING_REPORT)
                caption = self.caption_generator.generate_caption(event.frame_original)
                logger.info(f"Caption generated: {caption[:100]}...")
                
                # Update metadata with caption
                self._save_metadata(event.report_id, {
                    'caption': caption,
                    'status': 'captioned'
                })
            
            # Step 3: Generate NLP report
            nlp_analysis = {}
            report_html_path = None
            report_pdf_path = None
            
            if self.report_generator:
                report_data = {
                    'report_id': event.report_id,
                    'timestamp': event.timestamp,
                    'caption': caption,
                    'detections': event.detections,
                    'violation_summary': event.violation_summary,
                    'person_count': event.person_count,
                    'violation_count': event.violation_count,
                    'severity': event.severity,
                    'original_image_path': str(original_path),
                    'annotated_image_path': str(annotated_path)
                }
                
                # Generate reports (HTML + PDF)
                report_paths = self.report_generator.generate_report(report_data)
                report_html_path = report_paths.get('html')
                report_pdf_path = report_paths.get('pdf')
                nlp_analysis = report_paths.get('nlp_analysis', {})
                
                logger.info(f"Report generated: {report_html_path}")
                
                # Update metadata with NLP results
                self._save_metadata(event.report_id, {
                    'nlp_analysis': nlp_analysis,
                    'report_html_path': str(report_html_path),
                    'report_pdf_path': str(report_pdf_path),
                    'status': 'generated'
                })
            
            # Step 4: Save to database
            if self.db_manager:
                violation_data = {
                    'report_id': event.report_id,
                    'timeframe': event.timestamp,
                    'violation_summary': event.violation_summary,
                    'person_count': event.person_count,
                    'violation_count': event.violation_count,
                    'image_path': str(original_path),
                    'annotated_image_path': str(annotated_path),
                    'caption': caption,
                    'nlp_analysis': nlp_analysis,
                    'report_html_path': str(report_html_path) if report_html_path else None,
                    'report_pdf_path': str(report_pdf_path) if report_pdf_path else None,
                    'detection_data': event.detections
                }
                
                self.db_manager.save_violation(violation_data)
                logger.info(f"Saved to database: {event.report_id}")
            
            self.stats['total_reports'] += 1
            
            # Notify frontend: report ready!
            self._trigger_callbacks('on_report_ready', {
                'report_id': event.report_id,
                'html_path': str(report_html_path) if report_html_path else None,
                'pdf_path': str(report_pdf_path) if report_pdf_path else None,
                'caption': caption,
                'nlp_analysis': nlp_analysis
            })
            
            logger.info(f"[OK] Violation processed successfully: {event.report_id}")
            
        except Exception as e:
            logger.error(f"[X] Error processing violation {event.report_id}: {e}", exc_info=True)
            self.stats['errors'] += 1
            self._trigger_callbacks('on_error', {
                'error': str(e),
                'report_id': event.report_id,
                'context': 'process_violation'
            })
        
        finally:
            # Step 5: Resume YOLO detection (user requirement: resume after processing)
            if self.yolo_stream and self.state != PipelineState.STOPPED:
                self.yolo_stream.resume()
                self.set_state(PipelineState.DETECTING)
            
            self._trigger_callbacks('on_processing_complete', {
                'report_id': event.report_id
            })
    
    # =========================================================================
    # STATUS & STATISTICS
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status."""
        uptime = None
        if self.stats['start_time']:
            uptime = (datetime.now() - self.stats['start_time']).total_seconds()
        
        return {
            'state': self.state.value,
            'queue_size': self.violation_queue.qsize(),
            'in_cooldown': self.is_in_cooldown(),
            'cooldown_remaining': max(0, self.cooldown_seconds - (
                (datetime.now() - self.last_violation_time).total_seconds()
                if self.last_violation_time else 0
            )),
            'statistics': {
                'total_violations': self.stats['total_violations'],
                'total_reports': self.stats['total_reports'],
                'errors': self.stats['errors'],
                'uptime_seconds': uptime
            }
        }


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import *
    
    logging.basicConfig(level=logging.INFO)
    
    # Create orchestrator
    config = {
        'VIOLATION_RULES': VIOLATION_RULES,
        'VIOLATIONS_DIR': VIOLATIONS_DIR
    }
    
    orchestrator = PipelineOrchestrator(config)
    
    print("=" * 70)
    print("PIPELINE ORCHESTRATOR TEST")
    print("=" * 70)
    print(f"\nInitial state: {orchestrator.get_state().value}")
    print(f"Cooldown seconds: {orchestrator.cooldown_seconds}")
    print(f"Queue max size: {orchestrator.violation_queue.maxsize}")
    print(f"In cooldown: {orchestrator.is_in_cooldown()}")
    print("\n[OK] Pipeline Orchestrator initialized successfully")
    print("=" * 70)
