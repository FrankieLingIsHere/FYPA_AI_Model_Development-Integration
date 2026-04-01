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
import shutil
import html
from pathlib import Path
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from typing import List, Dict, Any
import json
import time

# Import timezone utility (configurable via .env)
from timezone_utils import get_local_time, to_local_time, get_timezone_info

from flask import Flask, render_template, send_from_directory, jsonify, abort, Response, request, redirect
from werkzeug.exceptions import HTTPException
import cv2
import numpy as np
from PIL import Image
import io
import base64

# Load environment variables
from dotenv import load_dotenv
load_dotenv(override=True)

# Import project modules
from infer_image import predict_image, resolve_model_path
from pipeline.backend.core.live_source_adapter import LiveSourceAdapter

# Global progress tracking for report generation
report_progress = {
    'current': None,
    'total': 0,
    'completed': 0,
    'status': 'idle',  # idle, processing, completed, error
    'current_step': '',
    'error_message': None
}
report_progress_lock = Lock()

# Global startup/readiness tracking for frontend loading gate
startup_state_lock = Lock()
startup_thread = None
startup_state = {
    'status': 'idle',  # idle, running, ready, error
    'ready': False,
    'progress': 0,
    'current_step': 'Waiting to initialize',
    'error_message': None,
    'started_at': None,
    'updated_at': None,
    'checks': {
        'pipeline_imports': {'label': 'Pipeline modules', 'status': 'pending', 'detail': None},
        'yolo_model': {'label': 'YOLO model warm-up', 'status': 'pending', 'detail': None},
        'pipeline_components': {'label': 'Pipeline components', 'status': 'pending', 'detail': None},
        'supabase_database': {'label': 'Supabase database', 'status': 'pending', 'detail': None},
        'supabase_storage': {'label': 'Supabase storage', 'status': 'pending', 'detail': None},
        'queue_worker': {'label': 'Queue worker', 'status': 'pending', 'detail': None}
    }
}

# Import pipeline components for violation handling
try:
    from pipeline.backend.core.violation_detector import ViolationDetector
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
    from pipeline.backend.core.violation_queue import ViolationQueueManager, QueuedViolation
    from pipeline.config import VIOLATION_RULES, LLAVA_CONFIG, OLLAMA_CONFIG, GEMINI_CONFIG, MODEL_API_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, VIOLATIONS_DIR, REPORTS_DIR, SUPABASE_CONFIG
    FULL_PIPELINE_AVAILABLE = True
except ImportError as e:
    FULL_PIPELINE_AVAILABLE = False
    VIOLATION_RULES = {}
    LLAVA_CONFIG = {}
    OLLAMA_CONFIG = {}
    GEMINI_CONFIG = {'enabled': False, 'model': 'gemini-2.5-flash'}
    MODEL_API_CONFIG = {'enabled': False, 'nlp_provider_order': ['model_api', 'gemini', 'ollama', 'local'], 'embedding_provider_order': ['model_api', 'ollama']}
    RAG_CONFIG = {}
    REPORT_CONFIG = {}
    BRAND_COLORS = {}
    REPORTS_DIR = Path('pipeline/reports')
    SUPABASE_CONFIG = {}
    logging.warning(f"Full pipeline components not available - violations will be detected but reports won't be generated: {e}")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================================================================
# APPLICATION SETUP
# =========================================================================

app = Flask(__name__, 
            template_folder='frontend',
            static_folder='frontend',
            static_url_path='/static')

SERVE_FRONTEND = os.getenv('SERVE_FRONTEND', 'true').lower() == 'true'
ALLOWED_ORIGINS = [
    origin.strip() for origin in os.getenv('ALLOWED_ORIGINS', '*').split(',') if origin.strip()
]
ALLOWED_ORIGINS = [o.strip().strip('"').strip("'") for o in ALLOWED_ORIGINS if o.strip().strip('"').strip("'")]

STARTUP_MODEL_WARMUP_ENABLED = os.getenv(
    'STARTUP_MODEL_WARMUP_ENABLED',
    'true' if SERVE_FRONTEND else 'false'
).lower() == 'true'
STARTUP_MODEL_WARMUP_TIMEOUT_SECONDS = int(os.getenv('STARTUP_MODEL_WARMUP_TIMEOUT_SECONDS', '120'))


def _is_origin_allowed(origin: str) -> bool:
    """Check whether an Origin is allowed for CORS."""
    if not origin:
        return False
    if '*' in ALLOWED_ORIGINS:
        return True
    for allowed in ALLOWED_ORIGINS:
        # Allow wildcard subdomains, e.g. https://*.vercel.app
        if allowed.startswith('https://*.'):
            suffix = allowed[len('https://*'):]
            if origin.startswith('https://') and origin.endswith(suffix):
                return True
        if allowed.startswith('http://*.'):
            suffix = allowed[len('http://*'):]
            if origin.startswith('http://') and origin.endswith(suffix):
                return True
    return origin in ALLOWED_ORIGINS


def _apply_cors_headers(response):
    """Attach CORS headers to API/report/image responses for split frontend/backend deployments."""
    origin = request.headers.get('Origin')
    path = request.path or ''
    should_apply = path.startswith('/api/') or path.startswith('/report/') or path.startswith('/image/')

    if not should_apply:
        return response

    allow_origin = None
    if '*' in ALLOWED_ORIGINS:
        allow_origin = origin or '*'
    elif _is_origin_allowed(origin):
        allow_origin = origin

    if allow_origin:
        response.headers['Access-Control-Allow-Origin'] = allow_origin

    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-Requested-With'
    response.headers['Vary'] = 'Origin'
    return response


def _run_with_timeout(task_fn, timeout_seconds: int, task_name: str):
    """Run a blocking startup task with timeout and bubble up errors."""
    result = {'value': None, 'error': None}

    def _worker():
        try:
            result['value'] = task_fn()
        except Exception as e:
            result['error'] = e

    worker = Thread(target=_worker, daemon=True, name=f'startup-{task_name}')
    worker.start()
    worker.join(max(1, int(timeout_seconds)))

    if worker.is_alive():
        raise TimeoutError(f"{task_name} timed out after {timeout_seconds}s")
    if result['error'] is not None:
        raise result['error']
    return result['value']


@app.before_request
def _handle_preflight():
    """Respond to browser preflight requests before route handlers run."""
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        return _apply_cors_headers(response)
    return None


@app.after_request
def _add_cors_headers(response):
    """Apply CORS headers to outgoing responses."""
    return _apply_cors_headers(response)


@app.before_request
def _ensure_startup_sequence_running():
    """Kick off startup checks on first meaningful request."""
    path = request.path or ''
    if path.startswith('/static/') or path == '/favicon.ico':
        return None
    ensure_startup_thread()
    return None

# Directories
VIOLATIONS_DIR = Path('pipeline/violations')
VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)

# Thread-safe camera access
live_source_adapter = LiveSourceAdapter()
camera_lock = live_source_adapter.lock


def _is_active_live_source_locked() -> bool:
    """Return whether currently selected live source is active (lock must be held)."""
    return live_source_adapter.is_active_locked()


def _stop_live_source_locked() -> None:
    """Stop whichever live source is active (lock must be held)."""
    live_source_adapter.stop_locked()


def _get_realsense_probe_source():
    """Compatibility wrapper retained for existing call sites."""
    return None


def _get_realsense_snapshot() -> Dict[str, Any]:
    """Collect RealSense availability/capabilities in a uniform format."""
    return live_source_adapter.get_realsense_snapshot()


def _get_default_live_source() -> str:
    """Pick default source based on currently available hardware."""
    return live_source_adapter.get_default_source()


def _start_live_source_locked(requested_source: str) -> Dict[str, Any]:
    """Start requested source with graceful fallback behavior (lock must be held)."""
    return live_source_adapter.start_locked(requested_source)


def _read_active_frame_locked():
    """Read one frame from current source (lock must be held)."""
    return live_source_adapter.read_frame_locked()


def _build_live_state_payload() -> Dict[str, Any]:
    """Build live state payload consumed by frontend controls."""
    return live_source_adapter.build_state_payload()


def _normalize_label(value: str) -> str:
    """Normalize class labels for robust keyword matching across naming styles."""
    if not value:
        return ''
    normalized = str(value).strip().lower().replace('_', '-').replace(' ', '-')
    normalized = re.sub(r'-+', '-', normalized)
    return normalized


def _is_violation_label(class_name: str) -> bool:
    """Return True if class name indicates missing PPE."""
    normalized = _normalize_label(class_name)
    return (
        normalized.startswith('no-')
        or normalized in {'without-hardhat', 'without-mask', 'without-goggles', 'without-gloves', 'without-safety-vest'}
    )


def _extract_violation_detections(detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter detections to likely PPE-violation classes."""
    return [d for d in detections if _is_violation_label(d.get('class_name', ''))]

# Violation detection state
violation_detector = None
caption_generator = None
report_generator = None
db_manager = None
storage_manager = None
last_violation_time = 0
VIOLATION_COOLDOWN = 3  # seconds between violation CAPTURES (fast - queue handles processing)

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
# REPORT PROGRESS TRACKING
# =========================================================================

def update_report_progress(
    step='',
    current=None,
    total=None,
    status='processing',
    error=None,
    current_step=None,
    completed=None,
    error_message=None,
    **_ignored
):
    """Update the global report generation progress."""
    global report_progress
    with report_progress_lock:
        if current is not None:
            report_progress['current'] = current
        if total is not None:
            report_progress['total'] = total
        step_value = current_step if current_step is not None else step
        if step_value:
            report_progress['current_step'] = step_value
        report_progress['status'] = status
        error_value = error_message if error_message is not None else error
        if error_value:
            report_progress['error_message'] = error_value
        if completed is not None:
            report_progress['completed'] = completed
        if status == 'completed':
            report_progress['completed'] = report_progress.get('total', 0)

def get_report_progress():
    """Get current report generation progress."""
    with report_progress_lock:
        return report_progress.copy()

def reset_report_progress():
    """Reset report progress tracking."""
    global report_progress
    with report_progress_lock:
        report_progress = {
            'current': None,
            'total': 0,
            'completed': 0,
            'status': 'idle',
            'current_step': '',
            'error_message': None
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_startup_step(step_key: str, step_status: str, detail: str = None):
    """Update a startup check step status in a thread-safe manner."""
    with startup_state_lock:
        checks = startup_state.get('checks', {})
        if step_key in checks:
            checks[step_key]['status'] = step_status
            if detail is not None:
                checks[step_key]['detail'] = detail


def _set_startup_progress(progress: int, current_step: str):
    """Update startup progress and status text."""
    with startup_state_lock:
        startup_state['status'] = 'running'
        startup_state['ready'] = False
        startup_state['progress'] = max(0, min(100, int(progress)))
        startup_state['current_step'] = str(current_step)
        startup_state['updated_at'] = _utc_now_iso()


def _set_startup_error(message: str):
    """Mark startup as failed and keep UI locked behind loader."""
    with startup_state_lock:
        startup_state['status'] = 'error'
        startup_state['ready'] = False
        startup_state['error_message'] = str(message)
        startup_state['updated_at'] = _utc_now_iso()


def _set_startup_ready():
    """Mark startup as fully ready."""
    with startup_state_lock:
        startup_state['status'] = 'ready'
        startup_state['ready'] = True
        startup_state['progress'] = 100
        startup_state['current_step'] = 'System ready'
        startup_state['error_message'] = None
        startup_state['updated_at'] = _utc_now_iso()


def get_startup_state_snapshot() -> Dict[str, Any]:
    with startup_state_lock:
        checks = startup_state.get('checks', {})
        completed_checks = sum(1 for c in checks.values() if c.get('status') == 'ok')
        total_checks = len(checks)
        return {
            'status': startup_state.get('status', 'idle'),
            'ready': bool(startup_state.get('ready', False)),
            'progress': int(startup_state.get('progress', 0)),
            'current_step': startup_state.get('current_step', ''),
            'error_message': startup_state.get('error_message'),
            'started_at': startup_state.get('started_at'),
            'updated_at': startup_state.get('updated_at'),
            'checks': checks,
            'checks_completed': completed_checks,
            'checks_total': total_checks
        }


def _run_startup_sequence():
    """Background startup sequence so frontend can show setup progress."""
    try:
        with startup_state_lock:
            startup_state['status'] = 'running'
            startup_state['ready'] = False
            startup_state['progress'] = 0
            startup_state['current_step'] = 'Starting setup checks'
            startup_state['error_message'] = None
            startup_state['started_at'] = _utc_now_iso()
            startup_state['updated_at'] = startup_state['started_at']
            for key in startup_state.get('checks', {}):
                startup_state['checks'][key]['status'] = 'pending'
                startup_state['checks'][key]['detail'] = None

        _set_startup_progress(8, 'Checking pipeline modules')
        if not FULL_PIPELINE_AVAILABLE:
            _set_startup_step('pipeline_imports', 'error', 'Required pipeline modules failed to import')
            raise RuntimeError('Pipeline modules are unavailable. Check environment dependencies and imports.')
        _set_startup_step('pipeline_imports', 'ok', 'Pipeline modules imported successfully')

        if STARTUP_MODEL_WARMUP_ENABLED:
            _set_startup_progress(24, 'Loading YOLO model')

            def _warmup_yolo():
                dummy = np.zeros((640, 640, 3), dtype=np.uint8)
                return predict_image(dummy, conf=0.25)

            _run_with_timeout(
                _warmup_yolo,
                STARTUP_MODEL_WARMUP_TIMEOUT_SECONDS,
                'yolo-warmup'
            )
            _set_startup_step('yolo_model', 'ok', 'YOLO model loaded and warm-up inference completed')
        else:
            _set_startup_progress(24, 'Skipping YOLO warm-up for this deployment')
            try:
                resolved_path = resolve_model_path()
                _set_startup_step(
                    'yolo_model',
                    'ok',
                    f'Skipped warm-up (STARTUP_MODEL_WARMUP_ENABLED=false), model found at {resolved_path}'
                )
            except Exception as yolo_path_exc:
                _set_startup_step('yolo_model', 'error', str(yolo_path_exc))
                raise RuntimeError(f'YOLO model path check failed: {yolo_path_exc}')

        _set_startup_progress(50, 'Initializing detection and report pipeline')
        init_success = initialize_pipeline_components()
        if not init_success:
            _set_startup_step('pipeline_components', 'error', 'Component initialization returned failure')
            raise RuntimeError('Pipeline components failed to initialize')
        _set_startup_step('pipeline_components', 'ok', 'Core components initialized')

        _set_startup_progress(68, 'Verifying Supabase database connection')
        if db_manager is None:
            _set_startup_step('supabase_database', 'error', 'Database manager is unavailable')
            raise RuntimeError('Supabase database manager is not available')

        try:
            db_manager._ensure_connection()
            with db_manager.conn.cursor() as cur:
                cur.execute('SELECT 1 AS startup_ok')
                _ = cur.fetchone()
            _set_startup_step('supabase_database', 'ok', 'Database query test passed')
        except Exception as db_exc:
            _set_startup_step('supabase_database', 'error', str(db_exc))
            raise RuntimeError(f'Supabase database check failed: {db_exc}')

        _set_startup_progress(82, 'Verifying Supabase storage connection')
        if storage_manager is None:
            _set_startup_step('supabase_storage', 'error', 'Storage manager is unavailable')
            raise RuntimeError('Supabase storage manager is not available')

        try:
            _ = storage_manager.client.storage.list_buckets()
            _set_startup_step('supabase_storage', 'ok', 'Storage buckets reachable')
        except Exception as storage_exc:
            _set_startup_step('supabase_storage', 'error', str(storage_exc))
            raise RuntimeError(f'Supabase storage check failed: {storage_exc}')

        _set_startup_progress(93, 'Checking background queue worker')
        if not queue_worker_running:
            _set_startup_step('queue_worker', 'error', 'Queue worker is not running')
            raise RuntimeError('Queue worker failed to start')
        _set_startup_step('queue_worker', 'ok', 'Queue worker is running')

        _set_startup_progress(99, 'Finalizing startup')
        _set_startup_ready()
        logger.info('✅ Startup sequence completed. System is ready.')

    except Exception as e:
        logger.error(f'❌ Startup sequence failed: {e}', exc_info=True)
        _set_startup_error(str(e))


def ensure_startup_thread():
    """Ensure startup sequence is running (or already completed)."""
    global startup_thread

    with startup_state_lock:
        if startup_state.get('ready'):
            return
        if startup_state.get('status') == 'running' and startup_thread and startup_thread.is_alive():
            return

    startup_thread = Thread(target=_run_startup_sequence, daemon=True, name='startup-sequence')
    startup_thread.start()


def _startup_gate_response():
    """Return 503 until startup checks are fully ready."""
    ensure_startup_thread()
    snapshot = get_startup_state_snapshot()
    if snapshot.get('ready'):
        return None

    status_code = 500 if snapshot.get('status') == 'error' else 503
    message = 'System setup failed' if status_code == 500 else 'System setup in progress'
    return jsonify({
        'success': False,
        'error': message,
        'startup': snapshot
    }), status_code

def format_violation_type(class_name: str) -> str:
    """
    Format violation class name for display.
    
    Examples:
        'NO-Hardhat' -> 'Missing Hard Hat'
        'NO-Safety Vest' -> 'Missing Safety Vest'
        'no-hardhat' -> 'Missing Hard Hat'
    """
    # Handle both 'NO-' prefix and lowercase 'no-' prefix
    class_name_upper = class_name.upper()
    if class_name_upper.startswith('NO-'):
        item = class_name[3:]  # Remove 'NO-' or 'no-'
        # Format specific items
        item = item.replace('hardhat', 'Hard Hat').replace('Hardhat', 'Hard Hat')
        item = item.replace('safety vest', 'Safety Vest').replace('Safety Vest', 'Safety Vest')
        item = item.replace('gloves', 'Gloves').replace('Gloves', 'Gloves')
        item = item.replace('mask', 'Mask').replace('Mask', 'Mask')
        item = item.replace('goggles', 'Goggles').replace('Goggles', 'Goggles')
        return f"Missing {item}"
    return class_name

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
            
            # Fix any stuck reports from previous sessions
            if db_manager and hasattr(db_manager, 'fix_stuck_reports'):
                logger.info("Checking for stuck reports...")
                fixed = db_manager.fix_stuck_reports()
                if fixed > 0:
                    logger.info(f"✓ Fixed {fixed} stuck reports")
        
        if storage_manager is None:
            logger.info("Initializing Supabase storage manager...")
            storage_manager = create_storage_manager_from_env()
            
        if report_generator is None:
            logger.info("Initializing Supabase report generator...")
            report_config = {
                'OLLAMA_CONFIG': OLLAMA_CONFIG,
                'GEMINI_CONFIG': GEMINI_CONFIG,
                'MODEL_API_CONFIG': MODEL_API_CONFIG,
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
            
            # Update progress with queue size
            queue_size = violation_queue.get_queue_size() if violation_queue else 0
            if queue_size > 0:
                update_report_progress(
                    total=queue_size,
                    status='waiting',
                    current_step=f'{queue_size} report(s) in queue'
                )
            else:
                reset_report_progress()
            
            # Try to get next violation from queue (with timeout)
            queued_violation = violation_queue.dequeue(timeout=2.0)
            
            if queued_violation is None:
                # No violation in queue, continue waiting
                continue
            
            logger.info(f"📥 Dequeued violation {queued_violation.report_id} for processing")
            
            try:
                # Update progress: starting processing
                queue_size = violation_queue.get_queue_size() if violation_queue else 0
                update_report_progress(
                    current=queued_violation.report_id,
                    total=queue_size + 1,
                    completed=0,
                    status='processing',
                    current_step='Starting report generation'
                )
                
                # Process the violation
                process_queued_violation(queued_violation)
                violation_queue.mark_processed(queued_violation)
                logger.info(f"✅ Completed processing {queued_violation.report_id}")
                
                # Update progress: completed
                update_report_progress(
                    completed=1,
                    status='completed',
                    current_step='Report generated successfully'
                )
                time.sleep(0.5)  # Brief pause to show completed status
                
            except Exception as e:
                # Get full traceback for debugging
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"❌ Error processing {queued_violation.report_id}: {e}")
                logger.error(f"Full traceback:\n{error_details}")
                
                update_report_progress(
                    status='error',
                    error_message=str(e)
                )
                
                # Requeue for retry
                if not violation_queue.requeue(queued_violation):
                    logger.error(f"Max retries exceeded for {queued_violation.report_id}")
                    # Update status to failed with detailed error
                    if db_manager:
                        try:
                            db_manager.update_detection_status(
                                queued_violation.report_id, 
                                'failed', 
                                f"Error: {str(e)}\n\nFull details:\n{error_details[:500]}"  # Limit to 500 chars
                            )
                        except Exception as e2:
                            logger.warning(f"Could not update status: {e2}")
                            
        except Exception as e:
            logger.error(f"Queue worker error: {e}")
            time.sleep(1)
    
    logger.info("Queue worker loop stopped")


def enqueue_violation(frame: np.ndarray, detections: List[Dict]) -> str:
    """
    Capture a violation and add it to the processing queue.
    This is a FAST operation that saves images immediately and queues for report generation.
    
    Args:
        frame: The video frame with the violation
        detections: List of YOLO detections
    
    Returns:
        report_id if successfully queued, None otherwise
    """
    global last_violation_time
    
    logger.info("=" * 80)
    logger.info("ENQUEUE_VIOLATION CALLED (Fast capture + queue)")
    logger.info("=" * 80)
    
    try:
        # Check capture cooldown (shorter than processing time)
        current_time = time.time()
        if current_time - last_violation_time < VIOLATION_COOLDOWN:
            remaining = int(VIOLATION_COOLDOWN - (current_time - last_violation_time))
            logger.info(f"Capture cooldown active ({remaining}s remaining) - skipping")
            return None
        
        last_violation_time = current_time
        
        # Check for violations using unified matcher (same logic as upload/live paths)
        violation_detections = _extract_violation_detections(detections)
        
        if not violation_detections:
            logger.warning("No violations found in detections")
            return None
        
        violation_types_raw = [d['class_name'] for d in violation_detections]
        violation_types = [format_violation_type(vt) for vt in violation_types_raw]
        logger.info(f"🚨 PPE VIOLATION DETECTED: {violation_types}")
        
        # Create violation directory with timestamp (configurable timezone)
        timestamp = get_local_time()
        report_id = timestamp.strftime('%Y%m%d_%H%M%S')
        violation_dir = VIOLATIONS_DIR.absolute() / report_id
        violation_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Created violation directory: {violation_dir}")
        
        # === IMMEDIATE: Save images (fast operation) ===
        # Save original frame
        original_path = violation_dir / 'original.jpg'
        cv2.imwrite(str(original_path), frame)
        logger.info(f"✓ Saved original image: {original_path}")
        
        # Save annotated frame
        _, annotated = predict_image(frame, conf=0.25)
        annotated_path = violation_dir / 'annotated.jpg'
        cv2.imwrite(str(annotated_path), annotated)
        logger.info(f"✓ Saved annotated image: {annotated_path}")
        
        # === IMMEDIATE: Insert pending detection event ===
        if db_manager:
            try:
                db_manager.insert_detection_event(
                    report_id=report_id,
                    timestamp=timestamp.isoformat(),  # Use ISO format to preserve timezone
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
                'timestamp': timestamp.isoformat(),  # Use ISO format
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
    
    # Update progress
    update_report_progress(
        current=report_id,
        current_step='Validating work environment'
    )
    
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
    
    # Update progress
    update_report_progress(
        current=report_id,
        current_step='Generating image caption'
    )
    
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

                if isinstance(caption, str) and caption.startswith('ALERT_LOCAL_MODE_UNAVAILABLE:'):
                    failure_reason = caption.replace('ALERT_LOCAL_MODE_UNAVAILABLE:', '', 1).strip()
                    logger.error(f"❌ Local mode unavailable for {report_id}: {failure_reason}")
                    if db_manager:
                        try:
                            db_manager.update_detection_status(report_id, 'failed', failure_reason)
                        except Exception as status_err:
                            logger.warning(f"Could not update status for local-mode failure: {status_err}")
                    update_report_progress(
                        current=report_id,
                        status='error',
                        error_message=failure_reason
                    )
                    return
                    
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
    failure_reason = None
    if report_generator:
        try:
            # Update progress
            update_report_progress(
                current=report_id,
                current_step='Generating analysis report'
            )
            
            logger.info("📄 Generating NLP report with Llama3...")
            
            violation_types_raw = violation_types
            violation_types_formatted = [format_violation_type(vt) for vt in violation_types_raw]
            
            report_data = {
                'report_id': report_id,
                'timestamp': timestamp,
                'detections': detections,
                'violation_summary': ', '.join(violation_types_formatted),
                'violation_count': len(violation_types_formatted),
                'caption': caption,
                'image_caption': caption,
                'original_image_path': str(original_path),
                'annotated_image_path': str(annotated_path),
                'location': 'Live Stream Monitor',
                'severity': 'HIGH',
                'person_count': len(detections)
            }
            
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
                else:
                    failure_reason = "report.html was not found in violation directory after generation"
            else:
                failure_reason = "Report generator returned empty or missing HTML output"
                            
        except Exception as e:
            logger.error(f"❌ Report generation failed: {e}")
            failure_reason = f"{type(e).__name__}: {e}"
    
    # Do not auto-create fallback report. Keep explicit failed status with detailed reason.
    if not report_created:
        if not failure_reason:
            failure_reason = "Unknown error: report generation did not complete"

        failure_path = violation_dir / 'generation_failure.txt'
        try:
            with open(failure_path, 'w', encoding='utf-8') as f:
                f.write(f"Report ID: {report_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Reason: {failure_reason}\n")
        except Exception as e:
            logger.warning(f"Could not persist generation failure details: {e}")

        if db_manager:
            try:
                db_manager.update_detection_status(
                    report_id,
                    'failed',
                    failure_reason
                )
            except Exception as e:
                logger.warning(f"Could not update failed status for report: {e}")
    
    # Save metadata
    violation_types_formatted = [format_violation_type(vt) for vt in violation_types] if violation_types else []
    metadata = {
        'report_id': report_id,
        'timestamp': timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
        'violation_type': violation_types_formatted[0] if violation_types_formatted else 'PPE Violation',
        'severity': 'HIGH',
        'location': 'Live Stream Monitor',
        'detection_count': len(detections),
        'has_caption': bool(caption),
        'has_report': report_created,
        'failure_reason': failure_reason
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
        
        # Check for violations using unified matcher (same logic as upload/live paths)
        violation_detections = _extract_violation_detections(detections)
        
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

                    if isinstance(caption, str) and caption.startswith('ALERT_LOCAL_MODE_UNAVAILABLE:'):
                        failure_reason = caption.replace('ALERT_LOCAL_MODE_UNAVAILABLE:', '', 1).strip()
                        logger.error(f"❌ Local mode unavailable for {report_id}: {failure_reason}")
                        if db_manager:
                            try:
                                db_manager.update_detection_status(report_id, 'failed', failure_reason)
                            except Exception as status_err:
                                logger.warning(f"Could not update status for local-mode failure: {status_err}")
                        return
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
        
        # Do not auto-create fallback report templates. Keep explicit failed status.
        if not report_created and db_manager:
            failure_reason = "Report generation did not produce model-generated HTML output"
            try:
                db_manager.update_detection_status(report_id, 'failed', failure_reason)
                logger.info(f"✓ Status updated to FAILED: {report_id}")
            except Exception as e:
                logger.warning(f"Could not update failed status: {e}")
        
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
            'has_report': report_created
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
    """Serve frontend (unified mode) or a backend status payload (API-only mode)."""
    ensure_startup_thread()
    if not SERVE_FRONTEND:
        return jsonify({
            'service': 'LUNA PPE API',
            'status': 'ok',
            'frontend_served': False,
            'message': 'Frontend is deployed separately. Use this host for API requests only.'
        })
    return send_from_directory('frontend', 'index.html')


@app.route('/api/system/startup-status', methods=['GET'])
def api_startup_status():
    """Expose startup progress so frontend can block UI until system is fully ready."""
    ensure_startup_thread()
    snapshot = get_startup_state_snapshot()
    status_code = 200
    if snapshot.get('status') == 'error':
        status_code = 500
    elif not snapshot.get('ready'):
        status_code = 202
    return jsonify(snapshot), status_code


@app.route('/favicon.ico')
def favicon():
    """Serve favicon."""
    if not SERVE_FRONTEND:
        abort(404)
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
                            'timestamp': timestamp.isoformat(),
                            'has_original': has_original,
                            'has_annotated': has_annotated,
                            'has_report': has_report,
                            'status': status,
                            'severity': metadata.get('severity', 'HIGH'),
                            'violation_type': metadata.get('violation_type', 'PPE Violation'),
                            'location': metadata.get('location', 'Unknown')
                        })
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
            resolved_person_count = None
            
            if detection_data_parsed:
                # Try to parse violation details from stored detection data
                if isinstance(detection_data_parsed, str):
                    try:
                        detection_data_parsed = json.loads(detection_data_parsed)
                    except:
                        detection_data_parsed = None
                
                if isinstance(detection_data_parsed, dict):
                    detections = detection_data_parsed.get('detections', []) if isinstance(detection_data_parsed.get('detections', []), list) else []
                    detected_people = [
                        d for d in detections
                        if isinstance(d, dict)
                        and isinstance(d.get('class_name'), str)
                        and 'person' in d['class_name'].lower()
                        and not d['class_name'].lower().startswith('no-')
                    ]
                    if detected_people:
                        resolved_person_count = len(detected_people)

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
                        # Convert "NO-Hardhat" to "Hardhat"
                        if item.startswith('NO-') or item.startswith('No-'):
                            ppe_item = item[3:]  # Remove "NO-" prefix
                            missing_ppe.append(ppe_item)
                            ppe_tags.append(item.upper())  # Keep NO-HARDHAT format for tags
                        elif 'Missing' in item:
                            ppe_item = item.replace('Missing ', '').strip()
                            missing_ppe.append(ppe_item)
                            ppe_tags.append(ppe_item.replace(' ', '-').upper())
                
                # Also try parsing "Missing Hardhat" format
                elif 'Missing' in summary:
                    matches = re.findall(r'Missing ([\w\s]+?)(?:,|\.|$)', summary)
                    missing_ppe.extend(matches)
                    ppe_tags.extend([m.replace(' ', '-').upper() for m in matches])

            if resolved_person_count is None:
                resolved_person_count = v.get('person_count', 0)
            
            formatted_violations.append({
                'report_id': v['report_id'],
                'timestamp': v['timestamp'].isoformat() if v.get('timestamp') else None,
                'person_count': resolved_person_count,
                'violation_count': v.get('violation_count') if v.get('violation_count') else len(missing_ppe) if missing_ppe else 1,
                'severity': v.get('severity', 'UNKNOWN'),
                'status': status,
                'device_id': v.get('device_id'),
                'error_message': v.get('error_message'),
                'violation_summary': v.get('violation_summary') or (f"Missing: {', '.join(missing_ppe)}" if missing_ppe else 'PPE Violation'),
                'missing_ppe': missing_ppe,
                'ppe_tags': ppe_tags,
                'violation_type': 'PPE Violation',
                'has_original': bool(v.get('original_image_key')),
                'has_annotated': bool(v.get('annotated_image_key')),
                'has_report': bool(v.get('report_html_key')),
                'detection_data': {
                    'caption_validation': caption_validation
                } if caption_validation else None
            })
        
        return jsonify(formatted_violations)
        
    except Exception as e:
        logger.error(f"Error fetching violations from Supabase: {e}")
        return jsonify({'error': 'Failed to fetch violations'}), 500


@app.route('/api/stats')
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
        # Calculate actual week start (Monday of current week)
        # weekday() returns 0=Monday, 1=Tuesday, etc.
        days_since_monday = now.weekday()
        week_start = today_start - timedelta(days=days_since_monday)
        
        stats = {
            'total': len(violations),
            'today': sum(1 for v in violations if v >= today_start),
            'thisWeek': sum(1 for v in violations if v >= week_start),
            'severity': {
                'high': 0,
                'medium': len(violations),
                'low': 0
            }
        }
        return jsonify(stats)
    
    # Use Supabase
    try:
        violations = db_manager.get_recent_violations(limit=1000)
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Calculate actual week start (Monday of current week)
        # weekday() returns 0=Monday, 1=Tuesday, etc.
        days_since_monday = now.weekday()
        week_start = today_start - timedelta(days=days_since_monday)
        
        # Convert to timezone-aware for comparison if needed
        if violations and violations[0].get('timestamp') and violations[0]['timestamp'].tzinfo:
            from datetime import timezone
            today_start = today_start.replace(tzinfo=timezone.utc)
            week_start = week_start.replace(tzinfo=timezone.utc)
        
        stats = {
            'total': len(violations),
            'today': sum(1 for v in violations if v.get('timestamp') and v['timestamp'] >= today_start),
            'thisWeek': sum(1 for v in violations if v.get('timestamp') and v['timestamp'] >= week_start),
            'severity': {
                'high': sum(1 for v in violations if v.get('severity', '').upper() == 'HIGH'),
                'medium': sum(1 for v in violations if v.get('severity', '').upper() == 'MEDIUM'),
                'low': sum(1 for v in violations if v.get('severity', '').upper() == 'LOW')
            }
        }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error fetching stats from Supabase: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


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
            'timestamp': violation['timestamp'].isoformat() if violation.get('timestamp') else None,
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
        if hasattr(db_manager, 'get_status'):
            status_info = db_manager.get_status(report_id)
        else:
            event = db_manager.get_detection_event(report_id) if hasattr(db_manager, 'get_detection_event') else None
            violation = db_manager.get_violation(report_id) if hasattr(db_manager, 'get_violation') else None
            local_report_exists = bool((VIOLATIONS_DIR / report_id / 'report.html').exists())

            if not event and not violation:
                status_info = None
            else:
                status = str((event or {}).get('status') or '').strip().lower()
                if not status:
                    status = 'completed' if ((violation and violation.get('report_html_key')) or local_report_exists) else 'pending'

                has_report = bool((violation or {}).get('report_html_key')) or local_report_exists

                # Guard against false-completed states with no report artifact.
                if status == 'completed' and not has_report:
                    status = 'failed'
                    if not (event or {}).get('error_message'):
                        if local_report_exists:
                            status = 'completed'
                        else:
                            if hasattr(db_manager, 'update_detection_status'):
                                try:
                                    db_manager.update_detection_status(
                                        report_id,
                                        'failed',
                                        'Completed status had no report artifact; marked failed for consistency.'
                                    )
                                except Exception:
                                    pass

                status_info = {
                    'status': status,
                    'has_report': has_report,
                    'has_original': bool((violation or {}).get('original_image_key')),
                    'has_annotated': bool((violation or {}).get('annotated_image_key')),
                    'device_id': (event or {}).get('device_id'),
                    'error_message': (event or {}).get('error_message'),
                    'timestamp': (event or {}).get('timestamp'),
                    'updated_at': (event or {}).get('updated_at')
                }

                # If generation is stale with no report output, surface a real failure reason.
                if status_info['status'] == 'generating' and not status_info['has_report']:
                    ref_time = status_info.get('updated_at') or status_info.get('timestamp')
                    dt_obj = None
                    if isinstance(ref_time, datetime):
                        dt_obj = ref_time
                    elif isinstance(ref_time, str):
                        try:
                            dt_obj = datetime.fromisoformat(ref_time.replace('Z', '+00:00'))
                        except Exception:
                            dt_obj = None

                    if dt_obj is not None:
                        if dt_obj.tzinfo is None:
                            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                        age_seconds = (datetime.now(timezone.utc) - dt_obj).total_seconds()
                        if age_seconds > 120:
                            timeout_reason = 'Report generation timed out without producing report output.'
                            status_info['status'] = 'failed'
                            status_info['error_message'] = timeout_reason
                            if hasattr(db_manager, 'update_detection_status'):
                                try:
                                    db_manager.update_detection_status(report_id, 'failed', timeout_reason)
                                except Exception:
                                    pass

                # Do not surface stale old error text once report artifact exists.
                if status_info.get('has_report') and status_info.get('status') == 'completed':
                    status_info['error_message'] = None

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
        logger.error(f"Error fetching report status: {e}", exc_info=True)
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


def _iso_or_none(value):
    """Safely convert datetime-like values to ISO8601 strings."""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _build_realtime_snapshot(limit: int = 30) -> Dict[str, Any]:
    """Collect compact realtime state for frontend auto-refresh subscribers."""
    queue_data = {
        'available': violation_queue is not None,
        'worker_running': bool(queue_worker_running),
        'queue_size': 0,
        'total_processed': 0,
        'total_failed': 0
    }

    if violation_queue is not None:
        try:
            stats = violation_queue.get_stats()
            queue_data.update({
                'queue_size': stats.get('current_size', 0),
                'total_processed': stats.get('total_processed', 0),
                'total_failed': stats.get('total_failed', 0)
            })
        except Exception as e:
            logger.debug(f"Queue stats unavailable for realtime snapshot: {e}")

    report_rows = []
    if db_manager is not None and getattr(db_manager, 'conn', None) is not None:
        try:
            with db_manager.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT report_id, status, error_message, timestamp, updated_at
                    FROM public.detection_events
                    ORDER BY COALESCE(updated_at, timestamp) DESC
                    LIMIT %s
                    """,
                    (int(limit),)
                )
                rows = cur.fetchall()

            for row in rows:
                report_rows.append({
                    'report_id': row.get('report_id'),
                    'status': str(row.get('status') or '').strip().lower() or 'unknown',
                    'error_message': row.get('error_message'),
                    'timestamp': _iso_or_none(row.get('timestamp')),
                    'updated_at': _iso_or_none(row.get('updated_at'))
                })
        except Exception as e:
            logger.debug(f"Realtime report snapshot query failed: {e}")

    return {
        'server_time': datetime.now(timezone.utc).isoformat(),
        'queue': queue_data,
        'progress': get_report_progress(),
        'reports': report_rows
    }


@app.route('/api/realtime/stream', methods=['GET'])
def api_realtime_stream():
    """Server-Sent Events stream for live UI updates without manual refresh."""
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

    def _event_stream():
        last_signature = None
        heartbeat_counter = 0

        while True:
            payload = _build_realtime_snapshot(limit=30)
            signature_source = {
                'queue': payload.get('queue'),
                'progress': payload.get('progress'),
                'reports': payload.get('reports')
            }
            signature = json.dumps(signature_source, sort_keys=True, default=str)

            # Push update when state changes; otherwise keep connection warm.
            if signature != last_signature:
                data = json.dumps(payload, default=str)
                yield f"event: update\ndata: {data}\n\n"
                last_signature = signature
                heartbeat_counter = 0
            else:
                heartbeat_counter += 1
                if heartbeat_counter >= 8:
                    heartbeat_counter = 0
                    ping = json.dumps({'server_time': datetime.now(timezone.utc).isoformat()})
                    yield f"event: heartbeat\ndata: {ping}\n\n"

            time.sleep(2)

    response = Response(_event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@app.route('/api/realtime/snapshot', methods=['GET'])
def api_realtime_snapshot():
    """Lightweight realtime snapshot endpoint for websocket-triggered UI refresh."""
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

    limit_raw = request.args.get('limit', '30')
    try:
        limit = max(1, min(100, int(limit_raw)))
    except Exception:
        limit = 30

    payload = _build_realtime_snapshot(limit=limit)
    return jsonify(payload)


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


@app.route('/api/settings/disk-space-status', methods=['GET'])
def api_disk_space_status():
    """Return disk free space and whether it is sufficient for local model mode."""
    try:
        required_gb = float(os.getenv('LOCAL_MODEL_REQUIRED_SPACE_GB', '12'))
        usage = shutil.disk_usage(Path.cwd())

        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_gb = (usage.total - usage.free) / (1024 ** 3)
        sufficient = free_gb >= required_gb

        return jsonify({
            'success': True,
            'required_gb': round(required_gb, 2),
            'free_gb': round(free_gb, 2),
            'used_gb': round(used_gb, 2),
            'total_gb': round(total_gb, 2),
            'sufficient': sufficient,
            'message': (
                'Disk space is sufficient for local model mode.'
                if sufficient else
                'Disk space is low for local model mode. Please choose API mode for optimized experience.'
            )
        })
    except Exception as e:
        logger.error(f"Error checking disk space status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _normalize_provider_order(raw_value, default_order):
    """Normalize provider order payload into a validated list."""
    allowed = {'model_api', 'gemini', 'ollama', 'local'}
    if raw_value is None:
        return list(default_order)

    if isinstance(raw_value, str):
        parts = [p.strip().lower() for p in raw_value.split(',') if p.strip()]
    elif isinstance(raw_value, list):
        parts = [str(p).strip().lower() for p in raw_value if str(p).strip()]
    else:
        return list(default_order)

    filtered = []
    for provider in parts:
        if provider in allowed and provider not in filtered:
            filtered.append(provider)

    return filtered if filtered else list(default_order)


def _current_provider_settings():
    """Return current runtime provider routing settings."""
    try:
        from caption_image import get_runtime_provider_settings
        vision_settings = get_runtime_provider_settings()
    except Exception:
        vision_settings = {
            'vision_provider_order': ['model_api', 'gemini', 'ollama'],
            'vision_api_url': os.getenv('VISION_API_URL', ''),
            'vision_api_model': os.getenv('VISION_API_MODEL', ''),
            'ollama_vision_model': os.getenv('OLLAMA_VISION_MODEL', 'qwen2.5vl'),
            'gemini_vision_model': os.getenv('GEMINI_VISION_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
        }

    return {
        'model_api_enabled': bool(MODEL_API_CONFIG.get('enabled', False)),
        'gemini_enabled': bool(GEMINI_CONFIG.get('enabled', True)),
        'nlp_provider_order': MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local']),
        'embedding_provider_order': MODEL_API_CONFIG.get('embedding_provider_order', ['model_api', 'ollama']),
        'vision_provider_order': vision_settings.get('vision_provider_order', ['model_api', 'gemini', 'ollama']),
        'nlp_model': MODEL_API_CONFIG.get('nlp_model', OLLAMA_CONFIG.get('model', 'llama3')),
        'vision_model': vision_settings.get('vision_api_model', ''),
        'embedding_model': MODEL_API_CONFIG.get('embedding_model', RAG_CONFIG.get('embedding_model', 'nomic-embed-text')),
        'ollama_nlp_model': OLLAMA_CONFIG.get('model', 'llama3'),
        'ollama_vision_model': vision_settings.get('ollama_vision_model', 'qwen2.5vl'),
        'gemini_model': GEMINI_CONFIG.get('model', 'gemini-2.5-flash'),
        'gemini_vision_model': vision_settings.get('gemini_vision_model', GEMINI_CONFIG.get('model', 'gemini-2.5-flash'))
    }


@app.route('/api/settings/provider-routing', methods=['GET', 'POST'])
def api_provider_routing_settings():
    """Get or update runtime provider routing settings for NLP/vision/embeddings."""
    global report_generator

    if request.method == 'GET':
        return jsonify(_current_provider_settings())

    try:
        data = request.get_json(silent=True) or {}

        model_api_enabled = bool(data.get('model_api_enabled', MODEL_API_CONFIG.get('enabled', False)))
        gemini_enabled = bool(data.get('gemini_enabled', GEMINI_CONFIG.get('enabled', True)))

        nlp_provider_order = _normalize_provider_order(
            data.get('nlp_provider_order'),
            MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local'])
        )
        embedding_provider_order = _normalize_provider_order(
            data.get('embedding_provider_order'),
            MODEL_API_CONFIG.get('embedding_provider_order', ['model_api', 'ollama'])
        )
        vision_provider_order = _normalize_provider_order(
            data.get('vision_provider_order'),
            ['model_api', 'gemini', 'ollama']
        )

        # Update in-memory config objects
        MODEL_API_CONFIG['enabled'] = model_api_enabled
        MODEL_API_CONFIG['nlp_provider_order'] = nlp_provider_order
        MODEL_API_CONFIG['embedding_provider_order'] = embedding_provider_order

        if data.get('nlp_model'):
            MODEL_API_CONFIG['nlp_model'] = str(data['nlp_model']).strip()
        if data.get('embedding_model'):
            MODEL_API_CONFIG['embedding_model'] = str(data['embedding_model']).strip()

        GEMINI_CONFIG['enabled'] = gemini_enabled
        if data.get('gemini_model'):
            GEMINI_CONFIG['model'] = str(data['gemini_model']).strip()

        if data.get('ollama_nlp_model'):
            OLLAMA_CONFIG['model'] = str(data['ollama_nlp_model']).strip()

        # Persist to environment for module consumers
        os.environ['MODEL_API_ENABLED'] = 'true' if model_api_enabled else 'false'
        os.environ['GEMINI_ENABLED'] = 'true' if gemini_enabled else 'false'
        os.environ['NLP_PROVIDER_ORDER'] = ','.join(nlp_provider_order)
        os.environ['EMBEDDING_PROVIDER_ORDER'] = ','.join(embedding_provider_order)
        os.environ['VISION_PROVIDER_ORDER'] = ','.join(vision_provider_order)

        if MODEL_API_CONFIG.get('nlp_model'):
            os.environ['NLP_API_MODEL'] = MODEL_API_CONFIG['nlp_model']
        if MODEL_API_CONFIG.get('embedding_model'):
            os.environ['EMBEDDING_API_MODEL'] = MODEL_API_CONFIG['embedding_model']
        if GEMINI_CONFIG.get('model'):
            os.environ['GEMINI_MODEL'] = GEMINI_CONFIG['model']
        if OLLAMA_CONFIG.get('model'):
            os.environ['OLLAMA_MODEL'] = OLLAMA_CONFIG['model']

        # Update captioning module runtime routing without restart
        try:
            from caption_image import update_runtime_provider_settings
            update_runtime_provider_settings({
                'vision_provider_order': vision_provider_order,
                'vision_model': data.get('vision_model'),
                'gemini_vision_model': data.get('gemini_vision_model'),
                'ollama_vision_model': data.get('ollama_vision_model')
            })
        except Exception as caption_err:
            logger.warning(f"Could not update caption provider settings at runtime: {caption_err}")

        # Apply to active report generator immediately
        if report_generator is not None and hasattr(report_generator, 'nlp_provider_order'):
            report_generator.model_api_enabled = MODEL_API_CONFIG.get('enabled', False)
            report_generator.nlp_provider_order = MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local'])
            report_generator.embedding_provider_order = MODEL_API_CONFIG.get('embedding_provider_order', ['model_api', 'ollama'])
            report_generator.nlp_model = MODEL_API_CONFIG.get('nlp_model', report_generator.model)
            report_generator.embedding_api_model = MODEL_API_CONFIG.get('embedding_model', report_generator.embedding_model)
            report_generator.use_gemini = GEMINI_CONFIG.get('enabled', True) and report_generator.gemini_client is not None and getattr(report_generator.gemini_client, 'is_available', False)
            report_generator.model = OLLAMA_CONFIG.get('model', report_generator.model)

        return jsonify({
            'success': True,
            'message': 'Provider routing settings updated',
            'settings': _current_provider_settings()
        })

    except Exception as e:
        logger.error(f"Error updating provider routing settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        if hasattr(db_manager, 'get_pending_reports'):
            all_items = db_manager.get_pending_reports(limit=200)
        elif hasattr(db_manager, 'get_all_violations_with_status'):
            all_items = db_manager.get_all_violations_with_status(limit=200)
        elif hasattr(db_manager, 'get_recent_detection_events'):
            all_items = db_manager.get_recent_detection_events(limit=200)
        else:
            all_items = []

        pending = []
        for p in all_items:
            status = str(p.get('status') or '').strip().lower()
            has_report = bool(p.get('report_html_key'))
            if status in ('pending', 'generating', 'queued', 'processing') or (not status and not has_report):
                ts = p.get('timestamp')
                if hasattr(ts, 'isoformat'):
                    ts_value = ts.isoformat()
                else:
                    ts_value = str(ts) if ts else None

                pending.append({
                    'report_id': p.get('report_id'),
                    'timestamp': ts_value,
                    'status': status or 'pending',
                    'device_id': p.get('device_id'),
                    'severity': p.get('severity')
                })

        formatted = pending[:10]
        return jsonify(formatted)
        
    except Exception as e:
        logger.error(f"Error fetching pending reports: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch pending reports'}), 500


@app.route('/api/report/<report_id>/generate-now', methods=['POST'])
def api_generate_report_now(report_id):
    """Force a report into the processing queue with highest priority."""
    if db_manager is None:
        return jsonify({'success': False, 'error': 'Database not available'}), 503

    if violation_queue is None:
        return jsonify({'success': False, 'error': 'Queue is not initialized'}), 503

    try:
        payload = request.get_json(silent=True) or {}
        force_reprocess = bool(payload.get('force', False))

        event = db_manager.get_detection_event(report_id)
        if not event:
            return jsonify({'success': False, 'error': 'Report not found'}), 404

        current_status = (event.get('status') or '').lower()
        if current_status == 'completed' and not force_reprocess:
            return jsonify({'success': True, 'message': 'Report is already completed', 'already_completed': True})

        violation_dir = VIOLATIONS_DIR.absolute() / report_id
        original_path = violation_dir / 'original.jpg'
        annotated_path = violation_dir / 'annotated.jpg'

        if not original_path.exists():
            return jsonify({
                'success': False,
                'error': 'Original image is missing for this report. Cannot regenerate locally.'
            }), 400

        detections = []
        violation_types = []

        violation = db_manager.get_violation(report_id)
        if violation and isinstance(violation.get('detection_data'), dict):
            detections = violation['detection_data'].get('detections', []) or []

        if detections:
            violation_types = [
                d.get('class_name', '') for d in detections
                if isinstance(d, dict) and 'no-' in d.get('class_name', '').lower()
            ]

        if not annotated_path.exists():
            try:
                frame = cv2.imread(str(original_path))
                if frame is not None:
                    _, annotated = predict_image(frame, conf=0.25)
                    cv2.imwrite(str(annotated_path), annotated)
            except Exception as annotate_err:
                logger.warning(f"Could not regenerate annotated image for {report_id}: {annotate_err}")

        if not queue_worker_running:
            start_queue_worker()

        violation_data = {
            'report_id': report_id,
            'timestamp': event.get('timestamp').isoformat() if event.get('timestamp') else datetime.now().isoformat(),
            'detections': detections,
            'violation_types': violation_types,
            'violation_count': len(violation_types),
            'original_image_path': str(original_path),
            'annotated_image_path': str(annotated_path),
            'violation_dir': str(violation_dir)
        }

        enqueued = violation_queue.enqueue(
            violation_data=violation_data,
            device_id=event.get('device_id') or 'manual_regenerate',
            report_id=report_id,
            severity='CRITICAL'
        )

        if not enqueued:
            return jsonify({'success': False, 'error': 'Could not enqueue report (queue full or rate limited)'}), 409

        db_manager.update_detection_status(report_id, 'pending')

        queue_stats = violation_queue.get_stats()
        return jsonify({
            'success': True,
            'message': 'Report moved to the front of queue for generation' + (' (reprocess mode)' if force_reprocess else ''),
            'report_id': report_id,
            'force_reprocess': force_reprocess,
            'queue_size': queue_stats.get('current_size', 0),
            'worker_running': queue_worker_running
        })

    except Exception as e:
        logger.error(f"Error prioritizing report {report_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


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
            'created_at': log['created_at'].isoformat() if log.get('created_at') else None
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
    failed_view = str(request.args.get('failed', '0')).lower() in ('1', 'true', 'yes')

    if storage_manager is None or db_manager is None:
        # Fallback to local filesystem
        violation_dir = VIOLATIONS_DIR / report_id
        
        if not violation_dir.exists():
            abort(404, description="Report not found")
        
        report_html = violation_dir / 'report.html'
        if report_html.exists():
            trace_payload = _build_traceability_payload(
                report_id=report_id,
                violation={},
                event={},
                source='local_filesystem',
                failed_view_requested=failed_view,
            )
            return _read_local_report_with_trace(report_html, trace_payload)
        else:
            abort(404, description="Report HTML not found")
    
    local_violation_dir = VIOLATIONS_DIR / report_id
    local_report_html = local_violation_dir / 'report.html'

    # Use Supabase
    try:
        event = db_manager.get_detection_event(report_id) if hasattr(db_manager, 'get_detection_event') else None
        event_status = str((event or {}).get('status') or '').strip().lower()
        event_error = (event or {}).get('error_message') or 'Unknown generation error'

        # Get violation data from database
        violation = db_manager.get_violation(report_id)
        trace_payload = _build_traceability_payload(
            report_id=report_id,
            violation=violation or {},
            event=event or {},
            source='supabase_storage',
            failed_view_requested=failed_view,
        )
        
        if not violation:
            if failed_view and event_status in ('failed', 'partial', 'skipped'):
                return _render_regenerate_report_page(
                    report_id,
                    f"Report generation failed: {event_error}. Fallback template views are disabled.",
                    status_code=409
                )

            if local_report_html.exists() and event_status not in ('failed', 'partial', 'skipped'):
                trace_payload = _build_traceability_payload(
                    report_id=report_id,
                    violation={},
                    event=event or {},
                    source='local_filesystem_fallback',
                    failed_view_requested=failed_view,
                )
                return _read_local_report_with_trace(local_report_html, trace_payload)

            if event_status in ('failed', 'partial', 'skipped'):
                return _render_regenerate_report_page(
                    report_id,
                    f"Report generation failed: {event_error}. Fallback template views are disabled.",
                    status_code=409
                )
            abort(404, description="Report not found")
        
        # Get signed URL for report HTML
        report_html_key = violation.get('report_html_key')
        if not report_html_key:
            if failed_view and event_status in ('failed', 'partial', 'skipped'):
                return _render_regenerate_report_page(
                    report_id,
                    f"Report generation failed: {event_error}. Fallback template views are disabled.",
                    status_code=409
                )

            if local_report_html.exists() and event_status not in ('failed', 'partial', 'skipped'):
                trace_payload = _build_traceability_payload(
                    report_id=report_id,
                    violation=violation or {},
                    event=event or {},
                    source='local_filesystem_fallback',
                    failed_view_requested=failed_view,
                )
                return _read_local_report_with_trace(local_report_html, trace_payload)

            if event_status in ('failed', 'partial', 'skipped'):
                return _render_regenerate_report_page(
                    report_id,
                    f"Report generation failed: {event_error}. Fallback template views are disabled.",
                    status_code=409
                )
            abort(404, description="Report HTML not found")
        
        # Download the HTML content and render it
        try:
            html_content = storage_manager.download_file_content(report_html_key)
            if not html_content:
                if local_report_html.exists() and event_status not in ('failed', 'partial', 'skipped'):
                    trace_payload = _build_traceability_payload(
                        report_id=report_id,
                        violation=violation or {},
                        event=event or {},
                        source='local_filesystem_fallback',
                        failed_view_requested=failed_view,
                    )
                    return _read_local_report_with_trace(local_report_html, trace_payload)

                if event_status in ('failed', 'partial', 'skipped'):
                    return _render_regenerate_report_page(
                        report_id,
                        f"Report generation failed: {event_error}. Fallback template views are disabled.",
                        status_code=409
                    )
                abort(404, description="Failed to download report HTML")

            if isinstance(html_content, (bytes, bytearray)):
                html_content = html_content.decode('utf-8', errors='replace')
            elif not isinstance(html_content, str):
                html_content = str(html_content)

            if _looks_like_fallback_template_html(html_content):
                logger.warning(f"Blocked fallback-template HTML from Supabase for report {report_id}")
                return _render_regenerate_report_page(
                    report_id,
                    "Report content is fallback-template output. Regenerate to use model-generated response.",
                    status_code=409
                )
            
            # Return the HTML content directly so browser renders it
            trace_payload = _build_traceability_payload(
                report_id=report_id,
                violation=violation or {},
                event=event or {},
                source='supabase_storage',
                failed_view_requested=failed_view,
            )
            html_content = _repair_report_documentation_block(html_content, report_id)
            html_content = _inject_traceability_widget(html_content, trace_payload)
            return html_content, 200, {
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error downloading report HTML: {e}")
            if local_report_html.exists() and event_status not in ('failed', 'partial', 'skipped'):
                trace_payload = _build_traceability_payload(
                    report_id=report_id,
                    violation=violation or {},
                    event=event or {},
                    source='local_filesystem_fallback',
                    failed_view_requested=failed_view,
                )
                return _read_local_report_with_trace(local_report_html, trace_payload)

            if event_status in ('failed', 'partial', 'skipped'):
                return _render_regenerate_report_page(
                    report_id,
                    f"Report generation failed: {event_error}. Fallback template views are disabled.",
                    status_code=409
                )
            abort(500, description=f"Error loading report: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching report from Supabase: {e}")
        if local_report_html.exists() and not failed_view:
            trace_payload = _build_traceability_payload(
                report_id=report_id,
                violation={},
                event={},
                source='local_filesystem_exception_fallback',
                failed_view_requested=failed_view,
            )
            return _read_local_report_with_trace(local_report_html, trace_payload)
        abort(500, description="Failed to fetch report")


def _safe_parse_json_like(value: Any) -> Dict[str, Any]:
        """Parse JSON-like payloads that may already be dicts or JSON strings."""
        if isinstance(value, dict):
                return value
        if isinstance(value, str):
                try:
                        parsed = json.loads(value)
                        return parsed if isinstance(parsed, dict) else {}
                except Exception:
                        return {}
        return {}


def _caption_placeholder_info(caption: str) -> Dict[str, Any]:
        """Identify whether caption text appears to be a fallback/placeholder string."""
        normalized = str(caption or '').strip()
        lowered = normalized.lower()
        known_markers = [
                'caption generation failed',
                'caption generation returned empty',
                'image captioning not available',
                'failed to generate caption after multiple attempts',
                'error generating caption',
                'could not process image for captioning',
            'alert_local_mode_unavailable',
            'local mode is unavailable on this device',
        ]
        matched_marker = next((m for m in known_markers if m in lowered), None)
        return {
                'is_placeholder': bool(matched_marker),
                'matched_marker': matched_marker,
                'length': len(normalized),
                'preview': normalized[:200]
        }


def _looks_like_fallback_template_html(html_content: str) -> bool:
        """Detect legacy fallback report templates that should not be served as final reports."""
        lowered = str(html_content or '').lower()
        has_fallback_label = (
            'report generator not available' in lowered
            or 'explicit failed-report fallback view' in lowered
        )
        has_setup_instructions = (
            'to enable full report generation' in lowered
            or 'ollama pull llama3' in lowered
        )
        return has_fallback_label and has_setup_instructions


def _render_regenerate_report_page(report_id: str, reason: str, status_code: int = 409):
        """Render an actionable page that lets users trigger report regeneration with one click."""
        safe_report_id = html.escape(str(report_id or 'UNKNOWN'))
        safe_reason = html.escape(str(reason or 'Report content is unavailable'))
        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Report Needs Regeneration - {safe_report_id}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#f3f4f6; margin:0; }}
        .wrap {{ max-width: 760px; margin: 40px auto; background:#fff; border-radius:12px; padding:24px; box-shadow:0 8px 30px rgba(0,0,0,0.08); }}
        h1 {{ margin:0 0 12px 0; color:#111827; font-size: 1.5rem; }}
        .meta {{ color:#374151; margin-bottom: 12px; }}
        .reason {{ background:#fff7ed; border:1px solid #fdba74; color:#9a3412; padding:12px; border-radius:8px; margin:12px 0 16px 0; }}
        .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom: 14px; }}
        button {{ border:none; border-radius:8px; padding:10px 16px; font-weight:700; cursor:pointer; }}
        #regen-btn {{ background:#111827; color:#f9fafb; }}
        #regen-btn:disabled {{ background:#6b7280; cursor:not-allowed; }}
        #open-reports-btn {{ background:#e5e7eb; color:#111827; }}
        #status {{ margin-top:10px; color:#1f2937; font-size:0.95rem; }}
        .stage-list {{ display:flex; gap:8px; flex-wrap:wrap; margin: 8px 0 0 0; padding: 0; list-style: none; }}
        .stage-item {{ padding:6px 10px; border-radius:999px; font-size:12px; font-weight:700; background:#e5e7eb; color:#4b5563; }}
        .stage-item.active {{ background:#f59e0b; color:#111827; }}
        .stage-item.done {{ background:#10b981; color:#ecfeff; }}
        .cooldown {{ margin-top: 6px; color:#b45309; font-size: 0.88rem; }}
        .retry {{ margin-top: 6px; color:#374151; font-size: 0.88rem; }}
    </style>
</head>
<body>
    <div class="wrap">
        <h1>Report content was blocked</h1>
        <div class="meta"><strong>Report ID:</strong> {safe_report_id}</div>
        <div class="reason">{safe_reason}</div>
        <div class="actions">
            <button id="regen-btn" type="button">Regenerate Report Now</button>
            <button id="open-reports-btn" type="button">Back to Reports</button>
        </div>
        <ul class="stage-list" id="stage-list">
            <li class="stage-item" data-stage="idle">Ready</li>
            <li class="stage-item" data-stage="queued">Queued</li>
            <li class="stage-item" data-stage="generating">Generating</li>
            <li class="stage-item" data-stage="completed">Completed</li>
        </ul>
        <div id="status">Ready to regenerate.</div>
        <div id="cooldown" class="cooldown" style="display:none;"></div>
        <div id="retry" class="retry"></div>
    </div>

    <script>
        (function() {{
            const reportId = {json.dumps(str(report_id or ''))};
            const statusEl = document.getElementById('status');
            const regenBtn = document.getElementById('regen-btn');
            const openReportsBtn = document.getElementById('open-reports-btn');
            const cooldownEl = document.getElementById('cooldown');
            const retryEl = document.getElementById('retry');
            const stageEls = Array.from(document.querySelectorAll('.stage-item'));

            const MAX_RETRIES = 5;
            const COOLDOWN_SECONDS = 8;
            const POLL_INTERVAL_MS = 2500;
            const MAX_WAIT_MS = 240000;
            let retryCount = 0;
            let cooldownTimer = null;

            function setStatus(msg) {{
                if (statusEl) statusEl.textContent = msg;
            }}

            function setStage(stage) {{
                const order = ['idle', 'queued', 'generating', 'completed'];
                const idx = order.indexOf(stage);
                stageEls.forEach((el) => {{
                    const elIdx = order.indexOf(el.dataset.stage);
                    el.classList.remove('active', 'done');
                    if (idx >= 0 && elIdx < idx) el.classList.add('done');
                    if (el.dataset.stage === stage) el.classList.add('active');
                    if (stage === 'completed' && el.dataset.stage === 'completed') {{
                        el.classList.remove('active');
                        el.classList.add('done');
                    }}
                }});
            }}

            function updateRetryLabel() {{
                if (!retryEl) return;
                retryEl.textContent = `Retries used: ${{retryCount}} / ${{MAX_RETRIES}}`;
            }}

            function startCooldown(seconds) {{
                if (!cooldownEl) return;
                if (cooldownTimer) clearInterval(cooldownTimer);
                let remaining = seconds;
                regenBtn.disabled = true;
                cooldownEl.style.display = 'block';
                cooldownEl.textContent = `Queue busy. Retry available in ${{remaining}}s...`;
                cooldownTimer = setInterval(() => {{
                    remaining -= 1;
                    if (remaining <= 0) {{
                        clearInterval(cooldownTimer);
                        cooldownTimer = null;
                        cooldownEl.style.display = 'none';
                        regenBtn.disabled = retryCount >= MAX_RETRIES;
                        return;
                    }}
                    cooldownEl.textContent = `Queue busy. Retry available in ${{remaining}}s...`;
                }}, 1000);
            }}

            async function openReportInNewTab() {{
                const url = `/report/${{encodeURIComponent(reportId)}}`;
                const w = window.open(url, '_blank');
                if (!w) {{
                    window.location.href = url;
                    return;
                }}
                setTimeout(() => {{
                    window.location.href = url;
                }}, 700);
            }}

            async function checkStatusAndMaybeOpen() {{
                try {{
                    const res = await fetch(`/api/report/${{encodeURIComponent(reportId)}}/status`, {{ cache: 'no-store' }});
                    const data = await res.json();
                    const status = String((data && data.status) || '').toLowerCase();
                    if (status === 'pending' || status === 'queued') {{
                        setStage('queued');
                        setStatus('Report is queued for regeneration...');
                        return false;
                    }}
                    if (status === 'generating' || status === 'processing') {{
                        setStage('generating');
                        setStatus('Report is generating...');
                        return false;
                    }}
                    if (status === 'completed' && data.has_report) {{
                        setStage('completed');
                        setStatus('Report completed. Opening in a new tab...');
                        await openReportInNewTab();
                        return true;
                    }}
                    return false;
                }} catch (err) {{
                    return false;
                }}
            }}

            async function regenerateNow() {{
                if (!reportId) {{
                    setStatus('Missing report id.');
                    return;
                }}
                if (retryCount >= MAX_RETRIES) {{
                    setStatus('Maximum retries reached. Please wait and refresh later.');
                    regenBtn.disabled = true;
                    return;
                }}

                regenBtn.disabled = true;
                setStage('queued');
                setStatus('Submitting regenerate request...');
                try {{
                    const res = await fetch(`/api/report/${{encodeURIComponent(reportId)}}/generate-now`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ force: true }})
                    }});
                    const data = await res.json().catch(() => ({{}}));
                    if (!res.ok || !data.success) {{
                        retryCount += 1;
                        updateRetryLabel();
                        if (res.status === 409 || res.status === 429 || res.status === 503) {{
                            setStatus(`Regeneration queued failed (${{data.error || 'queue busy'}}).`);
                            startCooldown(COOLDOWN_SECONDS);
                            return;
                        }}
                        throw new Error(data.error || `Request failed with status ${{res.status}}`);
                    }}

                    setStage('queued');
                    setStatus('Regeneration queued. Waiting for report completion...');
                    const start = Date.now();
                    const timer = setInterval(async () => {{
                        const done = await checkStatusAndMaybeOpen();
                        if (done) {{
                            clearInterval(timer);
                            return;
                        }}
                        if (Date.now() - start > MAX_WAIT_MS) {{
                            clearInterval(timer);
                            regenBtn.disabled = false;
                            setStatus('Still processing. You can retry opening this report in a moment.');
                        }}
                    }}, POLL_INTERVAL_MS);
                }} catch (err) {{
                    retryCount += 1;
                    updateRetryLabel();
                    regenBtn.disabled = retryCount >= MAX_RETRIES;
                    setStatus(`Regeneration failed: ${{err.message}}`);
                }}
            }}

            setStage('idle');
            updateRetryLabel();
            checkStatusAndMaybeOpen();

            regenBtn.addEventListener('click', regenerateNow);
            openReportsBtn.addEventListener('click', () => {{
                window.location.href = '/#reports';
            }});
        }})();
    </script>
</body>
</html>"""
        return page, status_code, {'Content-Type': 'text/html; charset=utf-8'}


def _build_traceability_payload(
        report_id: str,
        violation: Dict[str, Any],
        event: Dict[str, Any],
        source: str,
        failed_view_requested: bool
) -> Dict[str, Any]:
        """Build report provenance metadata for in-page traceability widget."""
        violation = violation or {}
        event = event or {}

        detection_data = _safe_parse_json_like(violation.get('detection_data'))
        caption = str(violation.get('caption') or '')
        placeholder = _caption_placeholder_info(caption)

        event_status = str(event.get('status') or '').strip().lower() or None
        event_error = event.get('error_message')
        violation_status = str(violation.get('status') or '').strip().lower() or None

        caption_validation = detection_data.get('caption_validation') if isinstance(detection_data, dict) else None

        detections = []
        if isinstance(detection_data, dict):
            raw_detections = detection_data.get('detections')
            if isinstance(raw_detections, list):
                detections = raw_detections

        def _normalized_label(item: Dict[str, Any]) -> str:
            label = item.get('class_name') if isinstance(item, dict) else None
            if label is None and isinstance(item, dict):
                label = item.get('class')
            label = str(label or '').strip().lower()
            label = label.replace('_', '-').replace(' ', '-')
            return label

        detected_people = [
            d for d in detections
            if _normalized_label(d) in {'person', 'worker', 'man', 'woman'}
        ]
        detected_violations = [
            d for d in detections
            if _normalized_label(d).startswith('no-')
        ]

        person_count = len(detected_people) if detections else (event.get('person_count') if isinstance(event, dict) else None)
        if person_count is None:
            person_count = violation.get('person_count')

        violation_count = len(detected_violations) if detections else (event.get('violation_count') if isinstance(event, dict) else None)
        if violation_count is None:
            violation_count = violation.get('violation_count')

        return {
                'report_id': report_id,
                'inspected_at_utc': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                'served_from': source,
                'failed_view_requested': failed_view_requested,
                'report_status': {
                        'detection_event_status': event_status,
                        'violation_status': violation_status,
                        'error_message': event_error,
                        'has_report_html_key': bool(violation.get('report_html_key')),
                },
                'caption': {
                        'source_classification': 'placeholder_or_fallback' if placeholder['is_placeholder'] else 'model_generated_text',
                        'placeholder_marker': placeholder['matched_marker'],
                        'length': placeholder['length'],
                        'preview': placeholder['preview'],
                },
                'caption_validation': caption_validation,
                'person_count': person_count,
                'violation_count': violation_count,
                'severity': violation.get('severity'),
        }


def _inject_traceability_widget(html_content: str, trace_payload: Dict[str, Any]) -> str:
        """Inject a fixed top toggle widget that reveals traceability metadata on hover/click."""
        if not html_content:
                return html_content

        # Prevent duplicate injection if report already contains the widget.
        if 'id="traceability-widget"' in html_content:
                return html_content

        payload_json = json.dumps(trace_payload or {}, ensure_ascii=False)
        payload_json = payload_json.replace('</', '<\\/')

        widget_html = f"""
<button id=\"report-back-btn\" type=\"button\" class=\"report-back-btn\" title=\"Back to previous page\">BACK</button>
<div id=\"traceability-widget\" class=\"traceability-widget\" aria-label=\"Report traceability\">
    <button id=\"traceability-toggle\" type=\"button\" class=\"traceability-toggle\" aria-expanded=\"false\" title=\"Hover or click to inspect report provenance\">TRACEABILITY</button>
    <section id=\"traceability-panel\" class=\"traceability-panel\" role=\"region\" aria-label=\"Traceability details\">
        <div class=\"traceability-title\">Report Provenance</div>
        <pre id=\"traceability-json\" class=\"traceability-json\"></pre>
    </section>
</div>
<style>
    .report-back-btn {{
        position: fixed;
        top: 8px;
        left: 8px;
        z-index: 2147483647;
        border: 2px solid #1f2937;
        background: #111827;
        color: #f9fafb;
        border-radius: 999px;
        padding: 8px 14px;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.4px;
        cursor: pointer;
        box-shadow: 0 6px 14px rgba(0, 0, 0, 0.25);
    }}
    .report-back-btn:hover {{
        background: #374151;
    }}
    .traceability-widget {{
        position: fixed;
        top: 8px;
        right: 8px;
        z-index: 2147483647;
        font-family: Consolas, 'Courier New', monospace;
    }}
    .traceability-toggle {{
        border: 2px solid #7c2d12;
        background: #f59e0b;
        color: #111827;
        border-radius: 999px;
        padding: 8px 14px;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.4px;
        cursor: pointer;
        box-shadow: 0 6px 14px rgba(0, 0, 0, 0.25);
    }}
    .traceability-toggle:hover {{
        background: #fbbf24;
    }}
    .traceability-panel {{
        margin-top: 8px;
        width: min(92vw, 540px);
        max-height: min(78vh, 540px);
        overflow: auto;
        border: 1px solid #334155;
        border-radius: 10px;
        background: rgba(15, 23, 42, 0.97);
        color: #e2e8f0;
        padding: 10px;
        display: none;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    }}
    .traceability-widget.trace-open .traceability-panel {{
        display: block;
    }}
    .traceability-title {{
        font-size: 12px;
        font-weight: 700;
        margin-bottom: 6px;
        color: #93c5fd;
    }}
    .traceability-json {{
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 11px;
        line-height: 1.35;
    }}
    @media (max-width: 560px), (max-height: 430px) and (orientation: landscape) {{
        .report-back-btn,
        .traceability-toggle {{
            padding: 6px 10px;
            font-size: 11px;
            letter-spacing: 0.2px;
        }}
        .traceability-panel {{
            width: min(96vw, 420px);
            max-height: min(58vh, 320px);
        }}
    }}
</style>
<script>
(() => {{
    const root = document.getElementById('traceability-widget');
    const toggle = document.getElementById('traceability-toggle');
    const pre = document.getElementById('traceability-json');
    const backBtn = document.getElementById('report-back-btn');
    if (!root || !toggle || !pre) return;

    const traceData = {payload_json};
    pre.textContent = JSON.stringify(traceData, null, 2);

    if (backBtn) {{
        backBtn.addEventListener('click', () => {{
            if (window.history.length > 1) {{
                window.history.back();
            }} else if (document.referrer) {{
                window.location.href = document.referrer;
            }} else {{
                window.location.href = '/';
            }}
        }});
    }}

    let pinned = false;
    const setOpen = (open) => root.classList.toggle('trace-open', !!open);

    root.addEventListener('mouseenter', () => {{
        if (!pinned) setOpen(true);
    }});
    root.addEventListener('mouseleave', () => {{
        if (!pinned) setOpen(false);
    }});

    toggle.addEventListener('click', () => {{
        pinned = !pinned;
        setOpen(pinned);
        toggle.setAttribute('aria-expanded', String(pinned));
    }});

    // Fallback handler: ensure documentation buttons always work even if report JS breaks.
    const reportId = traceData.report_id || 'UNKNOWN';
    const timestamp = (traceData.inspected_at_utc || '').replace('T', ' ').replace('Z', ' UTC');
    const severity = (traceData.severity || 'HIGH');

    const openDocWindow = (title, html) => {{
        const win = window.open('', '_blank');
        if (!win) {{
            alert('Popup was blocked. Please allow popups for this site.');
            return;
        }}
        win.document.open();
        win.document.write(html);
        win.document.close();
        win.document.title = title;
    }};

    const openNCR = () => {{
        const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>NCR - ${{reportId}}</title>
        </head><body style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;padding:18px;line-height:1.45;">
        <button onclick="window.print()" style="margin:8px 0;padding:8px 12px;">Print</button><h1 style="margin-bottom:6px;">NON-CONFORMANCE REPORT (NCR)</h1>
        <p><b>Report ID:</b> ${{reportId}}</p><p><b>Timestamp:</b> ${{timestamp}}</p><p><b>Severity:</b> ${{severity}}</p>
        <table border="1" cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;margin-top:10px;"><tr><th align="left">Issue</th><td>PPE non-compliance detected by CASM Safety Monitor</td></tr><tr><th align="left">Immediate Action</th><td>Stop work and restore PPE compliance before continuation</td></tr></table>
        </body></html>`;
        openDocWindow(`NCR - ${{reportId}}`, html);
    }};

    const openJKKP7 = () => {{
        const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>JKKP-7 - ${{reportId}}</title>
        </head><body style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;padding:18px;line-height:1.45;">
        <button onclick="window.print()" style="margin:8px 0;padding:8px 12px;">Print</button><h1 style="margin-bottom:6px;">BORANG JKKP 7</h1>
        <p><b>Report ID:</b> ${{reportId}}</p><p><b>Timestamp:</b> ${{timestamp}}</p>
        <table border="1" cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;margin-top:10px;"><tr><th align="left">Case</th><td>Workplace PPE non-compliance</td></tr><tr><th align="left">Reference</th><td>Auto-generated from CASM report</td></tr></table>
        </body></html>`;
        openDocWindow(`JKKP-7 - ${{reportId}}`, html);
    }};

    const bindDocsButtons = () => {{
        const buttons = Array.from(document.querySelectorAll('button'));
        buttons.forEach((btn) => {{
            const label = (btn.textContent || '').toLowerCase();
            if (label.includes('non-conformance') || label.includes('ncr')) {{
                btn.onclick = (ev) => {{ ev.preventDefault(); openNCR(); }};
            }}
            if (label.includes('jkkp-7') || label.includes('incident form')) {{
                btn.onclick = (ev) => {{ ev.preventDefault(); openJKKP7(); }};
            }}
        }});
    }};

    bindDocsButtons();
}})();
</script>
"""

        if re.search(r'<body[^>]*>', html_content, flags=re.IGNORECASE):
            return re.sub(r'<body[^>]*>', lambda m: m.group(0) + '\n' + widget_html, html_content, count=1, flags=re.IGNORECASE)
        if re.search(r'</body\s*>', html_content, flags=re.IGNORECASE):
            return re.sub(r'</body\s*>', widget_html + '\n</body>', html_content, count=1, flags=re.IGNORECASE)
        return html_content + widget_html


def _repair_report_documentation_block(html_content: str, report_id: str) -> str:
        """Repair malformed Generate Documentation script blocks and bind robust button handlers."""
        if not html_content:
                return html_content

        html_content = re.sub(
                r'<script>\s*function\s+generateNCR\s*\(\)\s*\{[\s\S]*?(?=<div\s+class="footer")',
                '',
                html_content,
                flags=re.IGNORECASE,
        )
        html_content = re.sub(
                r';\s*const\s+ncrWindow\s*=\s*window\.open[\s\S]*?(?=<div\s+class="footer")',
                '',
                html_content,
                flags=re.IGNORECASE,
        )

        html_content = html_content.replace('onclick="generateNCR()"', 'id="btn-generate-ncr"')
        html_content = html_content.replace('onclick="generateJKKP7()"', 'id="btn-generate-jkkp7"')

        report_id_js = json.dumps(str(report_id or 'UNKNOWN'))
        safe_doc_script = (
                "<script>(function(){"
                "const reportId=" + report_id_js + ";"
                "const openDoc=(title,body)=>{const w=window.open('','_blank');if(!w){alert('Popup was blocked. Please allow popups for this site.');return;}w.document.open();w.document.write('<!DOCTYPE html><html><head><meta charset=\\\"UTF-8\\\"><title>'+title+'</title></head><body style=\\\"font-family:Arial,sans-serif;max-width:860px;margin:0 auto;padding:18px;line-height:1.45;\\\">'+body+'</body></html>');w.document.close();};"
                "const openNCR=()=>openDoc('NCR - '+reportId,'<button onclick=\\\"window.print()\\\" style=\\\"margin:8px 0;padding:8px 12px;\\\">Print</button><h1 style=\\\"margin-bottom:6px;\\\">NON-CONFORMANCE REPORT (NCR)</h1><p><b>Report ID:</b> '+reportId+'</p><p><b>Generated:</b> '+new Date().toISOString()+'</p><table border=\\\"1\\\" cellpadding=\\\"8\\\" cellspacing=\\\"0\\\" style=\\\"width:100%;border-collapse:collapse;margin-top:10px;\\\"><tr><th align=\\\"left\\\">Issue</th><td>PPE non-compliance detected by CASM Safety Monitor</td></tr><tr><th align=\\\"left\\\">Immediate Action</th><td>Stop work and restore PPE compliance before continuation</td></tr></table>');"
                "const openJKKP7=()=>openDoc('JKKP-7 - '+reportId,'<button onclick=\\\"window.print()\\\" style=\\\"margin:8px 0;padding:8px 12px;\\\">Print</button><h1 style=\\\"margin-bottom:6px;\\\">BORANG JKKP 7</h1><p><b>Report ID:</b> '+reportId+'</p><p><b>Generated:</b> '+new Date().toISOString()+'</p><table border=\\\"1\\\" cellpadding=\\\"8\\\" cellspacing=\\\"0\\\" style=\\\"width:100%;border-collapse:collapse;margin-top:10px;\\\"><tr><th align=\\\"left\\\">Case</th><td>Workplace PPE non-compliance</td></tr><tr><th align=\\\"left\\\">Reference</th><td>Auto-generated from CASM report</td></tr></table>');"
            "const bind=()=>{const n=document.getElementById('btn-generate-ncr');const j=document.getElementById('btn-generate-jkkp7');if(n)n.onclick=(e)=>{e.preventDefault();openNCR();};if(j)j.onclick=(e)=>{e.preventDefault();openJKKP7();};"
            "const card=document.getElementById('reportSplitCard');const t=document.getElementById('reportExpandToggle');const x=document.getElementById('reportExpandedContext');"
            "if(card&&t&&x){const setExpanded=(expanded)=>{card.classList.toggle('expanded',expanded);t.setAttribute('aria-expanded',String(expanded));x.setAttribute('aria-hidden',String(!expanded));t.textContent=expanded?'Collapse Full Report Context':'Show Full Report Context';};setExpanded(false);t.onclick=(e)=>{e.preventDefault();setExpanded(!card.classList.contains('expanded'));};}};"
                "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',bind);}else{bind();}"
                "})();</script>"
        )

        if re.search(r'</body\s*>', html_content, flags=re.IGNORECASE):
                html_content = re.sub(r'</body\s*>', safe_doc_script + '\n</body>', html_content, count=1, flags=re.IGNORECASE)
        else:
                html_content += safe_doc_script

        return html_content


def _read_local_report_with_trace(local_report_html: Path, trace_payload: Dict[str, Any]):
    """Read local report HTML and inject traceability widget before returning response."""
    try:
        with open(local_report_html, 'r', encoding='utf-8') as f:
            html_content = f.read()

        if _looks_like_fallback_template_html(html_content):
            logger.warning(f"Blocked fallback-template local HTML for report {trace_payload.get('report_id')}")
            return _render_regenerate_report_page(
                str(trace_payload.get('report_id') or ''),
                "Report content is fallback-template output. Regenerate to use model-generated response.",
                status_code=409
            )

        html_content = _repair_report_documentation_block(
            html_content,
            str(trace_payload.get('report_id') or 'UNKNOWN')
        )
        html_content = _inject_traceability_widget(html_content, trace_payload)
        return html_content, 200, {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Could not inject traceability into local report {local_report_html}: {e}")
        return send_from_directory(str(local_report_html.parent), local_report_html.name)


@app.route('/image/<report_id>/<filename>')
def get_image(report_id, filename):
    """Serve violation images from Supabase or local storage."""
    if storage_manager is None or db_manager is None:
        # Fallback to local filesystem
        violation_dir = VIOLATIONS_DIR / report_id
        
        if not violation_dir.exists():
            abort(404, description="Report not found")
        
        if filename not in ['original.jpg', 'annotated.jpg']:
            abort(400, description="Invalid filename")
        
        image_path = violation_dir / filename
        if not image_path.exists():
            abort(404, description="Image not found")
        
        return send_from_directory(str(violation_dir), filename)
    
    # Use Supabase
    try:
        if filename not in ['original.jpg', 'annotated.jpg']:
            abort(400, description="Invalid filename")
        
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

def generate_frames(conf=0.25):
    """Generate frames from active live source with YOLO detection and violation processing."""

    with camera_lock:
        if not _is_active_live_source_locked():
            start_result = _start_live_source_locked(_get_default_live_source())
            if not start_result.get('success'):
                logger.error(start_result.get('message') or 'Failed to initialize live source')
                return
        source_name = live_source_adapter.current_source
    
    logger.info(f"Starting live frame generation from source: {source_name}")
    logger.info("=" * 80)
    logger.info("INITIALIZING PIPELINE COMPONENTS")
    logger.info(f"FULL_PIPELINE_AVAILABLE: {FULL_PIPELINE_AVAILABLE}")
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
                if not _is_active_live_source_locked():
                    break
                ret, frame, error_message = _read_active_frame_locked()
                if not ret:
                    logger.warning(error_message or 'Failed to read frame from active source')
                    break
            
            # Run YOLO detection
            try:
                detections, annotated = predict_image(frame, conf=conf)
                
                # Log all detections for debugging
                if detections:
                    detected_classes = [d['class_name'] for d in detections]
                    logger.debug(f"Detected: {detected_classes}")
                
                # Check for violations in background thread (non-blocking)
                if detections and FULL_PIPELINE_AVAILABLE:
                    violation_detections = _extract_violation_detections(detections)
                    if violation_detections:
                        # Log detected violations
                        violation_classes = [d.get('class_name') for d in violation_detections]
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
                
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
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
    """Live webcam stream with YOLO detection."""
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

    conf = float(request.args.get('conf', 0.10))
    return Response(
        generate_frames(conf=conf),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/live/start', methods=['POST'])
def start_live():
    """Start live monitoring."""
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

    payload = request.get_json(silent=True) or {}
    requested_source = str(payload.get('source', _get_default_live_source()))

    with camera_lock:
        result = _start_live_source_locked(requested_source)

    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('message', 'Failed to start live monitoring')}), 500

    response = {
        'success': True,
        'source': result.get('source', 'webcam'),
        'fallback_to_webcam': bool(result.get('fallback_to_webcam')),
        'message': result.get('message', 'Live monitoring started')
    }
    return jsonify(response)


@app.route('/api/live/stop', methods=['POST'])
def stop_live():
    """Stop live monitoring."""
    with camera_lock:
        _stop_live_source_locked()
    
    return jsonify({'success': True, 'message': 'Live monitoring stopped'})


@app.route('/api/live/status')
def live_status():
    """Get live monitoring status."""
    return jsonify(_build_live_state_payload())


@app.route('/api/live/devices')
def live_devices():
    """Return available live capture sources and default source selection."""
    return jsonify(_build_live_state_payload())


@app.route('/api/live/depth/status')
def live_depth_status():
    """Return RealSense depth telemetry and capability details."""
    payload = _build_live_state_payload()

    with camera_lock:
        depth_telemetry = live_source_adapter.get_depth_telemetry_locked()

    payload['depth_telemetry'] = depth_telemetry
    return jsonify(payload)


@app.route('/api/live/depth/preview')
def live_depth_preview():
    """Return RealSense depth preview image if available."""
    with camera_lock:
        preview = live_source_adapter.get_depth_preview_locked()

    if not preview:
        return Response(status=204)

    return Response(preview, mimetype='image/jpeg')


# =========================================================================
# API ENDPOINTS - IMAGE INFERENCE
# =========================================================================

@app.route('/api/inference/upload', methods=['POST'])
def upload_inference():
    """Run inference on uploaded image and generate report if violations detected."""
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

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
        violation_detections = _extract_violation_detections(detections)
        report_queued = False
        report_queue_reason = None
        queued_report_id = None
        
        # If violations detected, use queue system (consistent with live camera)
        if violation_detections and FULL_PIPELINE_AVAILABLE:
            violation_types = [d['class_name'] for d in violation_detections]
            logger.info(f"🚨 Uploaded image violation detected: {violation_types}")
            
            # Use queue system for processing (same as live camera)
            frame_copy = frame.copy()
            detections_copy = detections.copy()
            queued_report_id = enqueue_violation(frame_copy, detections_copy)
            report_queued = queued_report_id is not None
            if report_queued:
                logger.info(f"📥 Violation queued for processing: {queued_report_id}")
            else:
                report_queue_reason = 'cooldown_or_already_processing'
                logger.info("📭 Violation not queued (cooldown or already processing)")
        elif violation_detections and not FULL_PIPELINE_AVAILABLE:
            report_queue_reason = 'pipeline_components_unavailable'
        
        # Encode annotated image to base64
        _, buffer = cv2.imencode('.jpg', annotated)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'success': True,
            'detections': detections,
            'annotated_image': f'data:image/jpeg;base64,{img_base64}',
            'count': len(detections),
            'violations_detected': len(violation_detections) > 0,
            'violation_count': len(violation_detections),
            'report_queued': report_queued,
            'report_queue_reason': report_queue_reason,
            'report_id': queued_report_id
        })
        
    except Exception as e:
        logger.error(f"Inference error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/report-progress', methods=['GET'])
def api_report_progress():
    """Get current report generation progress."""
    try:
        progress = get_report_progress()
        
        # Add queue size if available
        if violation_queue:
            progress['queue_size'] = violation_queue.get_queue_size()
        else:
            progress['queue_size'] = 0
        
        return jsonify(progress)
        
    except Exception as e:
        logger.error(f"Error getting progress: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/failed-reports', methods=['GET'])
def api_failed_reports():
    """Get detailed information about failed reports for debugging."""
    try:
        if not db_manager:
            return jsonify({'error': 'Database not available'}), 503
        
        # Get all failed reports with error messages
        with db_manager.conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    report_id,
                    timestamp,
                    status,
                    error_message,
                    person_count,
                    violation_count,
                    created_at,
                    updated_at
                FROM public.detection_events
                WHERE status = 'failed'
                ORDER BY timestamp DESC
                LIMIT 50
            """)
            failed_reports = cur.fetchall()
        
        return jsonify({
            'count': len(failed_reports),
            'reports': failed_reports
        })
        
    except Exception as e:
        logger.error(f"Error fetching failed reports: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/reliability/stats', methods=['GET'])
def api_reliability_stats():
    """
    Rolling reliability stats for report generation quality.

    Query params:
      - window: number of most recent detection events to analyze (default 100, max 1000)
    """
    if not db_manager:
        return jsonify({'error': 'Database not available'}), 503

    try:
        try:
            window = int(request.args.get('window', 100))
        except Exception:
            window = 100
        window = max(10, min(window, 1000))

        with db_manager.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    de.report_id,
                    de.timestamp,
                    de.status,
                    de.error_message,
                    v.report_html_key
                FROM public.detection_events de
                LEFT JOIN public.violations v ON de.report_id = v.report_id
                ORDER BY de.timestamp DESC
                LIMIT %s
            """, (window,))
            rows = cur.fetchall()

        fallback_markers = (
            'report generator not available',
            'fallback report',
            'explicit failed-report fallback'
        )

        def _is_fallback_content(report_id: str) -> bool:
            try:
                local_path = VIOLATIONS_DIR / report_id / 'report.html'
                if not local_path.exists():
                    return False
                content = local_path.read_text(encoding='utf-8', errors='ignore')[:4000].lower()
                return any(marker in content for marker in fallback_markers)
            except Exception:
                return False

        totals = {
            'considered': 0,
            'real_success': 0,
            'fallback_needed': 0,
            'hard_failed': 0,
            'in_progress': 0,
            'unknown': 0
        }
        failure_causes = {}

        for row in rows:
            report_id = row.get('report_id')
            status = str(row.get('status') or '').strip().lower()
            error_message = (row.get('error_message') or '').strip()

            local_report_exists = bool((VIOLATIONS_DIR / report_id / 'report.html').exists()) if report_id else False
            has_report = bool(row.get('report_html_key')) or local_report_exists
            fallback_content = _is_fallback_content(report_id) if has_report and report_id else False

            totals['considered'] += 1

            is_real_success = status == 'completed' and has_report and not fallback_content
            is_fallback_needed = (
                status in ('failed', 'partial', 'skipped')
                or (status == 'completed' and not has_report)
                or fallback_content
            )

            if is_real_success:
                totals['real_success'] += 1
            elif is_fallback_needed:
                totals['fallback_needed'] += 1
            elif status in ('pending', 'generating', 'queued', 'processing'):
                totals['in_progress'] += 1
            else:
                totals['unknown'] += 1

            if status in ('failed', 'partial', 'skipped'):
                totals['hard_failed'] += 1
                cause_key = 'unknown'
                upper = error_message.upper()
                if 'RESOURCE_EXHAUSTED' in upper or 'QUOTA' in upper or '429' in upper:
                    cause_key = 'quota_or_rate_limit'
                elif 'JSON' in upper or 'PARSE' in upper:
                    cause_key = 'response_parse_error'
                elif 'TIMEOUT' in upper:
                    cause_key = 'timeout'
                elif "STRFTIME" in upper:
                    cause_key = 'timestamp_format_bug'
                elif error_message:
                    cause_key = 'other_error'
                failure_causes[cause_key] = failure_causes.get(cause_key, 0) + 1

        considered = totals['considered']
        real_success_rate = (totals['real_success'] / considered) if considered else 0.0
        fallback_needed_rate = (totals['fallback_needed'] / considered) if considered else 0.0

        return jsonify({
            'window': window,
            'considered': considered,
            'real_success_count': totals['real_success'],
            'real_success_rate': real_success_rate,
            'fallback_needed_count': totals['fallback_needed'],
            'fallback_needed_rate': fallback_needed_rate,
            'hard_failed_count': totals['hard_failed'],
            'in_progress_count': totals['in_progress'],
            'unknown_count': totals['unknown'],
            'failure_causes': failure_causes
        })

    except Exception as e:
        logger.error(f"Error computing reliability stats: {e}", exc_info=True)
        return jsonify({'error': 'Failed to compute reliability stats'}), 500


# =========================================================================
# SYSTEM INFO ENDPOINTS
# =========================================================================

@app.route('/api/system/info')
def system_info():
    """Get system information."""
    import torch

    try:
        resolved_model_path = resolve_model_path()
        model_exists = True
    except Exception:
        resolved_model_path = None
        model_exists = False
    
    info = {
        'python_version': sys.version,
        'cuda_available': torch.cuda.is_available(),
        'gpu_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        'violations_count': len(list(VIOLATIONS_DIR.iterdir())) if VIOLATIONS_DIR.exists() else 0,
        'model_path': 'Results/ppe_yolov86/weights/best.pt',
        'resolved_model_path': resolved_model_path,
        'model_exists': model_exists
    }
    
    return jsonify(info)


@app.route('/api/health/summary')
def api_health_summary():
    """Return a compact operational health snapshot for the full pipeline."""
    try:
        queue_data = {
            'available': violation_queue is not None,
            'worker_running': bool(queue_worker_running),
            'queue_size': 0,
            'capacity': None,
        }
        if violation_queue is not None:
            try:
                qstats = violation_queue.get_stats()
                queue_data.update({
                    'queue_size': qstats.get('current_size', 0),
                    'capacity': qstats.get('capacity'),
                    'total_processed': qstats.get('total_processed', 0),
                    'total_failed': qstats.get('total_failed', 0),
                    'total_rate_limited': qstats.get('total_rate_limited', 0),
                })
            except Exception as qerr:
                queue_data['error'] = str(qerr)

        rag_file = Path(RAG_CONFIG.get('integration_file', '')) if isinstance(RAG_CONFIG, dict) else None
        rag_file_exists = bool(rag_file and str(rag_file) and rag_file.exists())

        provider_settings = {
            'gemini_enabled': bool((GEMINI_CONFIG or {}).get('enabled', False)),
            'model_api_enabled': bool((MODEL_API_CONFIG or {}).get('enabled', False)),
            'ollama_base_url': (OLLAMA_CONFIG or {}).get('base_url'),
            'nlp_provider_order': (MODEL_API_CONFIG or {}).get('nlp_provider_order', []),
        }

        warnings = []
        if not rag_file_exists:
            warnings.append('RAG integration file missing; regulation enrichment may be reduced')
        if queue_data.get('available') and not queue_data.get('worker_running'):
            warnings.append('Queue available but worker thread is not running')
        if queue_data.get('queue_size', 0) and queue_data.get('worker_running'):
            warnings.append('Queue has pending work; report generation may be delayed')

        return jsonify({
            'timestamp_utc': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
            'status': 'ok',
            'storage_configured': storage_manager is not None,
            'database_configured': db_manager is not None,
            'pipeline_components': {
                'caption_generator': caption_generator is not None,
                'report_generator': report_generator is not None,
            },
            'queue': queue_data,
            'providers': provider_settings,
            'rag_file_exists': rag_file_exists,
            'warnings': warnings,
        })
    except Exception as e:
        logger.error(f"Error building health summary: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# =========================================================================
# ERROR HANDLERS
# =========================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    if not SERVE_FRONTEND:
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
    with camera_lock:
        _stop_live_source_locked()
    
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
    port = int(os.getenv('PORT', '5000'))
    logger.info(f"🚀 Server starting at: http://localhost:{port}")
    logger.info(f"🧭 Frontend serving mode: {'ENABLED' if SERVE_FRONTEND else 'DISABLED (API-only)'}")
    logger.info(f"🌐 Allowed CORS origins: {', '.join(ALLOWED_ORIGINS)}")
    logger.info("")
    logger.info("📊 Features:")
    logger.info("   - Modern web interface")
    logger.info("   - Live webcam monitoring with YOLO")
    logger.info("   - Image upload inference")
    logger.info("   - Violation reports and analytics")
    logger.info("")
    logger.info("🔗 Endpoints:")
    logger.info("   GET  /                          - Main frontend or API status")
    logger.info("   GET  /api/violations            - List violations")
    logger.info("   GET  /api/stats                 - Statistics")
    logger.info("   GET  /api/live/stream           - Live video stream")
    logger.info("   POST /api/live/start            - Start monitoring")
    logger.info("   POST /api/live/stop             - Stop monitoring")
    logger.info("   POST /api/inference/upload      - Upload inference")
    logger.info("")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 80)
    
    # Kick off startup checks asynchronously so frontend can display live progress.
    logger.info("🔧 Starting startup sequence thread...")
    ensure_startup_thread()
    logger.info("ℹ️  Visit /api/system/startup-status to track readiness progress")
    logger.info("")
    
    # Debug mode should ONLY be enabled for local development, NEVER in production
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    if debug_mode:
        logger.warning("⚠️  Flask debug mode is ENABLED - This should ONLY be used for local development!")
        logger.warning("⚠️  NEVER enable debug mode in production as it allows arbitrary code execution!")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        threaded=True,
        use_reloader=False  # Prevent double initialization
    )
