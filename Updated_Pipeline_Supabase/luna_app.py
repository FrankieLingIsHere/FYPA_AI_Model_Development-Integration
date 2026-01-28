"""
LUNA PPE Safety Monitor - Unified Application Server
====================================================

Integrated Flask application that combines:
- Frontend web interface (modern SPA)
- Backend API endpoints
- Live webcam streaming with YOLO detection
- Image upload inference
- Report viewing and management
- Real-time violation detection

This is the SINGLE entry point for the entire system.

Usage:
    python luna_app.py
    
    Then open browser to: http://localhost:5000
"""

import os
import sys
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta
from threading import Lock, Thread
from typing import List, Dict
import json
import time

from flask import Flask, render_template, send_from_directory, jsonify, abort, Response, request, redirect
import cv2
import numpy as np
from PIL import Image
import io
import base64

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import project modules
from infer_image import predict_image

# Import pipeline components for violation handling
try:
    from pipeline.backend.core.violation_detector import ViolationDetector
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
    from pipeline.backend.core.violation_queue import ViolationQueueManager, QueuedViolation
    from pipeline.config import VIOLATION_RULES, LLAVA_CONFIG, OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, VIOLATIONS_DIR, REPORTS_DIR, SUPABASE_CONFIG, get_severity_priority
    FULL_PIPELINE_AVAILABLE = True
except ImportError as e:
    FULL_PIPELINE_AVAILABLE = False
    logging.warning(f"Full pipeline components not available - violations will be detected but reports won't be generated: {e}")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Malaysian Timezone (MYT = UTC+8)
from datetime import timezone
MYT_TIMEZONE = timezone(timedelta(hours=8))

def format_timestamp_myt(ts):
    """
    Format a timestamp for API response with correct MYT (+08:00) timezone.
    Handles: datetime objects, strings, None
    Returns: ISO format string with +08:00 suffix
    """
    if ts is None:
        return None
    
    try:
        if isinstance(ts, str):
            # Parse string to datetime
            if 'T' in ts:
                # ISO format
                if '+' in ts:
                    # Has timezone, remove for parsing then make aware
                    dt = datetime.fromisoformat(ts)
                elif ts.endswith('Z'):
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                else:
                    # Naive ISO
                    dt = datetime.fromisoformat(ts)
            else:
                # Basic YYYY-MM-DD HH:MM:SS
                dt = datetime.strptime(ts.split('.')[0], '%Y-%m-%d %H:%M:%S')
        else:
            # Already datetime
            dt = ts
            
        # Standardize to MYT
        if dt.tzinfo is None:
            # Assume local system time (MYT) if naive
            # DO NOT just attach TZ if it might be UTC naive. 
            # But here we assume system is generating naive local times.
            dt = dt.replace(tzinfo=MYT_TIMEZONE)
        else:
            # Convert to MYT
            dt = dt.astimezone(MYT_TIMEZONE)
            
        return dt.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        
    except Exception as e:
        logger.warning(f"Timestamp formatting error for {ts}: {e}")
        return str(ts)

# =========================================================================
# APPLICATION SETUP
# =========================================================================

app = Flask(__name__, 
            template_folder='frontend',
            static_folder='frontend',
            static_url_path='/static')



# Directories
VIOLATIONS_DIR = Path('pipeline/violations')
VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)

# Thread-safe camera access
camera_lock = Lock()
active_camera = None  # Now can be RealSenseCamera or cv2.VideoCapture

# Import RealSense camera module
try:
    from realsense_camera import RealSenseCamera, create_combined_view, REALSENSE_AVAILABLE
    logger.info(f"RealSense module loaded. SDK available: {REALSENSE_AVAILABLE}")
except ImportError as e:
    REALSENSE_AVAILABLE = False
    RealSenseCamera = None
    create_combined_view = None
    logger.warning(f"RealSense module not available - will use standard webcam: {e}")
except Exception as e:
    REALSENSE_AVAILABLE = False
    RealSenseCamera = None
    create_combined_view = None
    logger.error(f"Error loading RealSense module: {e}")

# Violation detection state
violation_detector = None
caption_generator = None
report_generator = None
db_manager = None
storage_manager = None
last_violation_time = 0

# Initialize Supabase components eagerly at startup for API access
if FULL_PIPELINE_AVAILABLE:
    try:
        logger.info("🔌 Initializing Supabase components...")
        # Note: referencing the global variables defined just above
        db_manager = create_db_manager_from_env()
        logger.info(f"✓ DB Manager initialized: {db_manager is not None}")
        
        storage_manager = create_storage_manager_from_env()
        logger.info(f"✓ Storage Manager initialized: {storage_manager is not None}")
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize Supabase components: {e}")
VIOLATION_COOLDOWN = 3  # seconds between violation CAPTURES (fast - queue handles processing)

# =========================================================================
# SMART VIOLATION DETECTION - Scene State Tracking
# =========================================================================
# Track the current scene to avoid duplicate captures for same person/violation
current_scene_state = {
    'person_count': 0,
    'violation_types': set(),      # e.g., {'NO-Hardhat', 'NO-Mask'}
    'person_positions': [],         # List of (x_center, y_center) normalized positions
    'last_capture_time': 0,
    'last_frame_hash': None         # Simple hash to detect significant frame changes
}

# Smart detection settings
SMART_DETECTION_ENABLED = True      # Set to False to use simple cooldown only
SCENE_REFRESH_INTERVAL = 30         # Seconds before re-capturing same scene (periodic refresh)
POSITION_CHANGE_THRESHOLD = 0.15    # 15% of frame = significant movement (new person entered)
MIN_COOLDOWN_BETWEEN_CAPTURES = 3   # Absolute minimum seconds between ANY captures

# Queue-based violation handling (to prevent missing violations)
violation_queue = None  # ViolationQueueManager instance
queue_worker_thread = None  # Background worker for processing queue
queue_worker_running = False

# =========================================================================
# OLLAMA CONCURRENCY CONTROL
# =========================================================================
# Semaphore to ensure only ONE Ollama call at a time (prevents VRAM exhaustion)
# LLaVA needs ~3.6GB VRAM, multiple concurrent calls will fail
from threading import Semaphore
ollama_semaphore = Semaphore(1)  # Only 1 concurrent Ollama call allowed

# =========================================================================
# ENVIRONMENT VALIDATION SETTINGS
# =========================================================================
# Set to False to DISABLE environment checking (process ALL violations)
# Useful for testing when you can't simulate a real construction site
ENVIRONMENT_VALIDATION_ENABLED = False  # <-- SET TO False TO DISABLE SKIPPING

# How environment classification works:
# 1. LLaVA model analyzes the image and classifies it as:
#    A) CONSTRUCTION/INDUSTRIAL - construction site, factory, warehouse, workshop → VALID
#    B) OFFICE/COMMERCIAL - office, retail, meeting room → VALID (may need PPE)
#    C) RESIDENTIAL/CASUAL - home, living room, park, beach → INVALID (skipped)
#    D) OTHER - unclear scenes → VALID (benefit of doubt)
#
# 2. Only category C (residential/casual) causes skipping
# 3. Categories A, B, D all proceed with report generation

# Keywords used for SECONDARY validation (checking caption content)
# These are checked AFTER environment validation passes
VALID_ENVIRONMENT_KEYWORDS = [
    'construction', 'site', 'worker', 'building', 'scaffold', 'crane', 'excavator',
    'factory', 'warehouse', 'industrial', 'manufacturing', 'machinery', 'equipment',
    'hard hat', 'hardhat', 'safety vest', 'ppe', 'protective', 'helmet',
    'work zone', 'workshop', 'labor', 'labourer', 'employee', 'contractor',
    'concrete', 'steel', 'beam', 'framework', 'renovation', 'demolition',
    'forklift', 'loader', 'truck', 'heavy equipment', 'tools', 'ladder',
    'welding', 'cutting', 'drilling', 'lifting', 'hauling', 'assembly'
]

# Keywords that suggest NON-work environment (only used for warning, not skipping)
INVALID_ENVIRONMENT_KEYWORDS = [
    'living room', 'bedroom', 'kitchen', 'bathroom', 'dining', 'lounge',
    'office desk', 'computer screen', 'monitor', 'keyboard', 'coffee',
    'restaurant', 'cafe', 'park', 'garden', 'beach', 'vacation',
    'selfie', 'portrait', 'family photo', 'pet', 'cat', 'dog'
]

# =========================================================================
# SMART VIOLATION DETECTION - Helper Functions
# =========================================================================

def extract_violation_types(detections):
    """
    Extract set of violation type class names from detections.
    
    Args:
        detections: List of detection dictionaries with 'class_name' key
    
    Returns:
        Set of violation type strings (e.g., {'NO-Hardhat', 'NO-Mask'})
    """
    violation_types = set()
    for det in detections:
        class_name = det.get('class_name', '')
        # Only include actual violations (NO-* classes)
        if class_name.startswith('NO-'):
            violation_types.add(class_name)
    return violation_types


def extract_person_positions(detections, frame_width=1, frame_height=1):
    """
    Extract normalized center positions of persons from detections.
    
    Args:
        detections: List of detection dictionaries with bbox info
        frame_width: Frame width for normalization
        frame_height: Frame height for normalization
    
    Returns:
        List of (x_center, y_center) tuples normalized to 0-1 range
    """
    positions = []
    for det in detections:
        # Look for person-related detections (ones that have violations attached)
        bbox = det.get('bbox', det.get('box', None))
        if bbox and len(bbox) >= 4:
            # Normalize to 0-1 range
            x_center = (bbox[0] + bbox[2]) / 2 / frame_width if frame_width > 1 else (bbox[0] + bbox[2]) / 2
            y_center = (bbox[1] + bbox[3]) / 2 / frame_height if frame_height > 1 else (bbox[1] + bbox[3]) / 2
            positions.append((x_center, y_center))
    return positions


def count_violation_persons(detections):
    """
    Count number of unique persons with violations (based on distinct bounding boxes).
    
    Args:
        detections: List of detection dictionaries
    
    Returns:
        Approximate count of persons with violations
    """
    # Group by approximate position to count unique persons
    positions = extract_person_positions(detections)
    if not positions:
        return len([d for d in detections if d.get('class_name', '').startswith('NO-')])
    
    # Simple deduplication based on position proximity
    unique_count = 0
    used_positions = []
    for pos in positions:
        is_new = True
        for used_pos in used_positions:
            distance = ((pos[0] - used_pos[0])**2 + (pos[1] - used_pos[1])**2)**0.5
            if distance < 0.1:  # Within 10% = same person
                is_new = False
                break
        if is_new:
            unique_count += 1
            used_positions.append(pos)
    
    return max(unique_count, 1) if positions else 1


def significant_position_change(new_positions, old_positions, threshold=None):
    """
    Check if there's a significant position change (person left/entered).
    
    Args:
        new_positions: Current frame positions
        old_positions: Previous capture positions
        threshold: Distance threshold (default: POSITION_CHANGE_THRESHOLD)
    
    Returns:
        True if significant change detected
    """
    if threshold is None:
        threshold = POSITION_CHANGE_THRESHOLD
    
    if not old_positions:
        return True  # First detection
    
    if not new_positions:
        return False  # No new detections
    
    # Check if any new position is far from all old positions (new person entered)
    for new_pos in new_positions:
        closest_distance = min(
            ((new_pos[0] - old_pos[0])**2 + (new_pos[1] - old_pos[1])**2)**0.5
            for old_pos in old_positions
        )
        if closest_distance > threshold:
            return True  # New person entered at different position
    
    return False


def should_capture_violation(detections, frame_width=640, frame_height=480):
    """
    Determine if we should capture a new violation based on scene changes.
    
    Smart detection logic:
    1. New violation TYPE appeared -> CAPTURE
    2. Person count INCREASED -> CAPTURE
    3. Significant position change -> CAPTURE
    4. Scene refresh timeout -> CAPTURE
    5. Otherwise -> SKIP (same scene)
    
    Args:
        detections: Current frame detections
        frame_width: Frame width for position normalization
        frame_height: Frame height for position normalization
    
    Returns:
        Tuple of (should_capture: bool, reason: str)
    """
    global current_scene_state
    
    if not SMART_DETECTION_ENABLED:
        return True, "Smart detection disabled"
    
    current_time = time.time()
    
    # Always enforce minimum cooldown
    time_since_last = current_time - current_scene_state['last_capture_time']
    if time_since_last < MIN_COOLDOWN_BETWEEN_CAPTURES:
        return False, f"Minimum cooldown ({MIN_COOLDOWN_BETWEEN_CAPTURES - time_since_last:.1f}s remaining)"
    
    # Extract current scene info
    new_violation_types = extract_violation_types(detections)
    new_person_count = count_violation_persons(detections)
    new_positions = extract_person_positions(detections, frame_width, frame_height)
    
    # Check 1: New violation type appeared
    if current_scene_state['violation_types']:
        new_types = new_violation_types - current_scene_state['violation_types']
        if new_types:
            logger.info(f"🆕 New violation type(s) detected: {new_types}")
            return True, f"New violation type: {new_types}"
    
    # Check 2: Person count increased
    if new_person_count > current_scene_state['person_count']:
        logger.info(f"🆕 Person count increased: {current_scene_state['person_count']} -> {new_person_count}")
        return True, f"Person count increased: {current_scene_state['person_count']} -> {new_person_count}"
    
    # Check 3: Significant position change (new person entered different area)
    if significant_position_change(new_positions, current_scene_state['person_positions']):
        logger.info("🆕 Significant position change detected")
        return True, "New person entered (position change)"
    
    # Check 4: Scene refresh timeout (periodic re-capture)
    if time_since_last >= SCENE_REFRESH_INTERVAL:
        logger.info(f"🔄 Scene refresh timeout ({SCENE_REFRESH_INTERVAL}s) - re-capturing")
        return True, f"Periodic refresh after {int(time_since_last)}s"
    
    # No significant change - skip capture
    return False, f"Same scene ({int(SCENE_REFRESH_INTERVAL - time_since_last)}s until refresh)"


def update_scene_state(detections, frame_width=640, frame_height=480):
    """
    Update the current scene state after a successful capture.
    
    Args:
        detections: Captured frame detections
        frame_width: Frame width for position normalization
        frame_height: Frame height for position normalization
    """
    global current_scene_state
    
    current_scene_state['violation_types'] = extract_violation_types(detections)
    current_scene_state['person_count'] = count_violation_persons(detections)
    current_scene_state['person_positions'] = extract_person_positions(detections, frame_width, frame_height)
    current_scene_state['last_capture_time'] = time.time()
    
    logger.debug(f"Scene state updated: {current_scene_state['person_count']} person(s), {current_scene_state['violation_types']}")


# =========================================================================
# VIOLATION PROCESSING
# =========================================================================

def initialize_pipeline_components():
    """Initialize violation detector, caption generator, report generator, and Supabase managers."""
    global violation_detector, caption_generator, report_generator, db_manager, storage_manager
    global violation_queue, queue_worker_thread, queue_worker_running
    
    if not FULL_PIPELINE_AVAILABLE:
        logger.warning("Full pipeline not available - skipping component initialization")
        return False
    
    try:
        if violation_detector is None:
            logger.info("Initializing violation detector...")
            violation_detector = ViolationDetector(VIOLATION_RULES)
            
        if caption_generator is None:
            logger.info("Initializing caption generator...")
            caption_config = {'LLAVA_CONFIG': LLAVA_CONFIG}
            caption_generator = CaptionGenerator(caption_config)
        
        if db_manager is None:
            logger.info("Initializing Supabase database manager...")
            db_manager = create_db_manager_from_env()
            
            # Fix historical timestamp issues
            if db_manager and hasattr(db_manager, 'fix_timestamp_issues'):
                logger.info("Fixing timestamp issues...")
                db_manager.fix_timestamp_issues()
            
            # Fix any stuck reports from previous sessions
            if db_manager and hasattr(db_manager, 'get_stuck_report_ids'):
                logger.info("Checking for stuck reports...")
                stuck_ids = db_manager.get_stuck_report_ids(minutes_threshold=1) # 1 min for testing logic
                if stuck_ids:
                    logger.info(f"⚠️ Found {len(stuck_ids)} stuck reports. Attempting validation/reprocessing...")
                    
                    # Start a background thread to reprocess them so we don't block startup
                    Thread(target=reprocess_stuck_reports, args=(stuck_ids,), daemon=True).start()
        
        if storage_manager is None:
            logger.info("Initializing Supabase storage manager...")
            storage_manager = create_storage_manager_from_env()
            
        if report_generator is None:
            logger.info("Initializing Supabase report generator...")
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
        
        # Initialize violation queue for handling multiple violations
        if violation_queue is None:
            logger.info("Initializing violation queue manager...")
            violation_queue = ViolationQueueManager(
                max_size=100,           # Max violations in queue
                rate_limit_per_device=20,  # Allow more per device before rate limiting
                rate_limit_window=60,   # Per minute
                max_retries=3
            )
            logger.info(f"✓ Violation queue initialized (max_size=100)")
        
        # Start queue worker thread if not running
        if not queue_worker_running:
            logger.info("Starting violation queue worker thread...")
            start_queue_worker()
            
        logger.info("[OK] All pipeline components initialized")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing pipeline components: {e}")
        import traceback
        traceback.print_exc()
        return False


def reprocess_stuck_reports(report_ids: List[str]):
    """
    Background task to attempting to generate reports for stuck items.
    Tries to recover data from disk (metadata.json) or re-run inference (original.jpg).
    """
    logger.info(f"🔄 Starting reprocessing for {len(report_ids)} stuck reports...")
    
    count = 0
    for report_id in report_ids:
        try:
            violation_dir = VIOLATIONS_DIR.absolute() / report_id
            if not violation_dir.exists():
                logger.warning(f"❌ Cannot reprocess {report_id}: Directory not found on disk")
                db_manager.update_detection_status(report_id, 'failed', "Data lost: Directory missing")
                continue
                
            original_path = violation_dir / 'original.jpg'
            annotated_path = violation_dir / 'annotated.jpg'
            metadata_path = violation_dir / 'metadata.json'
            
            detections = []
            timestamp = datetime.now()
            
            # Strategy 1: Load from metadata (Best)
            if metadata_path.exists():
                logger.info(f"   Recovering {report_id} from metadata...")
                try:
                    with open(metadata_path, 'r') as f:
                        meta = json.load(f)
                        detections = meta.get('detections', []) # Note: metadata might not have raw detections
                        # If metadata doesn't have detections, we might fallback to Strategy 2
                        if not detections and 'person_count' in meta: 
                             # Partial metadata, fallback to re-inference
                             pass
                        else:
                            # Use metadata timestamp if available
                            ts_str = meta.get('timestamp')
                            # parser logic... skip for brevity and use DB timestamp if needed
                except Exception as e:
                    logger.warning(f"   Metadata corrupted: {e}")
            
            # Strategy 2: Re-run Inference (Fallback)
            if not detections and original_path.exists():
                logger.info(f"   Re-running inference for {report_id}...")
                image = cv2.imread(str(original_path))
                if image is not None:
                     # Re-run prediction
                     res_detections, _ = predict_image(image, conf=0.25)
                     detections = res_detections
                else:
                     logger.warning(f"   Could not read image for {report_id}")
            
            if not detections:
                 logger.error(f"❌ Failed to recover data for {report_id}")
                 db_manager.update_detection_status(report_id, 'failed', "Data recovery failed")
                 continue
            
            # Construct violation types and tags correctly
            violation_keywords = ['no-hardhat', 'no-gloves', 'no-safety vest', 'no-mask', 'no-goggles']
            violation_detections = [d for d in detections 
                                   if any(keyword in d['class_name'].lower() 
                                         for keyword in violation_keywords)]
            
            violation_types = [d['class_name'] for d in violation_detections]
            
            # Extract missing PPE for logic
            missing_ppe = []
            for d in detections:
                cls = d.get('class_name', '')
                if cls.startswith('NO-'):
                    ppe = cls.replace('NO-', '')
                    if ppe not in missing_ppe:
                        missing_ppe.append(ppe)
            
            # Re-queue it!
            logger.info(f"   Queuing {report_id} for processing...")
            
            # Retrieve timestamp from DB if possible to keep original time
            event = db_manager.get_detection_event(report_id)
            if event and event.get('timestamp'):
                timestamp = event['timestamp']
            
            violation_data = {
                'report_id': report_id,
                'timestamp': timestamp,
                'detections': detections,
                'violation_types': violation_types,
                'violation_count': len(violation_types),
                'original_image_path': str(original_path),
                'annotated_image_path': str(annotated_path),
                'violation_dir': str(violation_dir)
            }
            
            # Add to queue with recovery device ID
            if violation_queue:
                violation_queue.enqueue(
                    violation_data=violation_data,
                    device_id='recovery',
                    report_id=report_id,
                    severity='HIGH'
                )
                count += 1
                
        except Exception as e:
            logger.error(f"Error reprocessing {report_id}: {e}")
            
    logger.info(f"🔄 Reprocessing triggered for {count} reports")


def start_queue_worker():
    """Start the background worker thread for processing queued violations."""
    global queue_worker_thread, queue_worker_running
    
    if queue_worker_running:
        logger.warning("Queue worker already running")
        return
    
    queue_worker_running = True
    queue_worker_thread = Thread(
        target=queue_worker_loop,
        name="ViolationQueueWorker",
        daemon=True
    )
    queue_worker_thread.start()
    logger.info(f"✓ Queue worker thread started (Thread ID: {queue_worker_thread.ident})")


def stop_queue_worker():
    """Stop the background queue worker thread."""
    global queue_worker_running
    queue_worker_running = False
    logger.info("Queue worker stop requested")


def queue_worker_loop():
    """
    Main loop for the queue worker thread.
    Processes violations from the queue one at a time.
    """
    global queue_worker_running
    
    logger.info("Queue worker loop started - waiting for violations...")
    
    while queue_worker_running:
        try:
            if violation_queue is None:
                time.sleep(1)
                continue
            
            # Try to get next violation from queue (with timeout)
            queued_violation = violation_queue.dequeue(timeout=2.0)
            
            if queued_violation is None:
                # No violation in queue, continue waiting
                continue
            
            logger.info(f"📥 Dequeued violation {queued_violation.report_id} for processing")
            
            try:
                # Process the violation
                process_queued_violation(queued_violation)
                violation_queue.mark_processed(queued_violation)
                logger.info(f"✅ Completed processing {queued_violation.report_id}")
                
            except Exception as e:
                logger.error(f"❌ Error processing {queued_violation.report_id}: {e}")
                # Requeue for retry
                if not violation_queue.requeue(queued_violation):
                    logger.error(f"Max retries exceeded for {queued_violation.report_id}")
                    # Update status to failed
                    if db_manager:
                        try:
                            db_manager.update_detection_status(
                                queued_violation.report_id, 
                                'failed', 
                                f"Max retries exceeded: {str(e)}"
                            )
                        except Exception as e2:
                            logger.warning(f"Could not update status: {e2}")
                            
        except Exception as e:
            logger.error(f"Queue worker error: {e}")
            time.sleep(1)
    
    logger.info("Queue worker loop stopped")


def enqueue_violation(frame: np.ndarray, detections: List[Dict], force: bool = False, annotated_frame: np.ndarray = None) -> str:
    """
    Capture a violation and add it to the processing queue.
    Uses SMART DETECTION to only capture when:
    - New violation TYPE appears
    - New PERSON enters the frame
    - Significant POSITION change detected
    - Periodic refresh timeout reached
    - force=True (e.g., manual upload)
    
    Args:
        frame: The video frame with the violation
        detections: List of YOLO detections
        force: If True, bypass smart detection and cooldown checks
        annotated_frame: Optional pre-annotated frame to use (avoids re-inference mismatches)
    
    Returns:
        report_id if successfully queued, None otherwise
    """
    global last_violation_time
    
    logger.info("=" * 80)
    logger.info(f"ENQUEUE_VIOLATION CALLED (Smart Detection{' - FORCED' if force else ''})")
    logger.info("=" * 80)
    
    try:
        # Get frame dimensions for position normalization
        frame_height, frame_width = frame.shape[:2] if frame is not None else (480, 640)
        
        # Check for violations first
        violation_keywords = ['no-hardhat', 'no-gloves', 'no-safety vest', 
                             'no-mask', 'no-goggles']
        
        violation_detections = [d for d in detections 
                               if any(keyword in d['class_name'].lower() 
                                     for keyword in violation_keywords)]
        
        if not violation_detections:
            logger.warning("No violations found in detections")
            return None
        
        # === SMART DETECTION CHECK ===
        if not force:
            # Determine if we should capture based on scene changes
            should_capture, reason = should_capture_violation(detections, frame_width, frame_height)
            
            if not should_capture:
                logger.info(f"⏭️ Skipping capture: {reason}")
                return None
            
            logger.info(f"✅ Capture triggered: {reason}")
        else:
            logger.info("✅ Capture forced (manual upload)")
        
        violation_types = [d['class_name'] for d in violation_detections]
        logger.info(f"🚨 PPE VIOLATION DETECTED: {violation_types}")
        
        # Create violation directory with timestamp
        timestamp = datetime.now()
        report_id = timestamp.strftime('%Y%m%d_%H%M%S')
        violation_dir = VIOLATIONS_DIR.absolute() / report_id
        violation_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Created violation directory: {violation_dir}")
        
        # === IMMEDIATE: Save images (fast operation) ===
        # Save original frame
        original_path = violation_dir / 'original.jpg'
        cv2.imwrite(str(original_path), frame)
        logger.info(f"✓ Saved original image: {original_path}")
        
        # Save annotated frame (Use provided one or regenerate)
        annotated_path = violation_dir / 'annotated.jpg'
        if annotated_frame is not None:
             cv2.imwrite(str(annotated_path), annotated_frame)
             logger.info(f"✓ Saved PROVIDED annotated image: {annotated_path}")
        else:
            logger.info("   Regenerating annotated image (no pre-annotated frame provided)...")
            _, annotated = predict_image(frame, conf=0.25)
            cv2.imwrite(str(annotated_path), annotated)
            logger.info(f"✓ Saved generated annotated image: {annotated_path}")
        
        # === IMMEDIATE: Insert pending detection event ===
        if db_manager:
            try:
                db_manager.insert_detection_event(
                    report_id=report_id,
                    timestamp=timestamp,
                    person_count=len([d for d in detections if 'person' in d['class_name'].lower()]),
                    violation_count=len(violation_detections),
                    severity='HIGH',
                    status='pending'
                )
                logger.info(f"✓ Inserted PENDING detection event: {report_id}")
            except Exception as e:
                logger.error(f"Failed to insert pending event: {e}")
        
        # === QUEUE: Add to queue for async processing ===
        if violation_queue:
            violation_data = {
                'report_id': report_id,
                'timestamp': timestamp,
                'detections': detections,
                'violation_types': violation_types,
                'violation_count': len(violation_detections),
                'original_image_path': str(original_path),
                'annotated_image_path': str(annotated_path),
                'violation_dir': str(violation_dir)
            }
            
            success = violation_queue.enqueue(
                violation_data=violation_data,
                device_id='webcam_0',
                report_id=report_id,
                severity='HIGH'
            )
            
            if success:
                logger.info(f"✓ Violation {report_id} added to processing queue")
                queue_stats = violation_queue.get_stats()
                logger.info(f"   Queue size: {queue_stats['current_size']}/{queue_stats['capacity']}")
                
                # Update scene state for smart detection
                update_scene_state(detections, frame_width, frame_height)
                logger.info(f"   Scene state updated: {len(current_scene_state['violation_types'])} violation type(s), {current_scene_state['person_count']} person(s)")
                
                return report_id
            else:
                logger.error("Failed to add violation to queue")
                return report_id  # Still return ID - images saved, just won't be processed
        else:
            # Queue not available - log error but DON'T fallback to direct processing
            # (avoids concurrent Ollama calls that cause VRAM exhaustion)
            logger.error("Violation queue not initialized - violation captured but won't be processed")
            logger.error("Restart the server to initialize the queue worker")
            return report_id  # Images are saved, can be reprocessed manually
        
        return None
        
    except Exception as e:
        logger.error(f"Error enqueuing violation: {e}", exc_info=True)
        return None


def process_queued_violation(queued_violation: 'QueuedViolation'):
    """
    Process a violation from the queue.
    Validates environment first, then generates caption and report.
    
    Args:
        queued_violation: The queued violation object with data
    """
    data = queued_violation.data
    report_id = data['report_id']
    violation_dir = Path(data['violation_dir'])
    timestamp = data['timestamp']
    detections = data['detections']
    violation_types = data['violation_types']
    original_path = Path(data['original_image_path'])
    annotated_path = Path(data['annotated_image_path'])
    
    logger.info(f"📄 Processing queued violation: {report_id}")
    
    # === ENVIRONMENT VALIDATION (before heavy processing) ===
    # Uses semaphore to prevent concurrent Ollama calls (VRAM exhaustion)
    if ENVIRONMENT_VALIDATION_ENABLED:
        try:
            from caption_image import validate_work_environment
            
            logger.info("🔍 Validating work environment (acquiring Ollama lock)...")
            with ollama_semaphore:  # Only one Ollama call at a time
                env_result = validate_work_environment(str(original_path))
            
            logger.info(f"   Environment: {env_result['environment_type']} (confidence: {env_result['confidence']})")
            logger.info(f"   Is valid work environment: {env_result['is_valid']}")
            
            # Save environment validation result
            env_validation_path = violation_dir / 'environment_validation.json'
            with open(env_validation_path, 'w') as f:
                json.dump(env_result, f, indent=2)
            
            if not env_result['is_valid']:
                logger.warning(f"⚠️ SKIPPING violation {report_id} - not a valid work environment")
                logger.warning(f"   Reason: {env_result['reason']}")
                
                # Update status to 'skipped' and clean up
                if db_manager:
                    try:
                        db_manager.update_detection_status(
                            report_id, 
                            'skipped', 
                            f"Not a work environment: {env_result['environment_type']}"
                        )
                    except Exception as e:
                        logger.warning(f"Could not update status: {e}")
                
                # Create a "skipped" marker file instead of full report
                skip_report_path = violation_dir / 'SKIPPED_NOT_WORK_ENVIRONMENT.txt'
                with open(skip_report_path, 'w') as f:
                    f.write(f"Violation {report_id} was skipped.\n")
                    f.write(f"Reason: Scene detected as '{env_result['environment_type']}'\n")
                    f.write(f"This does not appear to be a construction/industrial environment.\n")
                    f.write(f"Raw result: {env_result['reason']}\n")
                
                return  # Skip processing this violation
                
        except ImportError:
            logger.warning("validate_work_environment not available - skipping environment check")
        except Exception as e:
            logger.warning(f"Environment validation failed: {e} - proceeding with processing")
    
    # Update status to generating
    if db_manager:
        try:
            db_manager.update_detection_status(report_id, 'generating')
            logger.info(f"✓ Status updated to GENERATING: {report_id}")
        except Exception as e:
            logger.warning(f"Could not update status: {e}")
    
    # Generate caption (with semaphore to prevent concurrent Ollama calls)
    caption = ""
    env_context = ""
    if caption_generator:
        try:
            logger.info("🎨 Generating image caption with LLaVA (acquiring Ollama lock)...")
            
            # Free up GPU memory before heavy captioning operation
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("   Cleared CUDA cache before caption generation")
            except Exception as gpu_e:
                logger.debug(f"   Could not clear CUDA cache: {gpu_e}")
            
            with ollama_semaphore:  # Only one Ollama call at a time
                caption = caption_generator.generate_caption(str(original_path))
            if caption:
                caption_path = violation_dir / 'caption.txt'
                with open(caption_path, 'w', encoding='utf-8') as f:
                    f.write(caption)
                logger.info(f"✓ Caption saved: {caption_path}")
                
                # Secondary validation: check caption content for work environment indicators
                caption_lower = caption.lower()
                has_work_indicators = any(kw in caption_lower for kw in VALID_ENVIRONMENT_KEYWORDS)
                has_invalid_indicators = any(kw in caption_lower for kw in INVALID_ENVIRONMENT_KEYWORDS)
                
                if has_invalid_indicators and not has_work_indicators:
                    logger.warning(f"⚠️ Caption suggests non-work environment: {caption[:100]}...")
                    env_context = " [Warning: Scene may not be a typical work environment]"
                    
            else:
                caption = "Caption generation returned empty"
        except Exception as e:
            logger.error(f"❌ Caption generation failed: {e}")
            caption = "Caption generation failed"
    else:
        caption = "Image captioning not available"
        caption_path = violation_dir / 'caption.txt'
        with open(caption_path, 'w', encoding='utf-8') as f:
            f.write(caption)
    
    # Generate report
    report_created = False
    if report_generator:
        try:
            logger.info("📄 Generating NLP report with Llama3...")
            
            report_data = {
                'report_id': report_id,
                'timestamp': timestamp,
                'detections': detections,
                'violation_summary': f"PPE Violation Detected: {', '.join(violation_types)}",
                'violation_count': len(violation_types),
                'caption': caption,
                'image_caption': caption,
                'original_image_path': str(original_path),
                'annotated_image_path': str(annotated_path),
                'location': 'Live Stream Monitor',
                'severity': 'HIGH',
                'person_count': len(detections)
            }
            
            logger.info("📄 Generating NLP report with Llama3 (acquiring Ollama lock)...")
            with ollama_semaphore:
                result = report_generator.generate_report(report_data)
            
            if result and result.get('html'):
                target_html = violation_dir / 'report.html'
                if target_html.exists():
                    logger.info(f"✓ Report generated: {target_html}")
                    report_created = True
                    
                    # Update status to completed
                    if db_manager:
                        try:
                            db_manager.update_detection_status(report_id, 'completed')
                            logger.info(f"✓ Status updated to COMPLETED: {report_id}")
                        except Exception as e:
                            logger.warning(f"Could not update status: {e}")
                            
        except Exception as e:
            logger.error(f"❌ Report generation failed: {e}")
            if db_manager:
                try:
                    db_manager.update_detection_status(report_id, 'failed', str(e))
                except Exception as e2:
                    logger.warning(f"Could not update status: {e2}")
    
    # Create placeholder if report generation failed
    if not report_created:
        create_placeholder_report(violation_dir, report_id, timestamp, detections, caption)
    
    # Extract missing PPE and count persons for metadata
    missing_ppe = []
    person_count = 0
    for d in detections:
        cls = d.get('class_name', '')
        if cls.startswith('NO-'):
            ppe = cls.replace('NO-', '')
            if ppe not in missing_ppe:
                missing_ppe.append(ppe)
        if 'person' in cls.lower():
            person_count += 1
            
    # Normalize PPE names for tags
    ppe_tags = [f"NO-{p.upper()}" for p in missing_ppe]
    violation_summary = f"PPE Violation Detected: {', '.join([f'NO-{p}' for p in missing_ppe])}" if missing_ppe else "PPE Violation"

    # Calculate severity dynamically
    severity = 'LOW'
    min_priority = 4  # Lower number = Higher priority (1=Critical, 4=Low)
    
    if not missing_ppe:
        # No specific PPE missing, but violation occurred (e.g. unknown class)
        severity = 'MEDIUM'
    else:
        for ppe in missing_ppe:
            # Check config for this PPE
            ppe_key = ppe.lower()
            if ppe_key in VIOLATION_RULES.get('required_ppe', {}):
                rule_severity = VIOLATION_RULES['required_ppe'][ppe_key].get('severity', 'LOW')
                rule_priority = get_severity_priority(rule_severity)
                
                if rule_priority < min_priority:
                    min_priority = rule_priority
                    severity = rule_severity
            
            # Check for critical overrides
            if f"NO-{ppe}" in VIOLATION_RULES.get('critical', {}):
                severity = 'HIGH'  # User requested checks map to HIGH, not CRITICAL
                min_priority = 2


    # Save metadata
    metadata = {
        'report_id': report_id,
        'timestamp': format_timestamp_myt(timestamp),
        'violation_type': violation_types[0] if violation_types else 'PPE Violation',
        'violation_summary': violation_summary,
        'severity': severity,
        'location': 'Live Stream Monitor',
        'detection_count': len(detections),
        'violation_count': len(missing_ppe) if missing_ppe else 1,
        'person_count': max(1, person_count),  # Ensure at least 1 person if report generated
        'missing_ppe': missing_ppe,
        'ppe_tags': ppe_tags,
        'has_caption': bool(caption),
        'has_report': report_created
    }
    
    metadata_path = violation_dir / 'metadata.json'
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"✅ Queued violation processing complete: {report_id}")


def create_placeholder_report(violation_dir: Path, report_id: str, timestamp, detections: List, caption: str):
    """Create a placeholder HTML report when generation fails."""
    report_html_path = violation_dir / 'report.html'
    placeholder_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Violation Report - {report_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #d32f2f; }}
        .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .info {{ background: #e3f2fd; border-left: 4px solid #2196f3; padding: 15px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚨 PPE Violation Report</h1>
        <p><strong>Report ID:</strong> {report_id}</p>
        <p><strong>Timestamp:</strong> {timestamp}</p>
        <p><strong>Severity:</strong> HIGH</p>
        
        <div class="warning">
            <h3>⚠️ Report Generator Not Available</h3>
            <p>The NLP report generator (Llama3) is not configured or not running.</p>
        </div>
        
        <div class="info">
            <h3>📋 Detection Summary</h3>
            <p><strong>Detections:</strong> {len(detections)}</p>
        </div>
        
        <h3>📸 Images</h3>
        <p>Original: <a href="original.jpg">original.jpg</a></p>
        <p>Annotated: <a href="annotated.jpg">annotated.jpg</a></p>
        
        <h3>📝 Caption</h3>
        <p>{caption if caption else 'No caption available'}</p>
    </div>
</body>
</html>"""
    with open(report_html_path, 'w', encoding='utf-8') as f:
        f.write(placeholder_html)
    logger.info(f"✓ Placeholder report saved: {report_html_path}")


def process_violation(frame: np.ndarray, detections: List[Dict]):
    """
    Process a detected violation: save images, generate caption and report.
    Runs in background thread to not block streaming.
    """
    global last_violation_time
    
    logger.info("=" * 80)
    logger.info("PROCESS_VIOLATION CALLED")
    logger.info("=" * 80)
    
    try:
        # Check cooldown
        current_time = time.time()
        if current_time - last_violation_time < VIOLATION_COOLDOWN:
            logger.info(f"Violation cooldown active ({int(VIOLATION_COOLDOWN - (current_time - last_violation_time))}s remaining)")
            return
        
        last_violation_time = current_time
        
        # Check for ANY PPE violations (match actual model class names)
        violation_keywords = ['no-hardhat', 'no-gloves', 'no-safety vest', 
                             'no-mask', 'no-goggles']
        
        violation_detections = [d for d in detections 
                               if any(keyword in d['class_name'].lower() 
                                     for keyword in violation_keywords)]
        
        if not violation_detections:
            logger.warning("No violations found in detections")
            return
        
        violation_types = [d['class_name'] for d in violation_detections]
        logger.info(f"🚨 PPE VIOLATION DETECTED: {violation_types}")
        logger.info("   Starting full processing...")
        logger.info(f"   Pipeline available: {FULL_PIPELINE_AVAILABLE}")
        logger.info(f"   Caption generator: {'✓ Available' if caption_generator else '✗ Not initialized'}")
        logger.info(f"   Report generator: {'✓ Available' if report_generator else '✗ Not initialized'}")
        
        # Create violation directory with absolute path
        timestamp = datetime.now()
        report_id = timestamp.strftime('%Y%m%d_%H%M%S')
        violation_dir = VIOLATIONS_DIR.absolute() / report_id
        violation_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Created violation directory: {violation_dir}")
        
        # === IMMEDIATE: Insert "pending" detection event ===
        # This makes the violation visible in the frontend immediately
        if db_manager:
            try:
                db_manager.insert_detection_event(
                    report_id=report_id,
                    timestamp=timestamp,
                    person_count=len([d for d in detections if 'person' in d['class_name'].lower()]),
                    violation_count=len(violation_detections),
                    severity='HIGH',
                    status='pending'
                )
                logger.info(f"✓ Inserted PENDING detection event: {report_id} (visible in frontend now)")
            except Exception as e:
                logger.error(f"Failed to insert pending event: {e}")
        
        # Save original frame
        original_path = violation_dir / 'original.jpg'
        cv2.imwrite(str(original_path), frame)
        logger.info(f"✓ Saved original image: {original_path}")
        
        # Save annotated frame
        _, annotated = predict_image(frame, conf=0.25)
        annotated_path = violation_dir / 'annotated.jpg'
        cv2.imwrite(str(annotated_path), annotated)
        logger.info(f"✓ Saved annotated image: {annotated_path}")
        
        # Generate caption if available
        caption = ""
        logger.info(f"Caption generator status: {caption_generator is not None}")
        
        if caption_generator:
            try:
                logger.info("🎨 Generating image caption with LLaVA...")
                caption = caption_generator.generate_caption(str(original_path))
                if caption:
                    caption_path = violation_dir / 'caption.txt'
                    with open(caption_path, 'w', encoding='utf-8') as f:
                        f.write(caption)
                    logger.info(f"✓ Caption saved: {caption_path}")
                    logger.info(f"  Caption preview: {caption[:100]}...")
                else:
                    logger.error("Caption generation returned None or empty string")
                    caption = "Caption generation returned empty"
            except Exception as e:
                logger.error(f"❌ Caption generation failed: {e}", exc_info=True)
                caption = "Caption generation failed"
        else:
            # Save placeholder caption even if generator not available
            logger.warning("Caption generator not available - saving placeholder")
            caption = "Image captioning not available - LLaVA model not loaded. Install dependencies: pip install transformers accelerate bitsandbytes"
            caption_path = violation_dir / 'caption.txt'
            with open(caption_path, 'w', encoding='utf-8') as f:
                f.write(caption)
            logger.info(f"✓ Placeholder caption saved: {caption_path}")
        
        # Generate report if available
        report_created = False
        logger.info(f"Report generator status: {report_generator is not None}")
        
        if report_generator:
            try:
                # Update status to "generating"
                if db_manager:
                    try:
                        db_manager.update_detection_status(report_id, 'generating')
                        logger.info(f"✓ Status updated to GENERATING: {report_id}")
                    except Exception as e:
                        logger.warning(f"Could not update status: {e}")
                
                logger.info("📄 Generating NLP report with Llama3...")
                
                report_data = {
                    'report_id': report_id,
                    'timestamp': timestamp,
                    'detections': detections,
                    'violation_summary': f"PPE Violation Detected: {', '.join(violation_types)}",
                    'violation_count': len(violation_detections),
                    'caption': caption,
                    'image_caption': caption,
                    'original_image_path': str(original_path),
                    'annotated_image_path': str(annotated_path),
                    'location': 'Live Stream Monitor',
                    'severity': 'HIGH',
                    'person_count': len(detections)
                }
                
                # generate_report returns dict with 'html' and 'pdf' keys
                # Note: ReportGenerator already copies the report to violations folder
                logger.info("Calling report_generator.generate_report()...")
                result = report_generator.generate_report(report_data)
                logger.info(f"Report generation result: {result}")
                
                if result and result.get('html'):
                    # Check if report was created in violations directory
                    target_html = violation_dir / 'report.html'
                    if target_html.exists():
                        logger.info(f"✓ Report generated: {target_html}")
                        report_created = True
                        # Update status to "completed"
                        if db_manager:
                            try:
                                db_manager.update_detection_status(report_id, 'completed')
                                logger.info(f"✓ Status updated to COMPLETED: {report_id}")
                            except Exception as e:
                                logger.warning(f"Could not update status: {e}")
                    else:
                        logger.warning(f"❌ Report not found in violations directory: {target_html}")
                else:
                    logger.warning(f"❌ Report generation returned None or no HTML path. Result: {result}")
                    
            except Exception as e:
                logger.error(f"❌ Report generation failed: {e}", exc_info=True)
                # Update status to "failed"
                if db_manager:
                    try:
                        db_manager.update_detection_status(report_id, 'failed', str(e))
                        logger.info(f"✓ Status updated to FAILED: {report_id}")
                    except Exception as e2:
                        logger.warning(f"Could not update status: {e2}")
        
        # Create placeholder report if generation failed or unavailable
        if not report_created:
            # Create placeholder report even if generator not available
            if report_generator is None:
                logger.warning("Report generator is None - creating placeholder report")
            else:
                logger.warning("Report generator exists but failed to create report - creating placeholder")
            report_html_path = violation_dir / 'report.html'
            placeholder_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Violation Report - {report_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #d32f2f; }}
        .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .info {{ background: #e3f2fd; border-left: 4px solid #2196f3; padding: 15px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚨 PPE Violation Report</h1>
        <p><strong>Report ID:</strong> {report_id}</p>
        <p><strong>Timestamp:</strong> {timestamp}</p>
        <p><strong>Violation Type:</strong> NO-HARDHAT</p>
        <p><strong>Severity:</strong> HIGH</p>
        
        <div class="warning">
            <h3>⚠️ Report Generator Not Available</h3>
            <p>The NLP report generator (Llama3) is not configured or not running.</p>
            <p>To enable full report generation:</p>
            <ol>
                <li>Install Ollama: <a href="https://ollama.ai" target="_blank">https://ollama.ai</a></li>
                <li>Run: <code>ollama serve</code></li>
                <li>Run: <code>ollama pull llama3</code></li>
                <li>Restart LUNA</li>
            </ol>
        </div>
        
        <div class="info">
            <h3>📋 Detection Summary</h3>
            <p><strong>Detections:</strong> {len(detections)}</p>
            <p><strong>NO-HARDHAT Count:</strong> {sum(1 for d in detections if 'no-hardhat' in d['class_name'].lower())}</p>
        </div>
        
        <h3>📸 Images</h3>
        <p>Original: <a href="original.jpg">original.jpg</a></p>
        <p>Annotated: <a href="annotated.jpg">annotated.jpg</a></p>
        
        <h3>📝 Caption</h3>
        <p>{caption if caption else 'No caption available'}</p>
    </div>
</body>
</html>"""
            with open(report_html_path, 'w', encoding='utf-8') as f:
                f.write(placeholder_html)
            logger.info(f"✓ Placeholder report saved: {report_html_path}")
        
        # Save metadata
        metadata = {
            'report_id': report_id,
            'timestamp': timestamp.isoformat(),
            'violation_type': 'NO-HARDHAT',
            'severity': 'HIGH',
            'location': 'Live Stream Monitor',
            'detection_count': len(detections),
            'no_hardhat_count': sum(1 for d in detections if 'no-hardhat' in d['class_name'].lower()),
            'has_caption': bool(caption),
            'has_report': report_generator is not None
        }
        
        metadata_path = violation_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"✓ Metadata saved: {metadata_path}")
        
        logger.info(f"✅ VIOLATION PROCESSING COMPLETE: {report_id}")
        logger.info(f"   - Location: {violation_dir}")
        logger.info(f"   - Files: original.jpg, annotated.jpg, caption.txt, report.html, metadata.json")
        
    except Exception as e:
        logger.error(f"Error processing violation: {e}", exc_info=True)


# =========================================================================
# FRONTEND ROUTES
# =========================================================================

@app.route('/')
def index():
    """Serve the main frontend application."""
    return send_from_directory('frontend', 'index.html')


@app.route('/favicon.ico')
def favicon():
    """Serve favicon."""
    return send_from_directory('frontend', 'favicon.ico', mimetype='image/x-icon')


# =========================================================================
# API ENDPOINTS - VIOLATIONS & REPORTS
# =========================================================================

@app.route('/api/violations')
def api_violations():
    """Get all violations with details from Supabase."""
    if db_manager is None:
        # Fallback to local filesystem
        violations = []
        if VIOLATIONS_DIR.exists():
            for violation_dir in sorted(VIOLATIONS_DIR.iterdir(), reverse=True):
                if violation_dir.is_dir():
                    report_id = violation_dir.name
                    try:
                        timestamp = datetime.strptime(report_id, '%Y%m%d_%H%M%S')
                        
                        # Get violation metadata if exists
                        metadata_file = violation_dir / 'metadata.json'
                        metadata = {}
                        if metadata_file.exists():
                            with open(metadata_file, 'r') as f:
                                metadata = json.load(f)
                        
                        # Determine status from files present
                        has_report = (violation_dir / 'report.html').exists()
                        has_original = (violation_dir / 'original.jpg').exists()
                        has_annotated = (violation_dir / 'annotated.jpg').exists()
                        
                        # Infer status from what files exist
                        if has_report:
                            status = 'completed'
                        elif has_annotated:
                            status = 'generating'  # Has annotated but no report yet
                        elif has_original:
                            status = 'pending'  # Just original image saved
                        else:
                            status = 'pending'
                        
                        violations.append({
                            'report_id': report_id,
                            'timestamp': format_timestamp_myt(timestamp),
                            'has_original': has_original,
                            'has_annotated': has_annotated,
                            'has_report': has_report,
                            'status': status,
                            'status': status,
                            'severity': metadata.get('severity', 'HIGH'),
                            'violation_type': metadata.get('violation_type', 'PPE Violation'),
                            'location': metadata.get('location', 'Unknown'),
                            'violation_count': metadata.get('violation_count', 1),
                            'missing_ppe': metadata.get('detection_data', {}).get('missing_ppe', []),
                            'violation_summary': metadata.get('violation_summary', 'PPE Violation')
                        })
                        
                        # Enrich with missing ppe if available in metadata
                        if 'violation_summary' in metadata:
                             summary = metadata['violation_summary']
                             mp = []
                             if 'PPE Violation Detected:' in summary:
                                parts = summary.split('PPE Violation Detected:')[1].strip().split(',')
                                mp = [p.strip().replace('NO-', '').replace('No-', '') for p in parts]
                             elif 'Missing' in summary:
                                import re
                                mp = re.findall(r'Missing ([\w\s]+?)(?:,|\.|$)', summary)
                             
                             if mp:
                                violations[-1]['missing_ppe'] = mp
                                violations[-1]['violation_count'] = len(mp)
                                violations[-1]['ppe_tags'] = [f"NO-{p.strip().upper().replace(' ', '-')}" for p in mp]
                    except ValueError:
                        logger.warning(f"Skipping invalid report directory: {report_id}")
                        continue
        return jsonify(violations)
    
    # Use Supabase - get ALL violations including pending
    try:
        # Use the new method that includes pending detection events
        if hasattr(db_manager, 'get_all_violations_with_status'):
            violations = db_manager.get_all_violations_with_status(limit=100)
        else:
            violations = db_manager.get_recent_violations(limit=100)
        
        # Format violations for API response
        formatted_violations = []
        for v in violations:
            # Extract caption validation data if available
            detection_data = v.get('detection_data') or {}
            caption_validation = detection_data.get('caption_validation')
            
            # Determine status - use actual status if available, otherwise infer from data
            status = v.get('status', 'unknown')
            if status == 'unknown':
                if v.get('report_html_key') or v.get('violation_id'):
                    status = 'completed'
                else:
                    status = 'pending'
            
            # Extract missing PPE details from detection_data or violation_summary
            missing_ppe = []
            ppe_tags = []
            detection_data_parsed = v.get('detection_data')
            
            if detection_data_parsed:
                # Try to parse violation details from stored detection data
                if isinstance(detection_data_parsed, str):
                    try:
                        detection_data_parsed = json.loads(detection_data_parsed)
                    except:
                        detection_data_parsed = None
                
                if isinstance(detection_data_parsed, dict):
                    # Extract from violation_summary field in detection data
                    if 'violation_summary' in detection_data_parsed:
                        for item in detection_data_parsed['violation_summary']:
                            if 'Missing' in item:
                                ppe_item = item.replace('Missing ', '').strip()
                                missing_ppe.append(ppe_item)
                                ppe_tags.append(ppe_item.replace(' ', '-').upper())
            
            # Fallback: parse from violation_summary string
            if not missing_ppe and v.get('violation_summary'):
                summary = v.get('violation_summary', '')
                
                # Parse format: "PPE Violation Detected: NO-Hardhat, NO-Safety Vest"
                if 'PPE Violation Detected:' in summary:
                    # Extract everything after the colon
                    violations_part = summary.split('PPE Violation Detected:')[1].strip()
                    # Split by comma and clean up
                    violation_items = [item.strip() for item in violations_part.split(',')]
                    for item in violation_items:
                        # Handle "NO-Hardhat" and "No-Hardhat"
                        clean_item = item.replace('NO-', '').replace('No-', '')
                        if clean_item:
                           missing_ppe.append(clean_item)
                           ppe_tags.append(f"NO-{clean_item.upper()}")

                # Parse format: "Worker detected with PPE violations: NO-Hardhat"
                elif 'Worker detected with PPE violations:' in summary:
                    violations_part = summary.split('Worker detected with PPE violations:')[1].split('.')[0].strip()
                    violation_items = [item.strip() for item in violations_part.split(',')]
                    for item in violation_items:
                        clean_item = item.replace('NO-', '').replace('No-', '')
                        if clean_item:
                            missing_ppe.append(clean_item)
                            ppe_tags.append(f"NO-{clean_item.upper()}")
                
                # Also try parsing "Missing Hardhat" format
                elif 'Missing' in summary:
                    matches = re.findall(r'Missing ([\w\s]+?)(?:,|\.|$)', summary)
                    for m in matches:
                        clean_m = m.strip()
                        if clean_m:
                             missing_ppe.append(clean_m)
                             ppe_tags.append(f"NO-{clean_m.replace(' ', '-').upper()}")
            
            # Check for images/report - prefer Supabase keys, fallback to local files
            report_id = v['report_id']
            local_dir = VIOLATIONS_DIR / report_id
            has_original = bool(v.get('original_image_key')) or (local_dir / 'original.jpg').exists()
            has_annotated = bool(v.get('annotated_image_key')) or (local_dir / 'annotated.jpg').exists()
            has_report = bool(v.get('report_html_key')) or (local_dir / 'report.html').exists()
            
            formatted_violations.append({
                'report_id': report_id,
                'timestamp': format_timestamp_myt(v['timestamp']),
                'person_count': v.get('person_count', 0),
                'violation_count': v.get('violation_count') if v.get('violation_count') else len(missing_ppe) if missing_ppe else 1,
                'severity': v.get('severity', 'UNKNOWN'),
                'status': status,
                'device_id': v.get('device_id'),
                'error_message': v.get('error_message'),
                'violation_summary': v.get('violation_summary') or (f"Missing: {', '.join(missing_ppe)}" if missing_ppe else 'PPE Violation'),
                'missing_ppe': missing_ppe,
                'ppe_tags': ppe_tags,
                'violation_type': 'PPE Violation',
                'has_original': has_original,
                'has_annotated': has_annotated,
                'has_report': has_report,
                'report_html_key': v.get('report_html_key'),
                'nlp_analysis': v.get('nlp_analysis'),
                'detection_data': {
                    'caption_validation': caption_validation
                } if caption_validation else None
            })
        
        return jsonify(formatted_violations)
        
    except Exception as e:
        logger.error(f"Error fetching violations from Supabase: {e}")
        return jsonify({'error': 'Failed to fetch violations'}), 500


@app.route('/api/stats')
@app.route('/api/dashboard/stats')
def api_stats():
    """Get violation statistics from Supabase."""
    if db_manager is None:
        # Fallback to local filesystem
        violations = []
        if VIOLATIONS_DIR.exists():
            for violation_dir in VIOLATIONS_DIR.iterdir():
                if violation_dir.is_dir():
                    try:
                        timestamp = datetime.strptime(violation_dir.name, '%Y%m%d_%H%M%S')
                        violations.append(timestamp)
                    except ValueError:
                        continue
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_monday = now.weekday()
        week_start = today_start - timedelta(days=days_since_monday)
        
        stats = {
            'total': len(violations),
            'today': sum(1 for v in violations if v >= today_start),
            'thisWeek': sum(1 for v in violations if v >= week_start),
            'severity': {'high': 0, 'medium': len(violations), 'low': 0},
            'breakdown': {}  # Local fallback doesn't support breakdown easily
        }
        return jsonify(stats)
    
    # Use Supabase
    try:
        violations = db_manager.get_recent_violations(limit=2000)
        
        # Calculate Date Ranges
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_start
        
        # Week ranges (Monday start)
        days_since_monday = now.weekday()
        week_start = today_start - timedelta(days=days_since_monday)
        last_week_start = week_start - timedelta(days=7)
        last_week_end = week_start
        
        # Handle timezone info in violations if present
        if violations and violations[0].get('timestamp') and violations[0]['timestamp'].tzinfo:
            from datetime import timezone
            today_start = today_start.replace(tzinfo=timezone.utc)
            yesterday_start = yesterday_start.replace(tzinfo=timezone.utc)
            yesterday_end = yesterday_end.replace(tzinfo=timezone.utc)
            week_start = week_start.replace(tzinfo=timezone.utc)
            last_week_start = last_week_start.replace(tzinfo=timezone.utc)
            last_week_end = last_week_end.replace(tzinfo=timezone.utc)
            
        # 1. Calculate Summary Stats
        today_count = 0
        yesterday_count = 0
        week_count = 0
        last_week_count = 0
        
        # 2. Calculate Breakdown
        violation_counts = {
            'NO-Hardhat': 0,
            'NO-Safety Vest': 0,
            'NO-Gloves': 0,
            'NO-Mask': 0,
            'NO-Goggles': 0,
            'NO-Safety Shoes': 0,
            'Other': 0
        }
        
        for v in violations:
            ts = v.get('timestamp')
            if ts:
                if ts >= today_start:
                    today_count += 1
                if ts >= yesterday_start and ts < yesterday_end:
                    yesterday_count += 1
                if ts >= week_start:
                    week_count += 1
                if ts >= last_week_start and ts < last_week_end:
                    last_week_count += 1
            
            # Parse detection data for breakdown
            parsed_from_detection = False
            detection_data = v.get('detection_data')
            if detection_data:
                # Handle both List (direct) and Dict (wrapper) formats
                if isinstance(detection_data, dict):
                    detections = detection_data.get('detections', [])
                elif isinstance(detection_data, list):
                    detections = detection_data
                else:
                    detections = []
                    
                for d in detections:
                    class_name = d.get('class_name', '')
                    # Case-insensitive matching
                    matched = False
                    for key in violation_counts.keys():
                        key_lower = key.lower().replace('no-', '').replace('safety ', '')
                        class_lower = class_name.lower().replace('no-', '').replace('safety ', '')
                        
                        if key_lower in class_lower or class_lower in key_lower:
                            violation_counts[key] += 1
                            matched = True
                            parsed_from_detection = True
                            break
                    
                    if not matched and class_name.upper().startswith('NO-'):
                        # Map unknown NO- classes to Other or count specifically if needed
                        violation_counts['Other'] += 1
                        parsed_from_detection = True
            
            # Fallback: If detection parsing failed (or no data), try parsing violation_summary
            if not parsed_from_detection and v.get('violation_summary'):
                summary = v['violation_summary'].lower()
                
                # Robust keyword matching: Check if violation type name appears in summary
                # e.g. "hardhat" in "Missing hardhat"
                for key in violation_counts.keys():
                    # key is "NO-Hardhat", key_simple is "hardhat"
                    key_simple = key.lower().replace('no-', '').replace('safety ', '')
                    
                    # Avoid matching "mask" in "unmasked" if unrelated, but generally safe
                    # Specific checks for common phrases
                    if key_simple in summary:
                        violation_counts[key] += 1
                    elif 'no-' + key_simple in summary or 'missing ' + key_simple in summary:
                        violation_counts[key] += 1

        stats = {
            'total': len(violations),
            'today': today_count,
            'todayDelta': today_count - yesterday_count,
            'thisWeek': week_count,
            'weekDelta': week_count - last_week_count,
            'severity': {
                'high': sum(1 for v in violations if str(v.get('severity', '')).upper() == 'HIGH'),
                'medium': sum(1 for v in violations if str(v.get('severity', '')).upper() == 'MEDIUM'),
                'low': sum(1 for v in violations if str(v.get('severity', '')).upper() == 'LOW')
            },
            'breakdown': violation_counts
        }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error fetching stats from Supabase: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


@app.route('/api/analytics/trend')
def api_analytics_trend():
    """Get violation trends for the last 14 days."""
    try:
        # Get enough data for trends
        violations = db_manager.get_recent_violations(limit=2000) if db_manager else []
        
        # Initialize last 14 days with 0
        trend_data = {}
        now = datetime.now()
        for i in range(13, -1, -1):
            date_str = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            trend_data[date_str] = 0
            
        # Fill with actual data
        for v in violations:
            ts = v.get('timestamp')
            if ts:
                # Handle string dates if necessary
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    except:
                        continue
                
                date_key = ts.strftime('%Y-%m-%d')
                if date_key in trend_data:
                    trend_data[date_key] += 1
            elif isinstance(ts, str):
                # Fallback for string timestamps
                try:
                    # Clean up string first
                    clean_ts = ts.replace('Z', '').split('+')[0]
                    # Try ISO format without TZ
                    dt = datetime.fromisoformat(clean_ts)
                    date_key = dt.strftime('%Y-%m-%d')
                    if date_key in trend_data:
                        trend_data[date_key] += 1
                except:
                    # Try basic format YYYYMMDD_HHMMSS
                    try:
                        dt = datetime.strptime(ts.split('_')[0], '%Y%m%d')
                        date_key = dt.strftime('%Y-%m-%d')
                        if date_key in trend_data:
                            trend_data[date_key] += 1
                    except:
                        continue
        
        # Convert to sorted list
        # result = [{'date': '2025-01-25', 'count': 5}, ...] 
        result = [
            {'date': date, 'count': count}
            for date, count in sorted(trend_data.items())
        ]
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error fetching trends: {e}")
        return jsonify({'error': 'Failed to fetch trends'}), 500


# =========================================================================
# API ENDPOINTS - STATUS & MONITORING (from Pipeline_Luna)
# =========================================================================

@app.route('/api/violation/<report_id>')
def api_get_violation(report_id):
    """Get a specific violation with full details and status."""
    if db_manager is None:
        # Fallback to local filesystem
        violation_dir = VIOLATIONS_DIR / report_id
        if not violation_dir.exists():
            return jsonify({'error': 'Violation not found'}), 404
        
        metadata_file = violation_dir / 'metadata.json'
        metadata = {}
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
        
        try:
            timestamp = datetime.strptime(report_id, '%Y%m%d_%H%M%S')
        except ValueError:
            timestamp = datetime.now()
        
        return jsonify({
            'report_id': report_id,
            'timestamp': timestamp.isoformat(),
            'has_original': (violation_dir / 'original.jpg').exists(),
            'has_annotated': (violation_dir / 'annotated.jpg').exists(),
            'has_report': (violation_dir / 'report.html').exists(),
            'status': 'completed' if (violation_dir / 'report.html').exists() else 'pending',
            **metadata
        })
    
    # Use Supabase
    try:
        violation = db_manager.get_violation(report_id)
        if not violation:
            return jsonify({'error': 'Violation not found'}), 404
        
        return jsonify({
            'report_id': violation['report_id'],
            'timestamp': format_timestamp_myt(violation['timestamp']),
            'person_count': violation.get('person_count', 0),
            'violation_count': violation.get('violation_count', 0),
            'severity': violation.get('severity', 'UNKNOWN'),
            'status': violation.get('status', 'unknown'),
            'device_id': violation.get('device_id'),
            'error_message': violation.get('error_message'),
            'violation_summary': violation.get('violation_summary'),
            'caption': violation.get('caption'),
            'has_original': bool(violation.get('original_image_key')),
            'has_annotated': bool(violation.get('annotated_image_key')),
            'has_report': bool(violation.get('report_html_key'))
        })
        
    except Exception as e:
        logger.error(f"Error fetching violation: {e}")
        return jsonify({'error': 'Failed to fetch violation'}), 500


@app.route('/api/report/<report_id>/status')
def api_report_status(report_id):
    """Get the status of a specific report (for fallback modal)."""
    if db_manager is None:
        # Fallback to local filesystem
        violation_dir = VIOLATIONS_DIR / report_id
        if not violation_dir.exists():
            return jsonify({
                'status': 'not_found',
                'message': 'Report not found'
            })
        
        has_report = (violation_dir / 'report.html').exists()
        return jsonify({
            'status': 'completed' if has_report else 'generating',
            'has_report': has_report,
            'has_original': (violation_dir / 'original.jpg').exists(),
            'has_annotated': (violation_dir / 'annotated.jpg').exists(),
            'message': 'Report is ready' if has_report else 'Report is being generated...'
        })
    
    # Use Supabase
    try:
        status_info = db_manager.get_status(report_id)
        if not status_info:
            return jsonify({
                'status': 'not_found',
                'message': 'Report not found'
            })
        
        status = status_info.get('status', 'unknown')
        messages = {
            'pending': 'Report is queued for processing',
            'generating': 'AI is analyzing the violation and generating the report',
            'completed': 'Report is ready to view',
            'failed': f"Report generation failed: {status_info.get('error_message', 'Unknown error')}",
            'partial': 'Report was partially generated',
            'skipped': f"Skipped - not a work environment: {status_info.get('error_message', 'Invalid scene')}"
        }
        
        return jsonify({
            'status': status,
            'has_report': status_info.get('has_report', False),
            'has_original': status_info.get('has_original', False),
            'has_annotated': status_info.get('has_annotated', False),
            'device_id': status_info.get('device_id'),
            'error_message': status_info.get('error_message'),
            'message': messages.get(status, 'Status unknown')
        })
        
    except Exception as e:
        logger.error(f"Error fetching report status: {e}")
        return jsonify({'error': 'Failed to fetch status'}), 500


@app.route('/api/queue/status')
def api_queue_status():
    """Get the current status of the violation processing queue."""
    if violation_queue is None:
        return jsonify({
            'available': False,
            'message': 'Violation queue not initialized'
        })
    
    try:
        stats = violation_queue.get_stats()
        return jsonify({
            'available': True,
            'queue_size': stats.get('current_size', 0),
            'capacity': stats.get('capacity', 100),
            'total_enqueued': stats.get('total_enqueued', 0),
            'total_processed': stats.get('total_processed', 0),
            'total_failed': stats.get('total_failed', 0),
            'total_rate_limited': stats.get('total_rate_limited', 0),
            'worker_running': queue_worker_running,
            'environment_validation_enabled': ENVIRONMENT_VALIDATION_ENABLED,
            'by_priority': stats.get('by_priority', {}),
            'by_device': stats.get('by_device', {})
        })
    except Exception as e:
        logger.error(f"Error getting queue status: {e}")
        return jsonify({'error': 'Failed to get queue status'}), 500


@app.route('/api/settings/environment-validation', methods=['GET', 'POST'])
def api_environment_validation():
    """Get or set environment validation setting."""
    global ENVIRONMENT_VALIDATION_ENABLED
    
    if request.method == 'GET':
        return jsonify({
            'enabled': ENVIRONMENT_VALIDATION_ENABLED,
            'valid_keywords': VALID_ENVIRONMENT_KEYWORDS[:10],  # First 10 for display
            'invalid_keywords': INVALID_ENVIRONMENT_KEYWORDS[:10]
        })
    
    # POST - update setting
    try:
        data = request.get_json()
        if 'enabled' in data:
            ENVIRONMENT_VALIDATION_ENABLED = bool(data['enabled'])
            logger.info(f"Environment validation {'enabled' if ENVIRONMENT_VALIDATION_ENABLED else 'disabled'}")
            return jsonify({
                'success': True,
                'enabled': ENVIRONMENT_VALIDATION_ENABLED,
                'message': f"Environment validation {'enabled' if ENVIRONMENT_VALIDATION_ENABLED else 'disabled'}"
            })
        else:
            return jsonify({'error': 'Missing "enabled" field'}), 400
    except Exception as e:
        logger.error(f"Error updating environment validation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/cooldown', methods=['GET', 'POST'])
def api_cooldown_setting():
    """Get or set the violation capture cooldown."""
    global VIOLATION_COOLDOWN
    
    if request.method == 'GET':
        return jsonify({
            'cooldown_seconds': VIOLATION_COOLDOWN,
            'description': 'Minimum seconds between capturing violations'
        })
    
    # POST - update cooldown
    try:
        data = request.get_json()
        if 'cooldown_seconds' in data:
            new_cooldown = int(data['cooldown_seconds'])
            if new_cooldown < 1:
                return jsonify({'error': 'Cooldown must be at least 1 second'}), 400
            if new_cooldown > 300:
                return jsonify({'error': 'Cooldown cannot exceed 300 seconds'}), 400
            VIOLATION_COOLDOWN = new_cooldown
            logger.info(f"Violation cooldown set to {VIOLATION_COOLDOWN} seconds")
            return jsonify({
                'success': True,
                'cooldown_seconds': VIOLATION_COOLDOWN,
                'message': f"Cooldown set to {VIOLATION_COOLDOWN} seconds"
            })
        else:
            return jsonify({'error': 'Missing "cooldown_seconds" field'}), 400
    except Exception as e:
        logger.error(f"Error updating cooldown: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/fix-stuck-reports', methods=['POST'])
def api_fix_stuck_reports():
    """Manually trigger fixing of stuck reports."""
    if db_manager is None:
        return jsonify({'error': 'Database not available'}), 503
    
    try:
        if hasattr(db_manager, 'fix_stuck_reports'):
            fixed_count = db_manager.fix_stuck_reports()
            return jsonify({
                'success': True,
                'fixed_count': fixed_count,
                'message': f'Fixed {fixed_count} stuck reports'
            })
        else:
            return jsonify({'error': 'Fix method not available'}), 500
    except Exception as e:
        logger.error(f"Error fixing stuck reports: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/pending')
def api_pending_reports():
    """Get all reports that are still pending or generating."""
    if db_manager is None:
        # Fallback to local filesystem
        pending = []
        if VIOLATIONS_DIR.exists():
            for violation_dir in sorted(VIOLATIONS_DIR.iterdir(), reverse=True):
                if violation_dir.is_dir():
                    if not (violation_dir / 'report.html').exists():
                        try:
                            timestamp = datetime.strptime(violation_dir.name, '%Y%m%d_%H%M%S')
                            pending.append({
                                'report_id': violation_dir.name,
                                'timestamp': timestamp.isoformat(),
                                'status': 'generating'
                            })
                        except ValueError:
                            continue
        return jsonify(pending[:10])
    
    # Use Supabase
    try:
        pending = db_manager.get_pending_reports(limit=10)
        formatted = [{
            'report_id': p['report_id'],
            'timestamp': format_timestamp_myt(p['timestamp']),
            'status': p.get('status', 'pending'),
            'device_id': p.get('device_id'),
            'severity': p.get('severity')
        } for p in pending]
        return jsonify(formatted)
        
    except Exception as e:
        logger.error(f"Error fetching pending reports: {e}")
        return jsonify({'error': 'Failed to fetch pending reports'}), 500


@app.route('/api/logs')
def api_logs():
    """Get recent system event logs."""
    limit = request.args.get('limit', 50, type=int)
    event_type = request.args.get('event_type', None)
    
    if db_manager is None:
        return jsonify([])  # No logs without Supabase
    
    try:
        logs = db_manager.get_recent_logs(limit=limit, event_type=event_type)
        formatted = [{
            'id': log.get('id'),
            'event_type': log.get('event_type'),
            'report_id': log.get('report_id'),
            'device_id': log.get('device_id'),
            'message': log.get('message'),
            'metadata': log.get('metadata'),
            'created_at': format_timestamp_myt(log['created_at'])
        } for log in logs]
        return jsonify(formatted)
        
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return jsonify({'error': 'Failed to fetch logs'}), 500


@app.route('/api/device/<device_id>/stats')
def api_device_stats(device_id):
    """Get statistics for a specific device."""
    if db_manager is None:
        return jsonify({'error': 'Supabase not configured'}), 503
    
    try:
        stats = db_manager.get_device_stats(device_id)
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error fetching device stats: {e}")
        return jsonify({'error': 'Failed to fetch device stats'}), 500


@app.route('/report/<report_id>')
def view_report(report_id):
    """View a specific violation report from Supabase or local storage."""
    # Check local filesystem FIRST (Edge priority) specifically for HTML reports
    # This ensures re-generated reports are seen immediately without cloud sync delay
    violation_dir = VIOLATIONS_DIR / report_id
    report_html = violation_dir / 'report.html'
    
    if report_html.exists():
        return send_from_directory(str(violation_dir), 'report.html')

    if storage_manager is None or db_manager is None:
        if not violation_dir.exists():
             abort(404, description="Report not found")
        else:
             abort(404, description="Report HTML not found")
    
    # Use Supabase
    try:
        # Get violation data from database
        violation = db_manager.get_violation(report_id)
        
        if not violation:
            abort(404, description="Report not found")
        
        # Get signed URL for report HTML
        report_html_key = violation.get('report_html_key')
        if not report_html_key:
            abort(404, description="Report HTML not found")
        
        # Download the HTML content and render it
        try:
            html_content = storage_manager.download_file_content(report_html_key)
            if not html_content:
                abort(404, description="Failed to download report HTML")
            
            # Return the HTML content directly so browser renders it
            return html_content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        except Exception as e:
            logger.error(f"Error downloading report HTML: {e}")
            abort(500, description=f"Error loading report: {str(e)}")
        
    except Exception as e:
        logger.error(f"Error fetching report from Supabase: {e}")
        abort(500, description="Failed to fetch report")


@app.route('/image/<report_id>/<filename>')
def get_image(report_id, filename):
    """Serve violation images from local storage first, then Supabase."""
    
    # Validate filename first
    if filename not in ['original.jpg', 'annotated.jpg']:
        abort(400, description="Invalid filename")
    
    # Check local filesystem FIRST (priority - same as view_report)
    # This ensures locally generated images are served immediately without cloud sync delay
    violation_dir = VIOLATIONS_DIR / report_id
    image_path = violation_dir / filename
    
    if image_path.exists():
        return send_from_directory(str(violation_dir), filename)
    
    # Fallback to Supabase if local not found
    if storage_manager is None or db_manager is None:
        abort(404, description="Image not found")
    
    # Use Supabase
    try:
        # Get violation data from database
        violation = db_manager.get_violation(report_id)
        
        if not violation:
            abort(404, description="Report not found")
        
        # Get storage key based on filename
        if filename == 'original.jpg':
            storage_key = violation.get('original_image_key')
        else:
            storage_key = violation.get('annotated_image_key')
        
        if not storage_key:
            abort(404, description="Image not found")
        
        # Get signed URL
        signed_url = storage_manager.get_signed_url(storage_key)
        
        if not signed_url:
            abort(404, description="Failed to generate signed URL")
        
        # Redirect to signed URL
        return redirect(signed_url)
        
    except Exception as e:
        logger.error(f"Error fetching image from Supabase: {e}")
        abort(500, description="Failed to fetch image")


# =========================================================================
# API ENDPOINTS - LIVE STREAMING
# =========================================================================

def generate_frames(conf=0.25, include_depth=False):
    """Generate frames from RealSense camera (or webcam fallback) with YOLO detection and violation processing."""
    global active_camera
    
    with camera_lock:
        if active_camera is None:
            # Try RealSense first, fallback to webcam
            if REALSENSE_AVAILABLE:
                logger.info("Attempting to open RealSense camera...")
                active_camera = RealSenseCamera(width=640, height=480, fps=30, enable_depth=True)
                if not active_camera.open():
                    logger.warning("RealSense failed, falling back to webcam")
                    active_camera = None
            
            if active_camera is None:
                # Fallback to webcam with DirectShow
                logger.info("Opening standard webcam...")
                active_camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not active_camera.isOpened():
                    logger.error("Failed to open any camera")
                    return
                active_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                active_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                active_camera.set(cv2.CAP_PROP_FPS, 30)
        
        cam = active_camera
    
    # Check camera type
    is_realsense = isinstance(cam, RealSenseCamera) if REALSENSE_AVAILABLE else False
    camera_type = "RealSense D435i" if is_realsense else "Webcam"
    
    logger.info(f"Starting live frame generation with {camera_type}...")
    logger.info("=" * 80)
    logger.info("INITIALIZING PIPELINE COMPONENTS")
    logger.info(f"FULL_PIPELINE_AVAILABLE: {FULL_PIPELINE_AVAILABLE}")
    logger.info(f"Camera Type: {camera_type}")
    logger.info(f"Include Depth: {include_depth}")
    logger.info("=" * 80)
    
    # Initialize pipeline components if available
    if FULL_PIPELINE_AVAILABLE:
        init_success = initialize_pipeline_components()
        logger.info(f"Pipeline initialization result: {init_success}")
        logger.info(f"Caption generator: {caption_generator}")
        logger.info(f"Report generator: {report_generator}")
    else:
        logger.error("FULL_PIPELINE_AVAILABLE is False - components will not initialize")
    
    logger.info("=" * 80)
    
    try:
        while True:
            with camera_lock:
                if cam is None or not cam.isOpened():
                    break
                
                # Read frame based on camera type
                if is_realsense:
                    ret, color_frame, depth_raw, depth_colormap = cam.read()
                    frame = color_frame
                else:
                    ret, frame = cam.read()
                    depth_colormap = None
                    
                if not ret or frame is None:
                    logger.warning("Failed to read frame")
                    break
            
            # Run YOLO detection on color frame
            try:
                detections, annotated = predict_image(frame, conf=conf)
                
                # Log all detections for debugging
                if detections:
                    detected_classes = [d['class_name'] for d in detections]
                    logger.debug(f"Detected: {detected_classes}")
                
                # Check for violations in background thread (non-blocking)
                if detections and FULL_PIPELINE_AVAILABLE:
                    # Check for ANY PPE violations (match actual model class names)
                    violation_keywords = ['no-hardhat', 'no-gloves', 'no-safety vest',
                                         'no-mask', 'no-goggles']
                    
                    has_violation = any(
                        any(keyword in d['class_name'].lower() for keyword in violation_keywords)
                        for d in detections
                    )
                    
                    if has_violation:
                        # Log detected violations
                        violation_classes = [d['class_name'] for d in detections 
                                           if any(keyword in d['class_name'].lower() 
                                                 for keyword in violation_keywords)]
                        logger.info("=" * 80)
                        logger.info(f"🚨 PPE VIOLATION DETECTED: {violation_classes}")
                        logger.info(f"Caption generator available: {caption_generator is not None}")
                        logger.info(f"Report generator available: {report_generator is not None}")
                        logger.info(f"Violation queue available: {violation_queue is not None}")
                        logger.info("=" * 80)
                        
                        # Use queue-based approach to prevent missing violations
                        # enqueue_violation is fast (saves images, adds to queue)
                        # Queue worker processes reports in background
                        frame_copy = frame.copy()
                        detections_copy = detections.copy()
                        
                        report_id = enqueue_violation(frame_copy, detections_copy)
                        if report_id:
                            logger.info(f"✓ Violation {report_id} queued for processing")
                        else:
                            logger.debug("Violation not queued (cooldown or already processing)")
                
                # Create output frame - combine with depth if requested
                if include_depth and depth_colormap is not None and REALSENSE_AVAILABLE:
                    output_frame = create_combined_view(frame, depth_colormap, annotated)
                else:
                    output_frame = annotated
                
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ret:
                    continue
                
                frame_bytes = buffer.tobytes()
                
                # Yield frame in multipart format
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
            except Exception as e:
                logger.error(f"Error processing frame: {e}")
                continue
                
    except GeneratorExit:
        logger.info("Client disconnected from stream")
    except Exception as e:
        logger.error(f"Stream error: {e}")
    finally:
        logger.info("Frame generation stopped")


@app.route('/api/live/stream')
def live_stream():
    """Live camera stream with YOLO detection. Supports RealSense D435i with depth visualization."""
    conf = float(request.args.get('conf', 0.10))
    include_depth = request.args.get('depth', 'false').lower() == 'true'
    return Response(
        generate_frames(conf=conf, include_depth=include_depth),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/live/realsense-check')
def realsense_check():
    """Debug endpoint to check RealSense availability."""
    import sys
    result = {
        'realsense_available': REALSENSE_AVAILABLE,
        'python_executable': sys.executable,
        'python_version': sys.version,
    }
    
    # Try to import pyrealsense2 directly
    try:
        import pyrealsense2 as rs
        result['pyrealsense2_version'] = rs.__version__ if hasattr(rs, '__version__') else 'unknown'
        result['pyrealsense2_import'] = True
        
        # Try to detect devices
        ctx = rs.context()
        devices = ctx.query_devices()
        result['devices_found'] = len(devices)
        if len(devices) > 0:
            result['device_name'] = devices[0].get_info(rs.camera_info.name)
    except ImportError as e:
        result['pyrealsense2_import'] = False
        result['pyrealsense2_error'] = str(e)
    except Exception as e:
        result['pyrealsense2_error'] = str(e)
    
    return jsonify(result)


@app.route('/api/live/camera-info')
def camera_info():
    """Get information about the active camera."""
    global active_camera
    
    with camera_lock:
        if active_camera is None:
            return jsonify({
                'active': False,
                'type': None,
                'info': None
            })
        
        if REALSENSE_AVAILABLE and isinstance(active_camera, RealSenseCamera):
            info = active_camera.get_camera_info()
            return jsonify({
                'active': True,
                'type': 'realsense',
                'info': info
            })
        else:
            return jsonify({
                'active': True,
                'type': 'webcam',
                'info': {
                    'type': 'Webcam',
                    'name': 'Standard Webcam (DirectShow)',
                    'depth_enabled': False
                }
            })


@app.route('/api/live/start', methods=['POST'])
def start_live():
    """Start live monitoring with RealSense D435i (primary) or webcam (fallback)."""
    global active_camera
    
    with camera_lock:
        if active_camera is None:
            # Try RealSense first
            if REALSENSE_AVAILABLE:
                logger.info("Attempting to open RealSense camera...")
                active_camera = RealSenseCamera(width=640, height=480, fps=30, enable_depth=True)
                if not active_camera.open():
                    logger.warning("RealSense failed, falling back to webcam")
                    active_camera = None
            
            # Fallback to webcam
            if active_camera is None:
                logger.info("Opening standard webcam...")
                active_camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not active_camera.isOpened():
                    return jsonify({'success': False, 'error': 'Failed to open any camera'}), 500
                active_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                active_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                active_camera.set(cv2.CAP_PROP_FPS, 30)
    
    # Get camera type for response
    if REALSENSE_AVAILABLE and isinstance(active_camera, RealSenseCamera):
        camera_type = "RealSense D435i"
        depth_enabled = True
    else:
        camera_type = "Webcam"
        depth_enabled = False
    
    return jsonify({
        'success': True, 
        'message': 'Live monitoring started',
        'camera_type': camera_type,
        'depth_enabled': depth_enabled
    })


@app.route('/api/live/stop', methods=['POST'])
def stop_live():
    """Stop live monitoring."""
    global active_camera
    
    with camera_lock:
        if active_camera is not None:
            active_camera.release()
            active_camera = None
    
    return jsonify({'success': True, 'message': 'Live monitoring stopped'})


@app.route('/api/live/status')
def live_status():
    """Get live monitoring status with camera information."""
    with camera_lock:
        is_active = active_camera is not None and active_camera.isOpened()
        
        if is_active:
            if REALSENSE_AVAILABLE and isinstance(active_camera, RealSenseCamera):
                camera_type = "RealSense D435i"
                depth_enabled = True
                camera_info_data = active_camera.get_camera_info()
            else:
                camera_type = "Webcam"
                depth_enabled = False
                camera_info_data = {'type': 'Webcam', 'name': 'Standard Webcam'}
        else:
            camera_type = None
            depth_enabled = False
            camera_info_data = None
    
    return jsonify({
        'active': is_active,
        'camera_type': camera_type,
        'depth_enabled': depth_enabled,
        'camera_info': camera_info_data,
        'realsense_available': REALSENSE_AVAILABLE
    })


# =========================================================================
# API ENDPOINTS - IMAGE INFERENCE
# =========================================================================

@app.route('/api/inference/upload', methods=['POST'])
def upload_inference():
    """Run inference on uploaded image and generate report if violations detected."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No image selected'}), 400
    
    try:
        # Read image
        img_bytes = file.read()
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return jsonify({'error': 'Invalid image format'}), 400
        
        # Get confidence threshold
        conf = float(request.form.get('conf', 0.10))
        
        # Run inference
        detections, annotated = predict_image(frame, conf=conf)
        
        # Check for violations
        violation_keywords = ['no-hardhat', 'no-gloves', 'no-safety vest',
                             'no-mask', 'no-goggles']
        
        violation_detections = [d for d in detections 
                               if any(keyword in d['class_name'].lower() 
                                     for keyword in violation_keywords)]
        
        # If violations detected, use queue system (consistent with live camera)
        if violation_detections and FULL_PIPELINE_AVAILABLE:
            violation_types = [d['class_name'] for d in violation_detections]
            logger.info(f"🚨 Uploaded image violation detected: {violation_types}")
            
            # Use queue system for processing (same as live camera)
            frame_copy = frame.copy()
            detections_copy = detections.copy()
            # FORCE capture for manual uploads to bypass smart detection checks
            # PASS THE ANNOTATED IMAGE to ensure consistency with what user sees
            report_id = enqueue_violation(frame_copy, detections_copy, force=True, annotated_frame=annotated)
            logger.info(f"📥 Violation queued for processing: {report_id}")
        
        # Encode annotated image to base64
        _, buffer = cv2.imencode('.jpg', annotated)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'success': True,
            'detections': detections,
            'annotated_image': f'data:image/jpeg;base64,{img_base64}',
            'count': len(detections),
            'violations_detected': len(violation_detections) > 0,
            'violation_count': len(violation_detections)
        })
        
    except Exception as e:
        logger.error(f"Inference error: {e}")
        return jsonify({'error': str(e)}), 500


# =========================================================================
# SYSTEM INFO ENDPOINTS
# =========================================================================

@app.route('/api/system/info')
def system_info():
    """Get system information."""
    import torch
    
    info = {
        'python_version': sys.version,
        'cuda_available': torch.cuda.is_available(),
        'gpu_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        'violations_count': len(list(VIOLATIONS_DIR.iterdir())) if VIOLATIONS_DIR.exists() else 0,
        'model_path': 'Results/ppe_yolov86/weights/best.pt'
    }
    
    return jsonify(info)


# =========================================================================
# ERROR HANDLERS
# =========================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory('frontend', 'index.html')


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    logger.error(f"Server error: {e}")
    return jsonify({'error': 'Internal server error'}), 500


# =========================================================================
# CLEANUP
# =========================================================================

def cleanup():
    """Cleanup resources on shutdown."""
    global active_camera
    
    with camera_lock:
        if active_camera is not None:
            active_camera.release()
            active_camera = None
    
    cv2.destroyAllWindows()


# =========================================================================
# MAIN
# =========================================================================

if __name__ == '__main__':
    import atexit
    atexit.register(cleanup)
    
    logger.info("=" * 80)
    logger.info("LUNA PPE SAFETY MONITOR - Unified Application Server")
    logger.info("=" * 80)
    logger.info("")
    logger.info("🚀 Server starting at: http://localhost:5000")
    logger.info("")
    logger.info("📊 Features:")
    logger.info("   - Modern web interface")
    logger.info("   - Live webcam monitoring with YOLO")
    logger.info("   - Image upload inference")
    logger.info("   - Violation reports and analytics")
    logger.info("")
    logger.info("🔗 Endpoints:")
    logger.info("   GET  /                          - Main frontend")
    logger.info("   GET  /api/violations            - List violations")
    logger.info("   GET  /api/stats                 - Statistics")
    logger.info("   GET  /api/live/stream           - Live video stream")
    logger.info("   POST /api/live/start            - Start monitoring")
    logger.info("   POST /api/live/stop             - Stop monitoring")
    logger.info("   POST /api/inference/upload      - Upload inference")
    logger.info("   POST /api/inference/upload      - Upload inference")
    logger.info("")
    
    # Auto-open browser (prevents need for manual clicking which can cause double-opens)
    # Auto-open browser (only in main process)
    def open_browser():
        import webbrowser
        import time
        # Check if we are in the main reloader process or if reloader is disabled
        # When use_reloader=False, WERKZEUG_RUN_MAIN is not set (None)
        # When use_reloader=True, Main process is None, Child is 'true'
        # We want to open ONLY in the Main process (None) to avoid opening on every reload
        # AND to avoid opening twice (once in Main, once in Child)
        
        is_main_process = not os.environ.get('WERKZEUG_RUN_MAIN')
        
        if is_main_process:
            time.sleep(1.5)  # Wait for server to start
            logger.info("🌐 Opening web browser...")
            webbrowser.open('http://localhost:5000')

    # Start browser thread
    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 80)
    
    # Debug mode should ONLY be enabled for local development, NEVER in production
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    if debug_mode:
        logger.warning("⚠️  Flask debug mode is ENABLED - This should ONLY be used for local development!")
        logger.warning("⚠️  NEVER enable debug mode in production as it allows arbitrary code execution!")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=debug_mode,
        threaded=True,
        use_reloader=False  # Prevent double initialization
    )
