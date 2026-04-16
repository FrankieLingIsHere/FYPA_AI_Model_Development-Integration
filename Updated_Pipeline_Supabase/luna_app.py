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
import subprocess
import html
import hashlib
import hmac
import secrets
from urllib.parse import urlparse, quote
from pathlib import Path
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from typing import List, Dict, Any, Optional, Tuple
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
import requests

# Load environment variables
from dotenv import load_dotenv
load_dotenv(override=False)

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
        'local_mode': {'label': 'Local mode readiness', 'status': 'pending', 'detail': None},
        'supabase_database': {'label': 'Supabase database', 'status': 'pending', 'detail': None},
        'supabase_storage': {'label': 'Supabase storage', 'status': 'pending', 'detail': None},
        'queue_worker': {'label': 'Queue worker', 'status': 'pending', 'detail': None}
    }
}

# In-memory cache for rendered report HTML source payloads to reduce repeated
# storage fetch latency when the same report is opened multiple times.
REPORT_HTML_CACHE_TTL_SECONDS = int(os.getenv('REPORT_HTML_CACHE_TTL_SECONDS', '300'))
report_html_cache_lock = Lock()
report_html_cache: Dict[str, Dict[str, Any]] = {}
REPORT_RENDERED_CACHE_TTL_SECONDS = int(
    os.getenv('REPORT_RENDERED_CACHE_TTL_SECONDS', str(REPORT_HTML_CACHE_TTL_SECONDS))
)
report_rendered_cache_lock = Lock()
report_rendered_cache: Dict[str, Dict[str, Any]] = {}


def _get_cached_report_html_content(report_id: str, report_html_key: str) -> Optional[str]:
    if REPORT_HTML_CACHE_TTL_SECONDS <= 0:
        return None

    now = time.time()
    with report_html_cache_lock:
        entry = report_html_cache.get(report_id)
        if not entry:
            return None
        if entry.get('report_html_key') != report_html_key:
            report_html_cache.pop(report_id, None)
            return None
        expires_at = float(entry.get('expires_at') or 0)
        if expires_at <= now:
            report_html_cache.pop(report_id, None)
            return None
        content = entry.get('content')
        return content if isinstance(content, str) else None


def _set_cached_report_html_content(report_id: str, report_html_key: str, content: str) -> None:
    if REPORT_HTML_CACHE_TTL_SECONDS <= 0:
        return
    if not isinstance(content, str) or not content:
        return

    with report_html_cache_lock:
        report_html_cache[report_id] = {
            'report_html_key': report_html_key,
            'content': content,
            'expires_at': time.time() + REPORT_HTML_CACHE_TTL_SECONDS,
        }
        if len(report_html_cache) > 300:
            # Evict oldest expiring entries to bound memory usage.
            stale_keys = sorted(
                report_html_cache,
                key=lambda k: float(report_html_cache[k].get('expires_at') or 0)
            )[:80]
            for key in stale_keys:
                report_html_cache.pop(key, None)


def _get_cached_rendered_report_html(report_id: str, report_html_key: str) -> Optional[str]:
    if REPORT_RENDERED_CACHE_TTL_SECONDS <= 0:
        return None

    now = time.time()
    with report_rendered_cache_lock:
        entry = report_rendered_cache.get(report_id)
        if not entry:
            return None
        if entry.get('report_html_key') != report_html_key:
            report_rendered_cache.pop(report_id, None)
            return None
        expires_at = float(entry.get('expires_at') or 0)
        if expires_at <= now:
            report_rendered_cache.pop(report_id, None)
            return None
        content = entry.get('content')
        return content if isinstance(content, str) else None


def _set_cached_rendered_report_html(report_id: str, report_html_key: str, content: str) -> None:
    if REPORT_RENDERED_CACHE_TTL_SECONDS <= 0:
        return
    if not isinstance(content, str) or not content:
        return

    with report_rendered_cache_lock:
        report_rendered_cache[report_id] = {
            'report_html_key': report_html_key,
            'content': content,
            'expires_at': time.time() + REPORT_RENDERED_CACHE_TTL_SECONDS,
        }
        if len(report_rendered_cache) > 300:
            stale_keys = sorted(
                report_rendered_cache,
                key=lambda k: float(report_rendered_cache[k].get('expires_at') or 0)
            )[:80]
            for key in stale_keys:
                report_rendered_cache.pop(key, None)

# Import pipeline components for violation handling
try:
    from pipeline.backend.core.violation_detector import ViolationDetector
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    from pipeline.backend.core.report_generator import ReportGenerator
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
EDGE_INGEST_TOKEN = os.getenv('EDGE_INGEST_TOKEN', '').strip()

STARTUP_MODEL_WARMUP_ENABLED = os.getenv(
    'STARTUP_MODEL_WARMUP_ENABLED',
    'true' if SERVE_FRONTEND else 'false'
).lower() == 'true'
STARTUP_MODEL_WARMUP_TIMEOUT_SECONDS = int(os.getenv('STARTUP_MODEL_WARMUP_TIMEOUT_SECONDS', '120'))
STARTUP_COMPONENT_INIT_TIMEOUT_SECONDS = int(os.getenv('STARTUP_COMPONENT_INIT_TIMEOUT_SECONDS', '90'))
STARTUP_MODEL_PATH_CHECK_TIMEOUT_SECONDS = int(os.getenv('STARTUP_MODEL_PATH_CHECK_TIMEOUT_SECONDS', '15'))
STARTUP_MODEL_PATH_CHECK_ENABLED = os.getenv(
    'STARTUP_MODEL_PATH_CHECK_ENABLED',
    'false' if not STARTUP_MODEL_WARMUP_ENABLED else 'true'
).lower() == 'true'
STARTUP_DB_MANAGER_INIT_TIMEOUT_SECONDS = int(os.getenv('STARTUP_DB_MANAGER_INIT_TIMEOUT_SECONDS', '20'))
STARTUP_STORAGE_MANAGER_INIT_TIMEOUT_SECONDS = int(os.getenv('STARTUP_STORAGE_MANAGER_INIT_TIMEOUT_SECONDS', '20'))
STARTUP_REPORT_GENERATOR_INIT_TIMEOUT_SECONDS = int(os.getenv('STARTUP_REPORT_GENERATOR_INIT_TIMEOUT_SECONDS', '30'))
STARTUP_AUTO_PREPARE_LOCAL_MODE = os.getenv('STARTUP_AUTO_PREPARE_LOCAL_MODE', 'false').lower() == 'true'
STARTUP_AUTO_PULL_LOCAL_MODEL = os.getenv('STARTUP_AUTO_PULL_LOCAL_MODEL', 'true').lower() == 'true'
STARTUP_LOCAL_MODE_PREP_WAIT_SECONDS = int(os.getenv('STARTUP_LOCAL_MODE_PREP_WAIT_SECONDS', '6'))
STARTUP_LOCAL_MODE_PULL_TIMEOUT_SECONDS = int(os.getenv('STARTUP_LOCAL_MODE_PULL_TIMEOUT_SECONDS', '240'))
ENABLE_TESTING_ENDPOINTS = os.getenv('ENABLE_TESTING_ENDPOINTS', 'false').lower() == 'true'
ALLOW_OFFLINE_LOCAL_MODE = os.getenv('ALLOW_OFFLINE_LOCAL_MODE', 'true').lower() == 'true'
LOCAL_OLLAMA_UNIFIED_MODEL = str(
    os.getenv('LOCAL_OLLAMA_UNIFIED_MODEL')
    or os.getenv('OLLAMA_MODEL')
    or os.getenv('OLLAMA_VISION_MODEL')
    or (OLLAMA_CONFIG or {}).get('model')
    or 'gemma4'
).strip()


def _is_edge_ingest_authorized() -> bool:
    """Validate edge relay ingest token when configured."""
    if not EDGE_INGEST_TOKEN:
        return True
    supplied = (request.headers.get('X-Edge-Token') or '').strip()
    return supplied == EDGE_INGEST_TOKEN


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


@app.before_request
def _protect_installer_static_asset():
    """Prevent bypassing installer gating through direct static file access."""
    if (request.path or '').strip() == '/static/LUNA_LocalInstaller.bat':
        return Response(
            "Installer download requires a signed one-time bootstrap token. "
            "Request it via /api/bootstrap/installer/request.",
            status=403,
            mimetype='text/plain'
        )
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


def _start_live_source_locked(requested_source: str, camera_index: Optional[int] = None) -> Dict[str, Any]:
    """Start requested source with graceful fallback behavior (lock must be held)."""
    return live_source_adapter.start_locked(requested_source, camera_index=camera_index)


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


def _extract_violation_types_from_detections(detections: List[Dict[str, Any]]) -> List[str]:
    """Extract violation labels from detections using class_name/class with normalized matching."""
    types: List[str] = []
    for item in detections or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get('class_name') or item.get('class') or '').strip()
        if not label:
            continue
        if _is_violation_label(label):
            types.append(label)
    return types


def _extract_violation_types_from_summary(summary: str) -> List[str]:
    """Best-effort parse of persisted summary text into NO-* style violation labels."""
    summary_text = str(summary or '').strip()
    if not summary_text:
        return []

    out: List[str] = []
    lower_summary = summary_text.lower()

    if 'ppe violation detected:' in lower_summary:
        _, _, rhs = summary_text.partition(':')
        for raw_item in rhs.split(','):
            item = str(raw_item or '').strip()
            if not item:
                continue
            if _is_violation_label(item):
                out.append(item)
                continue
            if item.lower().startswith('missing '):
                out.append(f"NO-{item[8:].strip()}")
                continue
            out.append(f"NO-{item}")
        return out

    for match in re.findall(r'Missing ([\\w\\s]+?)(?:,|\\.|$)', summary_text, flags=re.IGNORECASE):
        ppe_item = str(match or '').strip()
        if ppe_item:
            out.append(f"NO-{ppe_item}")

    return out


def _resolve_violation_types_and_count(
    detections: List[Dict[str, Any]],
    *,
    event: Optional[Dict[str, Any]] = None,
    violation_summary: Optional[str] = None,
    fallback_count: Optional[int] = None
) -> Tuple[List[str], int]:
    """Resolve robust violation labels/count even when stored detection payload is partial."""
    violation_types = _extract_violation_types_from_detections(detections)
    if not violation_types:
        violation_types = _extract_violation_types_from_summary(violation_summary or '')

    candidate_counts: List[int] = []
    if fallback_count is not None:
        try:
            candidate_counts.append(int(fallback_count))
        except Exception:
            pass

    if isinstance(event, dict):
        try:
            candidate_counts.append(int(event.get('violation_count') or 0))
        except Exception:
            pass

    resolved_count = max([len(violation_types)] + candidate_counts + [0])
    if resolved_count <= 0:
        resolved_count = 1

    if not violation_types:
        violation_types = ['NO-PPE Violation']

    return violation_types, resolved_count


def _safe_bbox(det: Dict[str, Any]) -> List[float]:
    """Extract bbox as [x1, y1, x2, y2] floats; return [] if invalid."""
    bbox = det.get('bbox') if isinstance(det, dict) else None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return []
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return []
    if x2 <= x1 or y2 <= y1:
        return []
    return [x1, y1, x2, y2]


def _bbox_iou(a: List[float], b: List[float]) -> float:
    """Compute IoU between two [x1, y1, x2, y2] boxes."""
    if len(a) != 4 or len(b) != 4:
        return 0.0

    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter_area
    if denom <= 0:
        return 0.0
    return inter_area / denom


def _bbox_center_distance(a: List[float], b: List[float]) -> float:
    """Compute Euclidean distance between bbox centers."""
    if len(a) != 4 or len(b) != 4:
        return float('inf')
    acx = (a[0] + a[2]) * 0.5
    acy = (a[1] + a[3]) * 0.5
    bcx = (b[0] + b[2]) * 0.5
    bcy = (b[1] + b[3]) * 0.5
    dx = acx - bcx
    dy = acy - bcy
    return float((dx * dx + dy * dy) ** 0.5)


def _build_violation_spatial_signature(violation_detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build compact spatial signatures for violation detections in current frame."""
    signature = []
    for det in violation_detections:
        bbox = _safe_bbox(det)
        if not bbox:
            continue
        signature.append({
            'label': _normalize_label(det.get('class_name', '')),
            'bbox': bbox,
            'score': float(det.get('score', det.get('confidence', 0.0)) or 0.0)
        })

    signature.sort(key=lambda item: item.get('score', 0.0), reverse=True)
    return signature[:6]

# Violation detection state
violation_detector = None
caption_generator = None
report_generator = None
db_manager = None
storage_manager = None
last_violation_time = 0
VIOLATION_COOLDOWN = 3  # seconds between violation CAPTURES (fast - queue handles processing)

# Live-stream dedup window to reduce redundant captures for same standing violators.
LIVE_VIOLATION_DEDUP_WINDOW_SECONDS = 12
LIVE_VIOLATION_DEDUP_IOU_THRESHOLD = 0.50
LIVE_VIOLATION_DEDUP_CENTER_FACTOR = 0.65
recent_live_violation_signatures: List[Dict[str, Any]] = []
recent_live_violation_lock = Lock()


def _is_redundant_live_violation(violation_detections: List[Dict[str, Any]], now_ts: float) -> bool:
    """Return True when current live violation closely matches recent ones in space + class."""
    global recent_live_violation_signatures

    current_signature = _build_violation_spatial_signature(violation_detections)
    if not current_signature:
        return False

    cutoff = now_ts - float(LIVE_VIOLATION_DEDUP_WINDOW_SECONDS)
    with recent_live_violation_lock:
        recent_live_violation_signatures = [
            item for item in recent_live_violation_signatures
            if float(item.get('timestamp', 0.0)) >= cutoff
        ]

        has_new = False
        for current in current_signature:
            current_bbox = current.get('bbox', [])
            current_label = current.get('label', '')
            matched = False

            for previous in recent_live_violation_signatures:
                if previous.get('label') != current_label:
                    continue
                previous_bbox = previous.get('bbox', [])

                iou = _bbox_iou(current_bbox, previous_bbox)
                if iou >= LIVE_VIOLATION_DEDUP_IOU_THRESHOLD:
                    matched = True
                    break

                distance = _bbox_center_distance(current_bbox, previous_bbox)
                prev_w = max(1.0, float(previous_bbox[2]) - float(previous_bbox[0])) if len(previous_bbox) == 4 else 1.0
                prev_h = max(1.0, float(previous_bbox[3]) - float(previous_bbox[1])) if len(previous_bbox) == 4 else 1.0
                max_shift = max(prev_w, prev_h) * float(LIVE_VIOLATION_DEDUP_CENTER_FACTOR)
                if distance <= max_shift:
                    matched = True
                    break

            if not matched:
                has_new = True
                break

        if not has_new:
            return True

        for current in current_signature:
            recent_live_violation_signatures.append({
                'timestamp': now_ts,
                'label': current.get('label', ''),
                'bbox': current.get('bbox', [])
            })
        return False

# Queue-based violation handling (to prevent missing violations)
violation_queue = None  # ViolationQueueManager instance
queue_worker_thread = None  # Background worker for processing queue
queue_worker_running = False
queue_worker_state_lock = Lock()


def _is_queue_worker_alive() -> bool:
    """Return True only when worker flag is set and thread is alive."""
    return bool(queue_worker_running and queue_worker_thread is not None and queue_worker_thread.is_alive())


def ensure_queue_worker_running() -> bool:
    """Best-effort worker self-heal for endpoints that require queue processing."""
    if violation_queue is None:
        return False

    if _is_queue_worker_alive():
        return True

    logger.warning("Queue worker is not healthy; attempting restart")
    return bool(start_queue_worker())

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


def _extract_project_ref_from_supabase_url(value: str) -> str:
    try:
        host = (urlparse(value).hostname or '').strip().lower()
    except Exception:
        host = ''
    if not host:
        return ''
    if host.endswith('.supabase.co'):
        return host.split('.supabase.co')[0]
    return ''


def _extract_db_host(value: str) -> str:
    try:
        host = (urlparse(value).hostname or '').strip().lower()
        return host
    except Exception:
        return ''


def _startup_env_diagnostics() -> Dict[str, Any]:
    supabase_url = os.getenv('SUPABASE_URL', '').strip()
    db_url = os.getenv('SUPABASE_DB_URL', '').strip()
    project_ref = _extract_project_ref_from_supabase_url(supabase_url)
    return {
        'supabase_url_host': (urlparse(supabase_url).hostname or '') if supabase_url else '',
        'supabase_project_ref': project_ref,
        'supabase_db_host': _extract_db_host(db_url),
        'railway_deployment_id': os.getenv('RAILWAY_DEPLOYMENT_ID', '').strip(),
        'railway_service_id': os.getenv('RAILWAY_SERVICE_ID', '').strip(),
        'railway_git_commit_sha': os.getenv('RAILWAY_GIT_COMMIT_SHA', '').strip(),
        'allow_offline_local_mode': ALLOW_OFFLINE_LOCAL_MODE,
        'startup_warmup_enabled': STARTUP_MODEL_WARMUP_ENABLED,
        'startup_auto_prepare_local_mode': STARTUP_AUTO_PREPARE_LOCAL_MODE,
        'startup_auto_pull_local_model': STARTUP_AUTO_PULL_LOCAL_MODEL,
    }


def _set_startup_step(step_key: str, step_status: str, detail: str = None):
    """Update a startup check step status in a thread-safe manner."""
    with startup_state_lock:
        checks = startup_state.get('checks', {})
        if step_key in checks:
            checks[step_key]['status'] = step_status
            if detail is not None:
                checks[step_key]['detail'] = detail
        startup_state['updated_at'] = _utc_now_iso()


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
            'checks_total': total_checks,
            'env_diagnostics': _startup_env_diagnostics()
        }


def _is_offline_local_fallback_available(local_diag: Optional[Dict[str, Any]]) -> bool:
    """Allow startup to continue in offline mode when local runtime is reachable, even if model pull failed."""
    diagnostics = local_diag or {}

    if bool(diagnostics.get('local_mode_possible')):
        return True

    return bool(diagnostics.get('ollama_installed') and diagnostics.get('ollama_running'))


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
                startup_state['checks'][key]['detail'] = 'Not started yet'

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
            if STARTUP_MODEL_PATH_CHECK_ENABLED:
                try:
                    resolved_path = _run_with_timeout(
                        lambda: resolve_model_path(),
                        STARTUP_MODEL_PATH_CHECK_TIMEOUT_SECONDS,
                        'yolo-path-check'
                    )
                    _set_startup_step(
                        'yolo_model',
                        'ok',
                        f'Skipped warm-up (STARTUP_MODEL_WARMUP_ENABLED=false), model found at {resolved_path}'
                    )
                except Exception as yolo_path_exc:
                    _set_startup_step('yolo_model', 'error', str(yolo_path_exc))
                    raise RuntimeError(f'YOLO model path check failed: {yolo_path_exc}')
            else:
                _set_startup_step(
                    'yolo_model',
                    'ok',
                    'Skipped warm-up (STARTUP_MODEL_WARMUP_ENABLED=false); startup model path check disabled'
                )

        _set_startup_progress(50, 'Initializing detection and report pipeline')
        init_success = _run_with_timeout(
            initialize_pipeline_components,
            STARTUP_COMPONENT_INIT_TIMEOUT_SECONDS,
            'pipeline-components-init'
        )
        if not init_success:
            _set_startup_step('pipeline_components', 'error', 'Component initialization returned failure')
            raise RuntimeError('Pipeline components failed to initialize')
        _set_startup_step('pipeline_components', 'ok', 'Core components initialized')

        _set_startup_progress(60, 'Checking local mode readiness (Ollama)')
        try:
            if not STARTUP_AUTO_PREPARE_LOCAL_MODE:
                _set_startup_step('local_mode', 'ok', 'Startup local-mode preparation disabled by env')
            else:
                before_local = _get_local_mode_diagnostics()
                start_action = {
                    'attempted': False,
                    'started': False,
                    'already_running': bool(before_local.get('ollama_running')),
                    'error': None,
                }
                pull_action = {
                    'attempted': False,
                    'pulled': False,
                    'already_available': bool(before_local.get('model_available')),
                    'error': None,
                }

                if before_local.get('ollama_installed') and not before_local.get('ollama_running'):
                    start_action = _start_ollama_service_if_needed(wait_seconds=STARTUP_LOCAL_MODE_PREP_WAIT_SECONDS)

                mid_local = _get_local_mode_diagnostics()
                if (
                    STARTUP_AUTO_PULL_LOCAL_MODEL
                    and mid_local.get('ollama_running')
                    and not mid_local.get('model_available')
                ):
                    pull_action = _pull_ollama_model_if_needed(
                        ollama_base_url=mid_local.get('ollama_base_url') or before_local.get('ollama_base_url') or 'http://localhost:11434',
                        model_name=mid_local.get('ollama_model') or before_local.get('ollama_model') or LOCAL_OLLAMA_UNIFIED_MODEL,
                        timeout_seconds=STARTUP_LOCAL_MODE_PULL_TIMEOUT_SECONDS,
                    )

                after_local = _get_local_mode_diagnostics()
                if after_local.get('local_mode_possible'):
                    _set_startup_step(
                        'local_mode',
                        'ok',
                        f"Ready (running={after_local.get('ollama_running')}, model={after_local.get('ollama_model')}, available={after_local.get('model_available')})"
                    )
                elif after_local.get('ollama_installed'):
                    detail_parts = [
                        f"running={after_local.get('ollama_running')}",
                        f"model_available={after_local.get('model_available')}",
                    ]
                    if start_action.get('error'):
                        detail_parts.append(f"start_error={start_action.get('error')}")
                    if pull_action.get('error'):
                        detail_parts.append(f"pull_error={pull_action.get('error')}")
                    _set_startup_step('local_mode', 'ok', 'Ollama detected but local mode not fully ready: ' + '; '.join(detail_parts))
                else:
                    _set_startup_step('local_mode', 'ok', 'Ollama is not installed on this host; local mode unavailable until installed')
        except Exception as local_mode_exc:
            _set_startup_step('local_mode', 'ok', f'Local mode check skipped due to non-blocking error: {local_mode_exc}')

        _set_startup_progress(68, 'Verifying Supabase database connection')
        if db_manager is None:
            if ALLOW_OFFLINE_LOCAL_MODE:
                if _local_mode_has_supabase_credentials():
                    _set_startup_step('supabase_database', 'ok', 'Supabase DB unavailable; running local-only mode until reconnect')
                else:
                    _set_startup_step('supabase_database', 'ok', 'Supabase credentials pending provisioning; local-only mode active')
            else:
                _set_startup_step('supabase_database', 'error', 'Database manager is unavailable')
                raise RuntimeError('Supabase database manager is not available')

        if db_manager is not None:
            try:
                db_manager._ensure_connection()
                with db_manager.conn.cursor() as cur:
                    cur.execute('SELECT 1 AS startup_ok')
                    _ = cur.fetchone()
                _set_startup_step('supabase_database', 'ok', 'Database query test passed')
            except Exception as db_exc:
                if ALLOW_OFFLINE_LOCAL_MODE:
                    _set_startup_step('supabase_database', 'ok', f'Supabase DB unreachable; local-only mode active ({db_exc})')
                else:
                    _set_startup_step('supabase_database', 'error', str(db_exc))
                    raise RuntimeError(f'Supabase database check failed: {db_exc}')

        _set_startup_progress(82, 'Verifying Supabase storage connection')
        if storage_manager is None:
            if ALLOW_OFFLINE_LOCAL_MODE:
                if _local_mode_has_supabase_credentials():
                    _set_startup_step('supabase_storage', 'ok', 'Supabase Storage unavailable; local artifacts will sync after reconnect')
                else:
                    _set_startup_step('supabase_storage', 'ok', 'Supabase credentials pending provisioning; local artifacts stay local until approval')
            else:
                _set_startup_step('supabase_storage', 'error', 'Storage manager is unavailable')
                raise RuntimeError('Supabase storage manager is not available')

        if storage_manager is not None:
            try:
                _ = storage_manager.client.storage.list_buckets()
                _set_startup_step('supabase_storage', 'ok', 'Storage buckets reachable')
            except Exception as storage_exc:
                if ALLOW_OFFLINE_LOCAL_MODE:
                    _set_startup_step('supabase_storage', 'ok', f'Supabase Storage unreachable; local-only mode active ({storage_exc})')
                else:
                    _set_startup_step('supabase_storage', 'error', str(storage_exc))
                    raise RuntimeError(f'Supabase storage check failed: {storage_exc}')

        _set_startup_progress(93, 'Checking background queue worker')
        if not ensure_queue_worker_running():
            _set_startup_step('queue_worker', 'error', 'Queue worker thread is not healthy')
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
        # Preserve failure details for debugging; do not auto-restart on every request.
        if startup_state.get('status') == 'error':
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

    def _can_run_local_offline() -> bool:
        if not ALLOW_OFFLINE_LOCAL_MODE:
            return False
        try:
            local_diag = _get_local_mode_diagnostics()
            # Keep offline mode available even before model pull completes.
            return bool(local_diag.get('local_mode_possible') or local_diag.get('ollama_installed'))
        except Exception:
            return True

    def _supabase_credentials_ready() -> bool:
        try:
            return _local_mode_has_supabase_credentials()
        except Exception:
            return True
    
    if not FULL_PIPELINE_AVAILABLE:
        logger.warning("Full pipeline not available - skipping component initialization")
        return False
    
    try:
        if violation_detector is None:
            _set_startup_step('pipeline_components', 'pending', 'Initializing violation detector')
            logger.info("Initializing violation detector...")
            violation_detector = ViolationDetector(VIOLATION_RULES)
            
        if caption_generator is None:
            _set_startup_step('pipeline_components', 'pending', 'Initializing caption generator')
            logger.info("Initializing caption generator...")
            caption_config = {'LLAVA_CONFIG': LLAVA_CONFIG}
            caption_generator = CaptionGenerator(caption_config)
        
        if db_manager is None:
            _set_startup_step('pipeline_components', 'pending', 'Initializing Supabase database manager')
            logger.info("Initializing Supabase database manager...")
            if ALLOW_OFFLINE_LOCAL_MODE and not _supabase_credentials_ready():
                logger.warning(
                    "Offline Mode Allowed: Supabase DB credentials are missing/placeholder. "
                    "Deferring DB initialization until provisioning completes."
                )
                db_manager = None
            else:
                try:
                    db_manager = _run_with_timeout(
                        create_db_manager_from_env,
                        STARTUP_DB_MANAGER_INIT_TIMEOUT_SECONDS,
                        'db-manager-init'
                    )
                except Exception as db_init_error:
                    if _can_run_local_offline():
                        logger.warning(
                            f"Offline Mode Allowed: Skipping Supabase DB initialization error: {db_init_error}"
                        )
                        db_manager = None
                    else:
                        raise
            
            # Fix any stuck reports from previous sessions
            if db_manager and hasattr(db_manager, 'fix_stuck_reports'):
                _set_startup_step('pipeline_components', 'pending', 'Recovering stuck reports')
                logger.info("Checking for stuck reports...")
                fixed = _run_with_timeout(
                    db_manager.fix_stuck_reports,
                    int(os.getenv('STARTUP_FIX_STUCK_REPORTS_TIMEOUT_SECONDS', '20')),
                    'fix_stuck_reports'
                )
                if fixed > 0:
                    logger.info(f"✓ Fixed {fixed} stuck reports")
        
        if storage_manager is None:
            _set_startup_step('pipeline_components', 'pending', 'Initializing Supabase storage manager')
            logger.info("Initializing Supabase storage manager...")
            if ALLOW_OFFLINE_LOCAL_MODE and not _supabase_credentials_ready():
                logger.warning(
                    "Offline Mode Allowed: Supabase Storage credentials are missing/placeholder. "
                    "Deferring Storage initialization until provisioning completes."
                )
                storage_manager = None
            else:
                try:
                    storage_manager = _run_with_timeout(
                        create_storage_manager_from_env,
                        STARTUP_STORAGE_MANAGER_INIT_TIMEOUT_SECONDS,
                        'storage-manager-init'
                    )
                except Exception as storage_init_error:
                    if _can_run_local_offline():
                        logger.warning(
                            f"Offline Mode Allowed: Skipping Supabase Storage initialization error: {storage_init_error}"
                        )
                        storage_manager = None
                    else:
                        raise
            
        if report_generator is None:
            use_supabase_generator = db_manager is not None and storage_manager is not None
            if use_supabase_generator:
                _set_startup_step('pipeline_components', 'pending', 'Initializing Supabase report generator')
                logger.info("Initializing Supabase report generator...")
            else:
                _set_startup_step('pipeline_components', 'pending', 'Initializing local report generator fallback')
                logger.info("Initializing local report generator fallback...")

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
            if use_supabase_generator:
                report_generator = _run_with_timeout(
                    lambda: create_supabase_report_generator(report_config),
                    STARTUP_REPORT_GENERATOR_INIT_TIMEOUT_SECONDS,
                    'report-generator-init'
                )
            else:
                if not _can_run_local_offline():
                    raise RuntimeError('Supabase report generator is unavailable and local-offline mode is not ready')

                report_generator = _run_with_timeout(
                    lambda: ReportGenerator(report_config),
                    STARTUP_REPORT_GENERATOR_INIT_TIMEOUT_SECONDS,
                    'report-generator-local-init'
                )
        
        # Initialize violation queue for handling multiple violations
        if violation_queue is None:
            _set_startup_step('pipeline_components', 'pending', 'Initializing violation queue manager')
            logger.info("Initializing violation queue manager...")
            violation_queue = ViolationQueueManager(
                max_size=100,           # Max violations in queue
                rate_limit_per_device=20,  # Allow more per device before rate limiting
                rate_limit_window=60,   # Per minute
                max_retries=3
            )
            logger.info(f"✓ Violation queue initialized (max_size=100)")
        
        # Start queue worker thread if not running
        if not ensure_queue_worker_running():
            _set_startup_step('pipeline_components', 'pending', 'Starting queue worker thread')
            logger.info("Starting violation queue worker thread...")
            if not start_queue_worker():
                logger.error("Failed to start queue worker thread")
                raise RuntimeError('Queue worker thread failed to start during component initialization')
            
        _set_startup_step('pipeline_components', 'ok', 'All pipeline components initialized')
        logger.info("[OK] All pipeline components initialized")
        return True
        
    except Exception as e:
        _set_startup_step('pipeline_components', 'error', f"Initialization failed: {e}")
        logger.error(f"Error initializing pipeline components: {e}")
        import traceback
        traceback.print_exc()
        raise


def start_queue_worker() -> bool:
    """Start the background worker thread for processing queued violations."""
    global queue_worker_thread, queue_worker_running

    with queue_worker_state_lock:
        if queue_worker_thread is not None and queue_worker_thread.is_alive():
            queue_worker_running = True
            logger.info(f"Queue worker already running (Thread ID: {queue_worker_thread.ident})")
            return True

        queue_worker_running = True
        queue_worker_thread = Thread(
            target=queue_worker_loop,
            name="ViolationQueueWorker",
            daemon=True
        )
        queue_worker_thread.start()

        if not queue_worker_thread.is_alive():
            queue_worker_running = False
            logger.error("Queue worker thread failed to become alive after start request")
            return False

        logger.info(f"✓ Queue worker thread started (Thread ID: {queue_worker_thread.ident})")
        return True


def stop_queue_worker():
    """Stop the background queue worker thread."""
    global queue_worker_running, queue_worker_thread

    thread_to_join = None
    with queue_worker_state_lock:
        queue_worker_running = False
        thread_to_join = queue_worker_thread

    if thread_to_join is not None and thread_to_join.is_alive():
        thread_to_join.join(timeout=2.0)

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
    
    with queue_worker_state_lock:
        queue_worker_running = False
    logger.info("Queue worker loop stopped")


def enqueue_violation(frame: np.ndarray, detections: List[Dict], trigger_source: str = 'live') -> str:
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
        trigger_source = (trigger_source or 'live').strip().lower()

        # Check capture cooldown (shorter than processing time)
        current_time = time.time()
        if current_time - last_violation_time < VIOLATION_COOLDOWN:
            remaining = int(VIOLATION_COOLDOWN - (current_time - last_violation_time))
            logger.info(f"Capture cooldown active ({remaining}s remaining) - skipping")
            return None
        
        # Check for violations using unified matcher (same logic as upload/live paths)
        violation_detections = _extract_violation_detections(detections)
        
        if not violation_detections:
            logger.warning("No violations found in detections")
            return None

        if trigger_source == 'live' and _is_redundant_live_violation(violation_detections, current_time):
            logger.info(
                "Live dedup active - skipping redundant stationary violation capture "
                f"(window={LIVE_VIOLATION_DEDUP_WINDOW_SECONDS}s)"
            )
            return None

        last_violation_time = current_time
        
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
    violation_types = data.get('violation_types') or []
    queued_violation_count = data.get('violation_count')
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
    caption_provider = None
    caption_model = None
    try:
        from caption_image import get_runtime_provider_diagnostics
        vision_diag = get_runtime_provider_diagnostics() or {}
        caption_provider = vision_diag.get('last_provider_used')
        provider_key = str(caption_provider or '').strip().lower()
        provider_to_model = {
            'gemini': vision_diag.get('gemini_model'),
            'ollama': vision_diag.get('ollama_model'),
            'model_api': vision_diag.get('vision_api_model'),
        }
        caption_model = provider_to_model.get(provider_key) or vision_diag.get('vision_api_model')
    except Exception:
        pass

    if report_generator:
        try:
            # Update progress
            update_report_progress(
                current=report_id,
                current_step='Generating analysis report'
            )
            
            logger.info(f"📄 Generating NLP report with local model ({LOCAL_OLLAMA_UNIFIED_MODEL})...")
            
            violation_types_raw = violation_types if isinstance(violation_types, list) else []
            if not violation_types_raw:
                violation_types_raw = _extract_violation_types_from_detections(detections)

            resolved_violation_count = max(
                len(violation_types_raw),
                int(queued_violation_count or 0),
                1,
            )
            violation_types_formatted = [format_violation_type(vt) for vt in violation_types_raw]
            violation_summary_text = ', '.join(violation_types_formatted) if violation_types_formatted else 'PPE Violation Detected'
            
            report_data = {
                'report_id': report_id,
                'timestamp': timestamp,
                'detections': detections,
                'violation_summary': violation_summary_text,
                'violation_count': resolved_violation_count,
                'caption': caption,
                'image_caption': caption,
                'caption_provider': caption_provider,
                'caption_model': caption_model,
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
            <p>The local NLP report generator ({LOCAL_OLLAMA_UNIFIED_MODEL}) is not configured or not running.</p>
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
        caption_provider = None
        caption_model = None
        try:
            from caption_image import get_runtime_provider_diagnostics
            vision_diag = get_runtime_provider_diagnostics() or {}
            caption_provider = vision_diag.get('last_provider_used')
            provider_key = str(caption_provider or '').strip().lower()
            provider_to_model = {
                'gemini': vision_diag.get('gemini_model'),
                'ollama': vision_diag.get('ollama_model'),
                'model_api': vision_diag.get('vision_api_model'),
            }
            caption_model = provider_to_model.get(provider_key) or vision_diag.get('vision_api_model')
        except Exception:
            pass
        
        if report_generator:
            try:
                # Update status to "generating"
                if db_manager:
                    try:
                        db_manager.update_detection_status(report_id, 'generating')
                        logger.info(f"✓ Status updated to GENERATING: {report_id}")
                    except Exception as e:
                        logger.warning(f"Could not update status: {e}")
                
                logger.info(f"📄 Generating NLP report with local model ({LOCAL_OLLAMA_UNIFIED_MODEL})...")
                
                report_data = {
                    'report_id': report_id,
                    'timestamp': timestamp,
                    'detections': detections,
                    'violation_summary': f"PPE Violation Detected: {', '.join(violation_types)}",
                    'violation_count': len(violation_detections),
                    'caption': caption,
                    'image_caption': caption,
                    'caption_provider': caption_provider,
                    'caption_model': caption_model,
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


@app.route('/manifest.json')
def web_manifest():
    """Serve web app manifest for PWA installation."""
    if not SERVE_FRONTEND:
        abort(404)
    return send_from_directory('frontend', 'manifest.json', mimetype='application/manifest+json')


@app.route('/service-worker.js')
def service_worker():
    """Serve service worker at root scope for full-app offline support."""
    if not SERVE_FRONTEND:
        abort(404)
    response = send_from_directory('frontend', 'service-worker.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


# =========================================================================
# API ENDPOINTS - VIOLATIONS & REPORTS
# =========================================================================

@app.route('/api/violations')
def api_violations():
    """Get all violations with details from Supabase."""
    requested_limit = request.args.get('limit', 1000, type=int)
    limit = max(1, min(requested_limit or 1000, 5000))

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
            violations = db_manager.get_all_violations_with_status(limit=limit)
        else:
            violations = db_manager.get_recent_violations(limit=limit)
        
        # Format violations for API response
        formatted_violations = []
        for v in violations:
            report_id = v['report_id']
            local_violation_dir = VIOLATIONS_DIR / str(report_id)
            local_has_original = (local_violation_dir / 'original.jpg').exists()
            local_has_annotated = (local_violation_dir / 'annotated.jpg').exists()
            local_has_report = (local_violation_dir / 'report.html').exists()

            # Extract caption validation data if available
            detection_data = v.get('detection_data') or {}
            caption_validation = detection_data.get('caption_validation')
            
            # Determine status - use actual status if available, otherwise infer from data
            status = v.get('status', 'unknown')
            if status == 'unknown':
                if v.get('report_html_key') or local_has_report or v.get('violation_id'):
                    status = 'completed'
                else:
                    status = 'pending'

            # Keep list view aligned with status endpoint: local report artifact means ready.
            if status in ('pending', 'queued', 'generating', 'processing', 'unknown') and local_has_report:
                status = 'completed'
            
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
                'report_id': report_id,
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
                'has_original': bool(v.get('original_image_key')) or local_has_original,
                'has_annotated': bool(v.get('annotated_image_key')) or local_has_annotated,
                'has_report': bool(v.get('report_html_key')) or local_has_report,
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
                    'updated_at': (event or {}).get('updated_at'),
                    'long_running_notice': False,
                    'alert_message': None,
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
                            provider_order = MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local'])
                            if not isinstance(provider_order, list):
                                provider_order = ['model_api', 'gemini', 'ollama', 'local']

                            def _provider_rank(name: str) -> int:
                                try:
                                    return provider_order.index(name)
                                except ValueError:
                                    return 999

                            local_rank = min(_provider_rank('local'), _provider_rank('ollama'))
                            cloud_rank = min(_provider_rank('model_api'), _provider_rank('gemini'))
                            local_preferred = local_rank < cloud_rank

                            local_diag = _get_local_mode_diagnostics()
                            local_ready = bool(local_diag.get('ollama_running') and local_diag.get('model_available'))

                            if local_preferred and local_ready:
                                status_info['status'] = 'generating'
                                status_info['long_running_notice'] = True
                                status_info['alert_message'] = (
                                    'Local model generation is taking longer than expected on this machine. '
                                    'The report is still processing and will complete when ready.'
                                )
                            else:
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
        generating_message = (
            status_info.get('alert_message')
            if status_info.get('long_running_notice')
            else 'AI is analyzing the violation and generating the report'
        )
        messages = {
            'pending': 'Report is queued for processing',
            'generating': generating_message,
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
            'alert_message': status_info.get('alert_message'),
            'message': messages.get(status, 'Status unknown')
        })
        
    except Exception as e:
        logger.error(f"Error fetching report status: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch status'}), 500


@app.route('/api/report/<report_id>/prefetch', methods=['POST'])
def api_report_prefetch(report_id):
    """Warm backend caches so the next /report/<id> open is low-latency."""
    started = time.perf_counter()

    try:
        local_report_html = VIOLATIONS_DIR / report_id / 'report.html'

        if storage_manager is None or db_manager is None:
            if local_report_html.exists():
                return jsonify({
                    'success': True,
                    'report_id': report_id,
                    'warmed': True,
                    'layer': 'local_filesystem',
                    'duration_ms': round((time.perf_counter() - started) * 1000, 2)
                })
            return jsonify({'success': False, 'error': 'Report not found'}), 404

        violation = db_manager.get_violation(report_id)
        if not violation:
            if local_report_html.exists():
                return jsonify({
                    'success': True,
                    'report_id': report_id,
                    'warmed': True,
                    'layer': 'local_filesystem',
                    'duration_ms': round((time.perf_counter() - started) * 1000, 2)
                })
            return jsonify({'success': False, 'error': 'Report not found'}), 404

        report_html_key = violation.get('report_html_key')
        if not report_html_key:
            if local_report_html.exists():
                return jsonify({
                    'success': True,
                    'report_id': report_id,
                    'warmed': True,
                    'layer': 'local_filesystem',
                    'duration_ms': round((time.perf_counter() - started) * 1000, 2)
                })
            return jsonify({'success': False, 'error': 'Report HTML not available'}), 404

        rendered = _get_cached_rendered_report_html(report_id, report_html_key)
        if rendered:
            return jsonify({
                'success': True,
                'report_id': report_id,
                'warmed': True,
                'layer': 'rendered_cache',
                'duration_ms': round((time.perf_counter() - started) * 1000, 2)
            })

        html_content = _get_cached_report_html_content(report_id, report_html_key)
        source_layer = 'source_cache'
        if html_content is None:
            html_content = storage_manager.download_file_content(report_html_key)
            source_layer = 'supabase_storage'

        if not html_content:
            return jsonify({'success': False, 'error': 'Failed to download report HTML'}), 404

        if isinstance(html_content, (bytes, bytearray)):
            html_content = html_content.decode('utf-8', errors='replace')
        elif not isinstance(html_content, str):
            html_content = str(html_content)

        _set_cached_report_html_content(report_id, report_html_key, html_content)

        event = db_manager.get_detection_event(report_id) if hasattr(db_manager, 'get_detection_event') else None
        trace_payload = _build_traceability_payload(
            report_id=report_id,
            violation=violation or {},
            event=event or {},
            source='supabase_storage_prefetch',
            failed_view_requested=False,
        )
        rendered = _repair_report_documentation_block(html_content, report_id)
        rendered = _normalize_report_footer_branding(rendered)
        rendered = _inject_traceability_widget(rendered, trace_payload)
        _set_cached_rendered_report_html(report_id, report_html_key, rendered)

        return jsonify({
            'success': True,
            'report_id': report_id,
            'warmed': True,
            'layer': source_layer,
            'duration_ms': round((time.perf_counter() - started) * 1000, 2)
        })
    except Exception as e:
        logger.warning(f"Report prefetch failed for {report_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
            'worker_running': _is_queue_worker_alive(),
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
        'worker_running': _is_queue_worker_alive(),
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


def _is_quota_related_error(message: str) -> bool:
    text = str(message or '').lower()
    if not text:
        return False
    return (
        'resource_exhausted' in text
        or 'quota' in text
        or 'rate limit' in text
        or '429' in text
        or 'exceeded your current quota' in text
    )


def _detect_ollama_executable() -> str:
    """Return best-effort Ollama executable path, including common non-PATH installs."""
    from_path = shutil.which('ollama')
    if from_path:
        return from_path

    candidates = []
    if os.name == 'nt':
        local_app_data = os.getenv('LOCALAPPDATA', '')
        program_files = os.getenv('ProgramFiles', '')
        program_files_x86 = os.getenv('ProgramFiles(x86)', '')
        candidates.extend([
            os.path.join(local_app_data, 'Programs', 'Ollama', 'ollama.exe'),
            os.path.join(local_app_data, 'Programs', 'Ollama', 'Ollama app.exe'),
            os.path.join(program_files, 'Ollama', 'ollama.exe'),
            os.path.join(program_files, 'Ollama', 'Ollama app.exe'),
            os.path.join(program_files_x86, 'Ollama', 'ollama.exe'),
            os.path.join(program_files_x86, 'Ollama', 'Ollama app.exe'),
        ])
    elif sys.platform == 'darwin':
        candidates.extend([
            '/Applications/Ollama.app/Contents/MacOS/Ollama',
            '/opt/homebrew/bin/ollama',
            '/usr/local/bin/ollama',
        ])
    else:
        candidates.extend([
            '/usr/local/bin/ollama',
            '/usr/bin/ollama',
            '/snap/bin/ollama',
        ])

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return ''


def _get_ollama_install_guidance() -> Dict[str, Any]:
    """Build OS-specific install guidance for Ollama onboarding UX."""
    if os.name == 'nt':
        return {
            'install_url': 'https://ollama.com/download/windows',
            'install_commands': [
                'winget install Ollama.Ollama',
                'choco install ollama -y'
            ],
            'post_install_steps': [
                'Start Ollama app once after install.',
                'If needed, run: ollama serve',
                f'Pull required model: ollama pull {LOCAL_OLLAMA_UNIFIED_MODEL}'
            ]
        }

    if sys.platform == 'darwin':
        return {
            'install_url': 'https://ollama.com/download/mac',
            'install_commands': [
                'brew install --cask ollama'
            ],
            'post_install_steps': [
                'Open Ollama app.',
                'If needed, run: ollama serve',
                f'Pull required model: ollama pull {LOCAL_OLLAMA_UNIFIED_MODEL}'
            ]
        }

    return {
        'install_url': 'https://ollama.com/download/linux',
        'install_commands': [
            'curl -fsSL https://ollama.com/install.sh | sh'
        ],
        'post_install_steps': [
            'Start Ollama service/app.',
            'If needed, run: ollama serve',
            f'Pull required model: ollama pull {LOCAL_OLLAMA_UNIFIED_MODEL}'
        ]
    }


def _get_local_mode_diagnostics() -> Dict[str, Any]:
    ollama_base_url = str(
        os.getenv('OLLAMA_BASE_URL')
        or (OLLAMA_CONFIG or {}).get('base_url')
        or 'http://localhost:11434'
    ).rstrip('/')
    ollama_model = str(
        os.getenv('OLLAMA_MODEL')
        or (OLLAMA_CONFIG or {}).get('model')
        or os.getenv('OLLAMA_VISION_MODEL')
        or LOCAL_OLLAMA_UNIFIED_MODEL
    ).strip()
    ollama_executable = _detect_ollama_executable()
    install_guidance = _get_ollama_install_guidance()

    tags_url = f"{ollama_base_url}/api/tags"
    ollama_running = False
    model_available = False
    probe_error = None

    try:
        resp = requests.get(tags_url, timeout=4)
        ollama_running = resp.ok
        if resp.ok:
            payload = resp.json() if resp.content else {}
            models = payload.get('models', []) if isinstance(payload, dict) else []
            names = []
            for item in models:
                if isinstance(item, dict):
                    name = str(item.get('name') or item.get('model') or '').strip()
                    if name:
                        names.append(name)
            model_available = any(
                name == ollama_model
                or name.startswith(f"{ollama_model}:")
                or name.split(':', 1)[0] == ollama_model
                for name in names
            )
        else:
            probe_error = f"Ollama tags request failed ({resp.status_code})"
    except Exception as e:
        probe_error = str(e)

    return {
        'ollama_base_url': ollama_base_url,
        'ollama_model': ollama_model,
        'ollama_executable': ollama_executable or None,
        'ollama_installed': bool(ollama_executable),
        'ollama_running': ollama_running,
        'model_available': model_available,
        'local_mode_possible': bool(ollama_running and model_available),
        'offline_fallback_available': bool(ollama_running and bool(ollama_executable)),
        'pull_command': f"ollama pull {ollama_model}",
        'start_command': f'"{ollama_executable}" serve' if ollama_executable else 'ollama serve',
        'install_url': install_guidance.get('install_url'),
        'install_commands': install_guidance.get('install_commands', []),
        'post_install_steps': install_guidance.get('post_install_steps', []),
        'error': probe_error,
    }


def _start_ollama_service_if_needed(wait_seconds: int = 8) -> Dict[str, Any]:
    """Best-effort start of Ollama service when not already running."""
    before = _get_local_mode_diagnostics()
    if before.get('ollama_running'):
        return {
            'attempted': False,
            'started': False,
            'already_running': True,
            'error': None,
        }

    ollama_cmd = _detect_ollama_executable()
    if not ollama_cmd:
        guidance = _get_ollama_install_guidance()
        return {
            'attempted': True,
            'started': False,
            'already_running': False,
            'error': 'Ollama executable not found in PATH.',
            'install_url': guidance.get('install_url'),
            'install_commands': guidance.get('install_commands', []),
        }

    try:
        kwargs = {
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'stdin': subprocess.DEVNULL,
        }

        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs['start_new_session'] = True

        cmd_lower = os.path.basename(ollama_cmd).lower()
        if cmd_lower == 'ollama app.exe':
            subprocess.Popen([ollama_cmd], **kwargs)
        else:
            subprocess.Popen([ollama_cmd, 'serve'], **kwargs)

        deadline = time.time() + max(1, int(wait_seconds))
        while time.time() < deadline:
            probe = _get_local_mode_diagnostics()
            if probe.get('ollama_running'):
                return {
                    'attempted': True,
                    'started': True,
                    'already_running': False,
                    'error': None,
                    'start_command': f'"{ollama_cmd}" serve' if cmd_lower != 'ollama app.exe' else f'"{ollama_cmd}"',
                }
            time.sleep(1)

        return {
            'attempted': True,
            'started': False,
            'already_running': False,
            'error': 'Ollama did not become reachable in time.',
            'start_command': f'"{ollama_cmd}" serve' if cmd_lower != 'ollama app.exe' else f'"{ollama_cmd}"',
        }
    except Exception as e:
        return {
            'attempted': True,
            'started': False,
            'already_running': False,
            'error': str(e),
            'start_command': f'"{ollama_cmd}" serve' if 'ollama_cmd' in locals() else 'ollama serve',
        }


def _pull_ollama_model_if_needed(ollama_base_url: str, model_name: str, timeout_seconds: int = 600) -> Dict[str, Any]:
    """Best-effort pull of required Ollama model when missing."""
    diag = _get_local_mode_diagnostics()
    if diag.get('model_available'):
        return {
            'attempted': False,
            'pulled': False,
            'already_available': True,
            'error': None,
        }

    if not diag.get('ollama_running'):
        return {
            'attempted': False,
            'pulled': False,
            'already_available': False,
            'error': 'Ollama is not running; cannot pull model yet.',
        }

    pull_url = f"{str(ollama_base_url).rstrip('/')}/api/pull"
    try:
        response = requests.post(
            pull_url,
            json={'model': model_name, 'stream': False},
            timeout=max(60, int(timeout_seconds))
        )
        if not response.ok:
            return {
                'attempted': True,
                'pulled': False,
                'already_available': False,
                'error': f"Model pull failed (HTTP {response.status_code})",
            }

        post_diag = _get_local_mode_diagnostics()
        return {
            'attempted': True,
            'pulled': bool(post_diag.get('model_available')),
            'already_available': False,
            'error': None if post_diag.get('model_available') else 'Model pull request returned without model availability confirmation.',
        }
    except Exception as e:
        return {
            'attempted': True,
            'pulled': False,
            'already_available': False,
            'error': str(e),
        }


def _apply_nlp_provider_order(order: List[str]) -> List[str]:
    normalized = _normalize_provider_order(order, MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local']))
    MODEL_API_CONFIG['nlp_provider_order'] = normalized
    os.environ['NLP_PROVIDER_ORDER'] = ','.join(normalized)

    if report_generator is not None:
        try:
            report_generator.nlp_provider_order = normalized
        except Exception:
            pass

    return normalized


LOCAL_MODE_PROVISION_STATE_FILE = Path('local_mode_provision_state.json')
LOCAL_MODE_MACHINE_ID_FILE = Path('machine_id.txt')


def _local_mode_normalize_cloud_url(raw_url: str) -> str:
    value = str(raw_url or '').strip()
    if not value:
        return ''
    if not re.match(r'^https?://', value, flags=re.IGNORECASE):
        value = f"https://{value}"
    return value.rstrip('/')


def _local_mode_is_placeholder_secret(value: str) -> bool:
    normalized = str(value or '').strip().lower()
    if not normalized:
        return True
    placeholder_markers = (
        'your-project-id',
        'your-service-role-key',
        'your-db-password',
        'example.supabase.co',
        'postgresql://postgres:your-db-password',
        'postgres://postgres:your-db-password',
    )
    return any(marker in normalized for marker in placeholder_markers)


def _local_mode_has_supabase_credentials() -> bool:
    db_url = os.getenv('SUPABASE_DB_URL', '').strip()
    supa_url = os.getenv('SUPABASE_URL', '').strip()
    service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    return not any(_local_mode_is_placeholder_secret(v) for v in (db_url, supa_url, service_key))


def _local_mode_load_provision_state() -> Dict[str, Any]:
    if not LOCAL_MODE_PROVISION_STATE_FILE.exists():
        return {}
    try:
        with open(LOCAL_MODE_PROVISION_STATE_FILE, 'r') as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _local_mode_save_provision_state(state: Dict[str, Any]) -> None:
    with open(LOCAL_MODE_PROVISION_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def _local_mode_get_or_create_machine_id() -> str:
    existing = ''
    if LOCAL_MODE_MACHINE_ID_FILE.exists():
        try:
            existing = str(LOCAL_MODE_MACHINE_ID_FILE.read_text(encoding='utf-8')).strip()
        except Exception:
            existing = ''

    if existing and re.fullmatch(r'[A-Za-z0-9._:-]{3,120}', existing):
        return existing

    machine_id = f"Edge-{secrets.token_hex(6).upper()}"
    LOCAL_MODE_MACHINE_ID_FILE.write_text(machine_id, encoding='utf-8')
    return machine_id


def _local_mode_upsert_env_values(updates: Dict[str, str], env_path: Path = Path('.env')) -> None:
    env_lines: List[str] = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding='utf-8').splitlines()
    elif Path('.env.example').exists():
        env_lines = Path('.env.example').read_text(encoding='utf-8').splitlines()

    key_pattern = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=')
    replaced_keys: set = set()

    for index, line in enumerate(env_lines):
        match = key_pattern.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in updates:
            env_lines[index] = f"{key}={str(updates[key]).strip()}"
            replaced_keys.add(key)

    if env_lines and env_lines[-1].strip() != '':
        env_lines.append('')

    for key, value in updates.items():
        if key not in replaced_keys:
            env_lines.append(f"{key}={str(value).strip()}")

    env_path.write_text('\n'.join(env_lines).rstrip() + '\n', encoding='utf-8')


def _local_mode_apply_supabase_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
    required_keys = ('SUPABASE_DB_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY')
    resolved_credentials = {
        key: str(credentials.get(key) or '').strip()
        for key in required_keys
    }

    if any(_local_mode_is_placeholder_secret(value) for value in resolved_credentials.values()):
        return {
            'success': False,
            'error': 'Received invalid provisioning credentials from cloud exchange.',
        }

    _local_mode_upsert_env_values(resolved_credentials)
    for key, value in resolved_credentials.items():
        os.environ[key] = value

    reinit_success = False
    reinit_error = None
    try:
        reinit_success = bool(initialize_pipeline_components())
    except Exception as e:
        reinit_error = str(e)

    return {
        'success': True,
        'reinitialized': reinit_success,
        'reinit_error': reinit_error,
    }


@app.route('/api/local-mode/provisioning/status', methods=['GET'])
def api_local_mode_provisioning_status():
    cloud_url = _local_mode_normalize_cloud_url(os.getenv('CLOUD_URL', '').strip())
    state = _local_mode_load_provision_state()
    machine_id = str(state.get('machine_id') or '').strip() or _local_mode_get_or_create_machine_id()
    raw_status = str(state.get('status') or 'idle').strip().lower()
    normalized_status = 'pending_approval' if raw_status == 'pending' else raw_status

    return jsonify({
        'success': True,
        'status': normalized_status,
        'machine_id': machine_id,
        'cloud_url': cloud_url,
        'admin_portal_url': f"{cloud_url}/admin/devices" if cloud_url else '',
        'credentials_present': _local_mode_has_supabase_credentials(),
        'updated_at': state.get('updated_at'),
        'requested_at': state.get('requested_at'),
        'provisioned_at': state.get('provisioned_at'),
    })


@app.route('/api/local-mode/provisioning/auto', methods=['GET', 'POST'])
def api_local_mode_auto_provisioning():
    """Auto-trigger cloud approval + bootstrap credential exchange for local mode access."""
    payload = request.get_json(silent=True) or {}
    if request.method == 'GET':
        query_cloud_url = str(request.args.get('cloud_url') or '').strip()
        if query_cloud_url and not payload.get('cloud_url'):
            payload['cloud_url'] = query_cloud_url
    cloud_url = _local_mode_normalize_cloud_url(
        payload.get('cloud_url')
        or os.getenv('CLOUD_URL')
        or ''
    )

    if not cloud_url:
        return jsonify({
            'success': False,
            'status': 'cloud_url_missing',
            'error': 'CLOUD_URL is not configured. Auto-provisioning cannot contact the cloud dashboard.',
            'hint': 'Set CLOUD_URL in local .env to your deployed cloud dashboard URL.',
        }), 400

    machine_id = _local_mode_get_or_create_machine_id()
    admin_portal_url = f"{cloud_url}/admin/devices"

    if _local_mode_has_supabase_credentials():
        return jsonify({
            'success': True,
            'status': 'credentials_present',
            'provisioned': True,
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        })

    state = _local_mode_load_provision_state()
    provision_secret = str(state.get('provision_secret') or '').strip()

    def _request_new_secret() -> Tuple[bool, str, str]:
        try:
            response = requests.post(
                f"{cloud_url}/api/provision/request",
                json={'machine_id': machine_id},
                timeout=12,
            )
            body = response.json() if response.content else {}
        except Exception as e:
            return False, '', f'Failed to request provisioning approval: {e}'

        if not response.ok:
            err = str((body or {}).get('error') or f'Provision request failed ({response.status_code})')
            return False, '', err

        secret = str((body or {}).get('provision_secret') or '').strip()
        if not secret:
            return False, '', 'Cloud response missing provision_secret.'

        return True, secret, ''

    if not provision_secret or str(state.get('cloud_url') or '') != cloud_url:
        requested, provision_secret, request_error = _request_new_secret()
        if not requested:
            return jsonify({
                'success': False,
                'status': 'request_failed',
                'error': request_error,
                'machine_id': machine_id,
                'admin_portal_url': admin_portal_url,
                'cloud_url': cloud_url,
            }), 502

        state = {
            'machine_id': machine_id,
            'provision_secret': provision_secret,
            'cloud_url': cloud_url,
            'status': 'pending_approval',
            'requested_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        _local_mode_save_provision_state(state)

    try:
        status_response = requests.get(
            f"{cloud_url}/api/provision/status",
            params={
                'machine_id': machine_id,
                'provision_secret': provision_secret,
            },
            timeout=10,
        )
        status_body = status_response.json() if status_response.content else {}
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'poll_failed',
            'error': f'Failed to poll provisioning status: {e}',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 502

    if status_response.status_code in (401, 404):
        retry_ok, retry_secret, retry_error = _request_new_secret()
        if not retry_ok:
            return jsonify({
                'success': False,
                'status': 'request_failed',
                'error': retry_error,
                'machine_id': machine_id,
                'admin_portal_url': admin_portal_url,
                'cloud_url': cloud_url,
            }), 502

        state = {
            'machine_id': machine_id,
            'provision_secret': retry_secret,
            'cloud_url': cloud_url,
            'status': 'pending_approval',
            'requested_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        _local_mode_save_provision_state(state)

        return jsonify({
            'success': True,
            'status': 'pending_approval',
            'message': 'Provision request re-submitted. Waiting for admin approval.',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        })

    if status_response.status_code == 403:
        state.update({
            'machine_id': machine_id,
            'cloud_url': cloud_url,
            'status': 'rejected',
            'updated_at': datetime.now(timezone.utc).isoformat(),
        })
        _local_mode_save_provision_state(state)
        return jsonify({
            'success': False,
            'status': 'rejected',
            'error': 'Provision request was rejected by administrator.',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 403

    if not status_response.ok:
        return jsonify({
            'success': False,
            'status': 'poll_failed',
            'error': str((status_body or {}).get('error') or f'Provision status request failed ({status_response.status_code})'),
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 502

    current_status = str((status_body or {}).get('status') or 'pending').strip().lower()
    state.update({
        'machine_id': machine_id,
        'provision_secret': provision_secret,
        'cloud_url': cloud_url,
        'status': current_status,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    })
    _local_mode_save_provision_state(state)

    if current_status == 'pending':
        return jsonify({
            'success': True,
            'status': 'pending_approval',
            'message': 'Provision request submitted. Waiting for admin approval.',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        })

    bootstrap_token = str((status_body or {}).get('bootstrap_token') or '').strip()
    if not bootstrap_token:
        return jsonify({
            'success': False,
            'status': 'bootstrap_missing',
            'error': 'Cloud approval status did not include bootstrap_token.',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 502

    try:
        exchange_response = requests.post(
            f"{cloud_url}/api/provision/bootstrap-exchange",
            json={
                'machine_id': machine_id,
                'provision_secret': provision_secret,
                'bootstrap_token': bootstrap_token,
            },
            timeout=12,
        )
        exchange_body = exchange_response.json() if exchange_response.content else {}
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'exchange_failed',
            'error': f'Failed to exchange bootstrap token: {e}',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 502

    if not exchange_response.ok:
        return jsonify({
            'success': False,
            'status': 'exchange_failed',
            'error': str((exchange_body or {}).get('error') or f'Bootstrap exchange failed ({exchange_response.status_code})'),
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 502

    credentials = (exchange_body or {}).get('credentials')
    if not isinstance(credentials, dict):
        return jsonify({
            'success': False,
            'status': 'exchange_failed',
            'error': 'Bootstrap exchange did not return credentials payload.',
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 502

    apply_result = _local_mode_apply_supabase_credentials(credentials)
    if not apply_result.get('success'):
        return jsonify({
            'success': False,
            'status': 'apply_failed',
            'error': str(apply_result.get('error') or 'Failed applying provisioned credentials locally.'),
            'machine_id': machine_id,
            'admin_portal_url': admin_portal_url,
            'cloud_url': cloud_url,
        }), 500

    state.update({
        'status': 'provisioned',
        'provisioned_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    })
    _local_mode_save_provision_state(state)

    return jsonify({
        'success': True,
        'status': 'provisioned',
        'provisioned': True,
        'message': 'Admin approval completed and Supabase credentials are now configured locally.',
        'machine_id': machine_id,
        'admin_portal_url': admin_portal_url,
        'cloud_url': cloud_url,
        'reinitialized': bool(apply_result.get('reinitialized')),
        'reinit_error': apply_result.get('reinit_error'),
    })


@app.route('/api/local-mode/prepare', methods=['POST'])
def api_prepare_local_mode():
    """One-click local mode bootstrap: start Ollama, pull model if needed, and optionally switch local-first routing."""
    try:
        payload = request.get_json(silent=True) or {}
        auto_pull = bool(payload.get('auto_pull', True))
        set_local_first = bool(payload.get('set_local_first', True))
        wait_seconds = int(payload.get('wait_seconds', 8) or 8)
        pull_timeout_seconds = int(payload.get('pull_timeout_seconds', 600) or 600)

        before = _get_local_mode_diagnostics()
        actions = {
            'start_service': _start_ollama_service_if_needed(wait_seconds=wait_seconds),
            'pull_model': {
                'attempted': False,
                'pulled': False,
                'already_available': bool(before.get('model_available')),
                'error': None,
            },
            'provider_order': {
                'applied': False,
                'order': MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local'])
            }
        }

        mid = _get_local_mode_diagnostics()
        if auto_pull and mid.get('ollama_running') and not mid.get('model_available'):
            actions['pull_model'] = _pull_ollama_model_if_needed(
                ollama_base_url=mid.get('ollama_base_url') or before.get('ollama_base_url') or 'http://localhost:11434',
                model_name=mid.get('ollama_model') or before.get('ollama_model') or LOCAL_OLLAMA_UNIFIED_MODEL,
                timeout_seconds=pull_timeout_seconds,
            )

        after = _get_local_mode_diagnostics()

        if set_local_first and after.get('local_mode_possible'):
            applied_order = _apply_nlp_provider_order(['local', 'ollama', 'model_api', 'gemini'])
            actions['provider_order'] = {
                'applied': True,
                'order': applied_order,
            }

        ready = bool(after.get('local_mode_possible'))

        return jsonify({
            'success': ready,
            'message': 'Local mode is ready.' if ready else 'Local mode is not ready yet.',
            'before': before,
            'after': after,
            'actions': actions,
        }), 200
    except Exception as e:
        logger.error(f"Error preparing local mode: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _collect_recovery_candidates(limit: int = 200) -> List[Dict[str, Any]]:
    if db_manager is None:
        return []

    rows = []
    try:
        if hasattr(db_manager, 'get_all_violations_with_status'):
            rows = db_manager.get_all_violations_with_status(limit=limit) or []
        elif hasattr(db_manager, 'get_pending_reports'):
            rows = db_manager.get_pending_reports(limit=limit) or []
    except Exception as e:
        logger.warning(f"Failed collecting recovery candidates: {e}")
        rows = []

    candidates = []
    for row in rows:
        status = str((row or {}).get('status') or '').strip().lower()
        error_message = str((row or {}).get('error_message') or '').strip()
        report_id = (row or {}).get('report_id')
        if not report_id:
            continue

        pending_like = status in ('pending', 'queued', 'processing', 'generating')
        quota_failed = status == 'failed' and _is_quota_related_error(error_message)
        if not (pending_like or quota_failed):
            continue

        candidates.append({
            'report_id': report_id,
            'status': status,
            'error_message': error_message,
            'device_id': (row or {}).get('device_id')
        })

    return candidates


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
            'ollama_vision_model': os.getenv('OLLAMA_VISION_MODEL', LOCAL_OLLAMA_UNIFIED_MODEL),
            'gemini_vision_model': os.getenv('GEMINI_VISION_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
        }

    ollama_nlp_model = str(OLLAMA_CONFIG.get('model') or os.getenv('OLLAMA_MODEL') or LOCAL_OLLAMA_UNIFIED_MODEL).strip()
    ollama_vision_model = str(vision_settings.get('ollama_vision_model') or os.getenv('OLLAMA_VISION_MODEL') or ollama_nlp_model).strip()

    return {
        'model_api_enabled': bool(MODEL_API_CONFIG.get('enabled', False)),
        'gemini_enabled': bool(GEMINI_CONFIG.get('enabled', True)),
        'gemini_daily_budget_usd': float(os.getenv('GEMINI_DAILY_BUDGET_USD', '0') or 0),
        'gemini_monthly_budget_usd': float(os.getenv('GEMINI_MONTHLY_BUDGET_USD', '0') or 0),
        'gemini_max_output_tokens_per_report': int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS_PER_REPORT', '900') or 900),
        'nlp_provider_order': MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local']),
        'embedding_provider_order': MODEL_API_CONFIG.get('embedding_provider_order', ['model_api', 'ollama']),
        'vision_provider_order': vision_settings.get('vision_provider_order', ['model_api', 'gemini', 'ollama']),
        'nlp_model': MODEL_API_CONFIG.get('nlp_model', ollama_nlp_model),
        'vision_model': vision_settings.get('vision_api_model', ''),
        'embedding_model': MODEL_API_CONFIG.get('embedding_model', RAG_CONFIG.get('embedding_model', 'nomic-embed-text')),
        'ollama_nlp_model': ollama_nlp_model,
        'ollama_vision_model': ollama_vision_model,
        'gemini_model': GEMINI_CONFIG.get('model', 'gemini-2.5-flash'),
        'gemini_vision_model': vision_settings.get('gemini_vision_model', GEMINI_CONFIG.get('model', 'gemini-2.5-flash'))
    }


def _get_provider_runtime_snapshot() -> Dict[str, Any]:
    """Collect runtime provider diagnostics from NLP + vision modules."""
    nlp_runtime = {
        'provider_order': MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local']),
        'last_provider': None,
        'last_model': None,
        'last_error': None,
        'last_fallback_reason': None,
        'last_completed_at': None,
        'gemini_budget': {
            'enabled': bool(
                float(os.getenv('GEMINI_DAILY_BUDGET_USD', '0') or 0) > 0
                or float(os.getenv('GEMINI_MONTHLY_BUDGET_USD', '0') or 0) > 0
            ),
            'daily_limit_usd': float(os.getenv('GEMINI_DAILY_BUDGET_USD', '0') or 0),
            'monthly_limit_usd': float(os.getenv('GEMINI_MONTHLY_BUDGET_USD', '0') or 0),
            'daily_spend_usd': 0.0,
            'monthly_spend_usd': 0.0,
            'daily_calls': 0,
            'monthly_calls': 0,
            'last_block_reason': None,
            'enforced_max_output_tokens': int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS_PER_REPORT', '900') or 900),
        },
    }

    if report_generator is not None and hasattr(report_generator, 'get_runtime_provider_diagnostics'):
        try:
            nlp_runtime = report_generator.get_runtime_provider_diagnostics() or nlp_runtime
        except Exception as e:
            logger.warning(f"Unable to fetch NLP runtime diagnostics: {e}")

    vision_runtime = {
        'vision_provider_order': [],
        'last_provider_used': None,
        'recent_failures': [],
        'gemini_quota_cooldown_remaining_s': 0,
        'gemini_model': None,
        'ollama_model': None,
        'vision_api_model': None,
    }

    try:
        from caption_image import get_runtime_provider_diagnostics
        payload = get_runtime_provider_diagnostics()
        if isinstance(payload, dict):
            vision_runtime = payload
    except Exception as e:
        logger.warning(f"Unable to fetch vision runtime diagnostics: {e}")

    return {
        'nlp': nlp_runtime,
        'vision': vision_runtime,
    }


def _estimate_remaining_report_capacity(provider_settings: Dict[str, Any], runtime_snapshot: Dict[str, Any], local_diag: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort remaining report capacity estimate for UX visibility."""
    nlp_runtime = runtime_snapshot.get('nlp', {}) if isinstance(runtime_snapshot, dict) else {}
    vision_runtime = runtime_snapshot.get('vision', {}) if isinstance(runtime_snapshot, dict) else {}
    gemini_budget = nlp_runtime.get('gemini_budget', {}) if isinstance(nlp_runtime, dict) else {}

    local_mode_possible = bool((local_diag or {}).get('local_mode_possible'))
    gemini_enabled = bool(provider_settings.get('gemini_enabled', True))
    model_api_enabled = bool(provider_settings.get('model_api_enabled', False))
    nlp_order = [str(p).lower() for p in provider_settings.get('nlp_provider_order', [])]

    nlp_last_error = str(nlp_runtime.get('last_error') or '')
    vision_failures = vision_runtime.get('recent_failures') or []
    gemini_quota_cooldown_remaining = int(vision_runtime.get('gemini_quota_cooldown_remaining_s') or 0)
    daily_limit = float(gemini_budget.get('daily_limit_usd', 0.0) or 0.0)
    monthly_limit = float(gemini_budget.get('monthly_limit_usd', 0.0) or 0.0)
    daily_spend = float(gemini_budget.get('daily_spend_usd', 0.0) or 0.0)
    monthly_spend = float(gemini_budget.get('monthly_spend_usd', 0.0) or 0.0)
    budget_exhausted = (
        (daily_limit > 0 and daily_spend >= daily_limit)
        or (monthly_limit > 0 and monthly_spend >= monthly_limit)
    )
    budget_blocked = 'budget guardrail hit' in nlp_last_error.lower() or bool(gemini_budget.get('last_block_reason'))

    gemini_quota_signals = [
        'quota' in nlp_last_error.lower(),
        'resource_exhausted' in nlp_last_error.lower(),
        gemini_quota_cooldown_remaining > 0,
        any('quota' in str(item.get('reason', '')).lower() for item in vision_failures if isinstance(item, dict)),
    ]
    gemini_likely_limited = any(gemini_quota_signals)

    if local_mode_possible and ('ollama' in nlp_order or 'local' in nlp_order):
        return {
            'estimate_reports_remaining': None,
            'confidence': 'medium',
            'status': 'sustainable',
            'message': 'Local fallback is available; capacity is effectively bounded by local compute rather than API quota.'
        }

    if model_api_enabled and ('model_api' in nlp_order):
        return {
            'estimate_reports_remaining': None,
            'confidence': 'low',
            'status': 'unknown',
            'message': 'Primary model API is enabled; remaining capacity depends on external account quota and cannot be measured precisely from runtime telemetry.'
        }

    if gemini_enabled and (budget_exhausted or budget_blocked):
        if daily_limit > 0 and daily_spend >= daily_limit:
            budget_message = f"Gemini daily budget reached ({daily_spend:.4f}/{daily_limit:.4f} USD)."
        elif monthly_limit > 0 and monthly_spend >= monthly_limit:
            budget_message = f"Gemini monthly budget reached ({monthly_spend:.4f}/{monthly_limit:.4f} USD)."
        else:
            budget_message = 'Gemini budget guardrail is currently blocking new cloud requests.'
        return {
            'estimate_reports_remaining': 0,
            'confidence': 'high',
            'status': 'depleted',
            'message': f"{budget_message} Routing should continue via lower-cost/local fallback providers."
        }

    if gemini_enabled and gemini_likely_limited:
        return {
            'estimate_reports_remaining': 0,
            'confidence': 'medium',
            'status': 'depleted',
            'message': 'Gemini appears quota-limited right now and no durable cloud fallback is currently guaranteed.'
        }

    if gemini_enabled:
        return {
            'estimate_reports_remaining': 5,
            'confidence': 'low',
            'status': 'limited',
            'message': 'Gemini is enabled with no hard quota signal yet; conservative estimate assumes only a small remaining burst on free/shared quota.'
        }

    return {
        'estimate_reports_remaining': 0,
        'confidence': 'medium',
        'status': 'depleted',
        'message': 'No enabled cloud provider is currently visible for report NLP generation.'
    }


@app.route('/api/settings/provider-routing', methods=['GET', 'POST'])
def api_provider_routing_settings():
    """Get or update runtime provider routing settings for NLP/vision/embeddings."""
    global report_generator

    if request.method == 'GET':
        return jsonify(_current_provider_settings())

    try:
        data = request.get_json(silent=True) or {}

        def _to_float(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(default)

        def _to_int(value, default=0):
            try:
                return int(value)
            except (TypeError, ValueError):
                return int(default)

        model_api_enabled = bool(data.get('model_api_enabled', MODEL_API_CONFIG.get('enabled', False)))
        gemini_enabled = bool(data.get('gemini_enabled', GEMINI_CONFIG.get('enabled', True)))
        gemini_daily_budget_usd = max(0.0, _to_float(data.get('gemini_daily_budget_usd', os.getenv('GEMINI_DAILY_BUDGET_USD', '0')), 0.0))
        gemini_monthly_budget_usd = max(0.0, _to_float(data.get('gemini_monthly_budget_usd', os.getenv('GEMINI_MONTHLY_BUDGET_USD', '0')), 0.0))
        gemini_max_output_tokens_per_report = max(1, _to_int(data.get('gemini_max_output_tokens_per_report', os.getenv('GEMINI_MAX_OUTPUT_TOKENS_PER_REPORT', '900')), 900))

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

        requested_local_model = str(
            data.get('ollama_nlp_model')
            or data.get('ollama_vision_model')
            or os.getenv('LOCAL_OLLAMA_UNIFIED_MODEL')
            or LOCAL_OLLAMA_UNIFIED_MODEL
        ).strip()
        if requested_local_model:
            OLLAMA_CONFIG['model'] = requested_local_model
            os.environ['LOCAL_OLLAMA_UNIFIED_MODEL'] = requested_local_model
            os.environ['OLLAMA_MODEL'] = requested_local_model
            os.environ['OLLAMA_VISION_MODEL'] = requested_local_model

        # Persist to environment for module consumers
        os.environ['MODEL_API_ENABLED'] = 'true' if model_api_enabled else 'false'
        os.environ['GEMINI_ENABLED'] = 'true' if gemini_enabled else 'false'
        os.environ['GEMINI_DAILY_BUDGET_USD'] = str(gemini_daily_budget_usd)
        os.environ['GEMINI_MONTHLY_BUDGET_USD'] = str(gemini_monthly_budget_usd)
        os.environ['GEMINI_MAX_OUTPUT_TOKENS_PER_REPORT'] = str(gemini_max_output_tokens_per_report)
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
            os.environ['OLLAMA_VISION_MODEL'] = OLLAMA_CONFIG['model']

        # Update captioning module runtime routing without restart
        try:
            from caption_image import update_runtime_provider_settings
            update_runtime_provider_settings({
                'vision_provider_order': vision_provider_order,
                'vision_model': data.get('vision_model'),
                'gemini_vision_model': data.get('gemini_vision_model'),
                'ollama_vision_model': OLLAMA_CONFIG.get('model')
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
            report_generator.gemini_daily_budget_usd = gemini_daily_budget_usd
            report_generator.gemini_monthly_budget_usd = gemini_monthly_budget_usd
            report_generator.gemini_max_output_tokens_per_report = gemini_max_output_tokens_per_report
            if getattr(report_generator, 'gemini_client', None) is not None:
                report_generator.gemini_client.max_tokens = min(
                    report_generator.gemini_client.max_tokens,
                    gemini_max_output_tokens_per_report
                )

        return jsonify({
            'success': True,
            'message': 'Provider routing settings updated',
            'settings': _current_provider_settings()
        })

    except Exception as e:
        logger.error(f"Error updating provider routing settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/providers/runtime-status', methods=['GET'])
def api_provider_runtime_status():
    """Expose active provider/model, failover reason, and capacity estimate for UX."""
    try:
        settings = _current_provider_settings()
        runtime_snapshot = _get_provider_runtime_snapshot()
        local_diag = _get_local_mode_diagnostics()
        capacity = _estimate_remaining_report_capacity(settings, runtime_snapshot, local_diag)

        return jsonify({
            'success': True,
            'settings': settings,
            'runtime': runtime_snapshot,
            'local': local_diag,
            'capacity': capacity,
        })
    except Exception as e:
        logger.error(f"Error building provider runtime status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/reports/recovery/options', methods=['GET'])
def api_report_recovery_options():
    """Provide quota-recovery options before failover is executed."""
    diagnostics = _get_local_mode_diagnostics()
    candidates = _collect_recovery_candidates(limit=300)
    quota_failed = [c for c in candidates if c.get('status') == 'failed']
    pending_like = [c for c in candidates if c.get('status') in ('pending', 'queued', 'processing', 'generating')]

    return jsonify({
        'success': True,
        'local': diagnostics,
        'counts': {
            'total_candidates': len(candidates),
            'pending_like': len(pending_like),
            'quota_failed': len(quota_failed)
        },
        'current_nlp_provider_order': MODEL_API_CONFIG.get('nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local'])
    })


@app.route('/api/reports/recovery/execute', methods=['POST'])
def api_report_recovery_execute():
    """Run approved recovery action: local-first or failover for pending/quota-failed reports."""
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get('mode') or '').strip().lower()
    if mode not in ('local', 'failover'):
        return jsonify({'success': False, 'error': 'mode must be either "local" or "failover"'}), 400

    if db_manager is None:
        return jsonify({'success': False, 'error': 'Database not available'}), 503
    if violation_queue is None:
        return jsonify({'success': False, 'error': 'Queue is not initialized'}), 503

    if mode == 'local':
        diagnostics = _get_local_mode_diagnostics()
        if not diagnostics.get('local_mode_possible'):
            return jsonify({
                'success': False,
                'error': 'Local mode is not currently feasible on this backend host.',
                'local': diagnostics
            }), 400

    if not ensure_queue_worker_running():
        return jsonify({'success': False, 'error': 'Queue worker is not running'}), 503

    selected_order = ['local', 'ollama', 'model_api', 'gemini'] if mode == 'local' else ['model_api', 'ollama', 'local', 'gemini']
    applied_order = _apply_nlp_provider_order(selected_order)

    candidates = _collect_recovery_candidates(limit=300)
    requested_report_ids = payload.get('report_ids')
    if isinstance(requested_report_ids, list) and requested_report_ids:
        requested_set = {str(r).strip() for r in requested_report_ids if str(r).strip()}
        candidates = [c for c in candidates if c.get('report_id') in requested_set]

    enqueued_count = 0
    skipped_count = 0
    errors = []

    for item in candidates:
        report_id = item.get('report_id')
        try:
            event = db_manager.get_detection_event(report_id) if hasattr(db_manager, 'get_detection_event') else None
            violation_dir = VIOLATIONS_DIR.absolute() / report_id
            original_path = violation_dir / 'original.jpg'
            annotated_path = violation_dir / 'annotated.jpg'

            if not original_path.exists() or event is None:
                skipped_count += 1
                continue

            detections = []
            violation = db_manager.get_violation(report_id) if hasattr(db_manager, 'get_violation') else None
            if violation and isinstance(violation.get('detection_data'), dict):
                detections = violation['detection_data'].get('detections', []) or []

            violation_summary_text = (violation or {}).get('violation_summary') if isinstance(violation, dict) else ''
            violation_types, resolved_violation_count = _resolve_violation_types_and_count(
                detections,
                event=event,
                violation_summary=violation_summary_text,
                fallback_count=event.get('violation_count') if isinstance(event, dict) else None,
            )

            if not annotated_path.exists():
                try:
                    frame = cv2.imread(str(original_path))
                    if frame is not None:
                        _, annotated = predict_image(frame, conf=0.25)
                        cv2.imwrite(str(annotated_path), annotated)
                except Exception:
                    pass

            violation_data = {
                'report_id': report_id,
                'timestamp': event.get('timestamp').isoformat() if event.get('timestamp') else datetime.now().isoformat(),
                'detections': detections,
                'violation_types': violation_types,
                'violation_count': resolved_violation_count,
                'original_image_path': str(original_path),
                'annotated_image_path': str(annotated_path),
                'violation_dir': str(violation_dir)
            }

            enqueued = violation_queue.enqueue(
                violation_data=violation_data,
                device_id=(event.get('device_id') if isinstance(event, dict) else None) or 'recovery_pipeline',
                report_id=report_id,
                severity='CRITICAL'
            )

            if not enqueued:
                skipped_count += 1
                continue

            db_manager.update_detection_status(report_id, 'pending')
            enqueued_count += 1

        except Exception as e:
            errors.append(f"{report_id}: {e}")
            skipped_count += 1

    return jsonify({
        'success': True,
        'mode': mode,
        'applied_nlp_provider_order': applied_order,
        'total_candidates': len(candidates),
        'enqueued': enqueued_count,
        'skipped': skipped_count,
        'errors': errors[:10],
        'worker_running': _is_queue_worker_alive()
    })


@app.route('/api/reports/sync-local-cache', methods=['POST'])
def api_sync_local_cache_to_supabase():
    """Scan local violation folders and enqueue unsynced items for Supabase reconciliation."""
    payload = request.get_json(silent=True) or {}
    max_items = int(payload.get('limit', 120) or 120)
    max_items = max(1, min(max_items, 500))
    dry_run = bool(payload.get('dry_run', False))

    if db_manager is None:
        return jsonify({'success': False, 'error': 'Database manager unavailable'}), 503
    if storage_manager is None:
        return jsonify({'success': False, 'error': 'Storage manager unavailable'}), 503
    if violation_queue is None:
        return jsonify({'success': False, 'error': 'Queue is not initialized'}), 503
    if not dry_run and not ensure_queue_worker_running():
        return jsonify({'success': False, 'error': 'Queue worker is not running'}), 503

    local_dirs = []
    if VIOLATIONS_DIR.exists():
        for violation_dir in sorted(VIOLATIONS_DIR.iterdir(), reverse=True):
            if violation_dir.is_dir():
                local_dirs.append(violation_dir)
            if len(local_dirs) >= max_items:
                break

    scanned = 0
    enqueued = 0
    skipped = 0
    candidates = 0
    errors = []

    for violation_dir in local_dirs:
        scanned += 1
        report_id = violation_dir.name
        original_path = violation_dir / 'original.jpg'
        annotated_path = violation_dir / 'annotated.jpg'
        report_html_path = violation_dir / 'report.html'

        if not original_path.exists():
            skipped += 1
            continue

        try:
            event = db_manager.get_detection_event(report_id) if hasattr(db_manager, 'get_detection_event') else None
            violation = db_manager.get_violation(report_id) if hasattr(db_manager, 'get_violation') else None
        except Exception as lookup_err:
            errors.append(f"{report_id}: lookup failed ({lookup_err})")
            skipped += 1
            continue

        has_cloud_original = bool((violation or {}).get('original_image_key'))
        has_cloud_annotated = bool((violation or {}).get('annotated_image_key'))
        has_cloud_report = bool((violation or {}).get('report_html_key'))
        local_has_report = report_html_path.exists()

        needs_sync = (
            not event or
            not has_cloud_original or
            (annotated_path.exists() and not has_cloud_annotated) or
            (local_has_report and not has_cloud_report)
        )

        if not needs_sync:
            skipped += 1
            continue

        candidates += 1

        if dry_run:
            continue

        detections = []
        detection_data = (violation or {}).get('detection_data') if isinstance(violation, dict) else None
        if isinstance(detection_data, dict):
            detections = detection_data.get('detections', []) or []

        if not annotated_path.exists():
            try:
                frame = cv2.imread(str(original_path))
                if frame is not None:
                    _, annotated = predict_image(frame, conf=0.25)
                    cv2.imwrite(str(annotated_path), annotated)
            except Exception:
                pass

        ts_value = None
        if event and event.get('timestamp'):
            ts = event.get('timestamp')
            ts_value = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
        else:
            try:
                ts_obj = datetime.strptime(report_id, '%Y%m%d_%H%M%S')
                ts_value = ts_obj.isoformat()
            except Exception:
                ts_value = datetime.now().isoformat()

        violation_summary_text = (violation or {}).get('violation_summary') if isinstance(violation, dict) else ''
        violation_types, resolved_violation_count = _resolve_violation_types_and_count(
            detections,
            event=event,
            violation_summary=violation_summary_text,
            fallback_count=event.get('violation_count') if isinstance(event, dict) else None,
        )

        violation_data = {
            'report_id': report_id,
            'timestamp': ts_value,
            'detections': detections,
            'violation_types': violation_types,
            'violation_count': resolved_violation_count,
            'original_image_path': str(original_path),
            'annotated_image_path': str(annotated_path if annotated_path.exists() else original_path),
            'violation_dir': str(violation_dir)
        }

        try:
            if not event and hasattr(db_manager, 'insert_detection_event'):
                db_manager.insert_detection_event(
                    report_id=report_id,
                    timestamp=ts_value,
                    person_count=0,
                    violation_count=max(1, violation_data['violation_count']),
                    severity='HIGH',
                    status='pending'
                )

            queued = violation_queue.enqueue(
                violation_data=violation_data,
                device_id=(event.get('device_id') if isinstance(event, dict) else None) or 'local_cache_sync',
                report_id=report_id,
                severity='HIGH'
            )

            if not queued:
                skipped += 1
                continue

            if hasattr(db_manager, 'update_detection_status'):
                db_manager.update_detection_status(report_id, 'pending', 'Queued for local-cache reconciliation to Supabase')

            enqueued += 1
        except Exception as enqueue_err:
            errors.append(f"{report_id}: enqueue failed ({enqueue_err})")
            skipped += 1

    return jsonify({
        'success': True,
        'dry_run': dry_run,
        'scanned': scanned,
        'candidates': candidates,
        'enqueued': enqueued,
        'skipped': skipped,
        'errors': errors[:20],
        'worker_running': _is_queue_worker_alive() if not dry_run else bool(violation_queue is not None)
    })


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

        if current_status in ('pending', 'queued', 'processing', 'generating') and not force_reprocess:
            queue_stats = violation_queue.get_stats()
            return jsonify({
                'success': True,
                'message': 'Report is already queued or generating',
                'already_queued': True,
                'report_id': report_id,
                'queue_size': queue_stats.get('current_size', 0),
                'worker_running': _is_queue_worker_alive()
            })

        violation_dir = VIOLATIONS_DIR.absolute() / report_id
        original_path = violation_dir / 'original.jpg'
        annotated_path = violation_dir / 'annotated.jpg'

        violation = db_manager.get_violation(report_id)

        if not original_path.exists() and storage_manager is not None and isinstance(violation, dict):
            try:
                original_key = violation.get('original_image_key')
                if original_key:
                    blob = storage_manager.download_file_content(original_key)
                    if blob:
                        violation_dir.mkdir(parents=True, exist_ok=True)
                        if isinstance(blob, str):
                            blob = blob.encode('utf-8')
                        original_path.write_bytes(blob)
                        logger.info(f"Recovered original image from Supabase for report {report_id}")
            except Exception as recover_err:
                logger.warning(f"Could not recover original image from Supabase for {report_id}: {recover_err}")

        if not original_path.exists():
            return jsonify({
                'success': False,
                'error': 'Original image is missing for this report. Cannot regenerate locally.'
            }), 400

        detections = []
        violation_types = []

        if violation and isinstance(violation.get('detection_data'), dict):
            detections = violation['detection_data'].get('detections', []) or []

        violation_summary_text = violation.get('violation_summary') if isinstance(violation, dict) else ''
        violation_types, resolved_violation_count = _resolve_violation_types_and_count(
            detections,
            event=event,
            violation_summary=violation_summary_text,
            fallback_count=event.get('violation_count') if isinstance(event, dict) else None,
        )

        if not annotated_path.exists():
            try:
                frame = cv2.imread(str(original_path))
                if frame is not None:
                    _, annotated = predict_image(frame, conf=0.25)
                    cv2.imwrite(str(annotated_path), annotated)
            except Exception as annotate_err:
                logger.warning(f"Could not regenerate annotated image for {report_id}: {annotate_err}")

        if not ensure_queue_worker_running():
            return jsonify({'success': False, 'error': 'Queue worker is not running'}), 503

        violation_data = {
            'report_id': report_id,
            'timestamp': event.get('timestamp').isoformat() if event.get('timestamp') else datetime.now().isoformat(),
            'detections': detections,
            'violation_types': violation_types,
            'violation_count': resolved_violation_count,
            'original_image_path': str(original_path),
            'annotated_image_path': str(annotated_path),
            'violation_dir': str(violation_dir)
        }

        enqueued = violation_queue.enqueue(
            violation_data=violation_data,
            device_id=event.get('device_id') or f'manual_regenerate_{report_id}',
            report_id=report_id,
            severity='CRITICAL'
        )

        if not enqueued:
            queue_stats = violation_queue.get_stats()
            return jsonify({
                'success': False,
                'error': 'Could not enqueue report (queue full or rate limited)',
                'queue_size': queue_stats.get('current_size', 0),
                'queue_capacity': queue_stats.get('capacity', 100),
                'worker_running': _is_queue_worker_alive()
            }), 409

        db_manager.update_detection_status(report_id, 'pending')

        queue_stats = violation_queue.get_stats()
        return jsonify({
            'success': True,
            'message': 'Report moved to the front of queue for generation' + (' (reprocess mode)' if force_reprocess else ''),
            'report_id': report_id,
            'force_reprocess': force_reprocess,
            'queue_size': queue_stats.get('current_size', 0),
            'worker_running': _is_queue_worker_alive()
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

        if not failed_view:
            cached_rendered = _get_cached_rendered_report_html(report_id, report_html_key)
            if cached_rendered:
                return cached_rendered, 200, {
                    'Content-Type': 'text/html; charset=utf-8',
                    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
        
        # Download the HTML content and render it
        try:
            html_content = _get_cached_report_html_content(report_id, report_html_key)
            if html_content is None:
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

            _set_cached_report_html_content(report_id, report_html_key, html_content)
            
            # Return the HTML content directly so browser renders it
            trace_payload = _build_traceability_payload(
                report_id=report_id,
                violation=violation or {},
                event=event or {},
                source='supabase_storage',
                failed_view_requested=failed_view,
            )
            html_content = _repair_report_documentation_block(html_content, report_id)
            html_content = _normalize_report_footer_branding(html_content)
            html_content = _inject_traceability_widget(html_content, trace_payload)
            if not failed_view:
                _set_cached_rendered_report_html(report_id, report_html_key, html_content)
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


def _extract_generation_model_info(detection_data: Dict[str, Any], nlp_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve best-effort model/provider provenance for caption + report generation."""
        detection_data = detection_data if isinstance(detection_data, dict) else {}
        nlp_analysis = nlp_analysis if isinstance(nlp_analysis, dict) else {}

        caption_provider = None
        caption_model = None
        caption_source = None

        history = detection_data.get('caption_history')
        if isinstance(history, list):
            history_entries = [entry for entry in history if isinstance(entry, dict)]
            if history_entries:
                latest = history_entries[-1]
                model_from_history = latest.get('model')
                if model_from_history:
                    caption_model = str(model_from_history)
                    caption_provider = str(latest.get('provider') or 'historical_record')
                    caption_source = 'detection_data.caption_history[-1]'

        if caption_model is None:
            for model_key in ('caption_model', 'vision_model', 'generation_model', 'model_used'):
                value = detection_data.get(model_key)
                if value:
                    caption_model = str(value)
                    caption_source = f'detection_data.{model_key}'
                    break

        if caption_provider is None:
            for provider_key in ('caption_provider', 'vision_provider', 'generation_provider', 'provider_used'):
                value = detection_data.get(provider_key)
                if value:
                    caption_provider = str(value)
                    caption_source = caption_source or f'detection_data.{provider_key}'
                    break

        report_provider = None
        report_model = None
        report_source = None

        for provider_key in ('provider', 'generation_provider', 'report_provider', 'model_provider'):
            value = nlp_analysis.get(provider_key)
            if value:
                report_provider = str(value)
                report_source = f'nlp_analysis.{provider_key}'
                break

        for model_key in ('model', 'generation_model', 'report_model', 'model_used'):
            value = nlp_analysis.get(model_key)
            if value:
                report_model = str(value)
                report_source = report_source or f'nlp_analysis.{model_key}'
                break

        runtime_snapshot = _get_provider_runtime_snapshot()
        nlp_runtime = runtime_snapshot.get('nlp', {}) if isinstance(runtime_snapshot, dict) else {}
        vision_runtime = runtime_snapshot.get('vision', {}) if isinstance(runtime_snapshot, dict) else {}

        if report_provider is None and isinstance(nlp_runtime, dict):
            if nlp_runtime.get('last_provider'):
                report_provider = str(nlp_runtime.get('last_provider'))
                report_source = 'runtime.nlp.last_provider'

        if report_model is None and isinstance(nlp_runtime, dict):
            if nlp_runtime.get('last_model'):
                report_model = str(nlp_runtime.get('last_model'))
                report_source = report_source or 'runtime.nlp.last_model'

        if caption_provider is None and isinstance(vision_runtime, dict):
            if vision_runtime.get('last_provider_used'):
                caption_provider = str(vision_runtime.get('last_provider_used'))
                caption_source = 'runtime.vision.last_provider_used'

        if caption_model is None and isinstance(vision_runtime, dict):
            provider_key = (caption_provider or '').strip().lower()
            provider_to_model = {
                'gemini': vision_runtime.get('gemini_model'),
                'ollama': vision_runtime.get('ollama_model'),
                'model_api': vision_runtime.get('vision_api_model'),
            }
            inferred_model = provider_to_model.get(provider_key) or vision_runtime.get('vision_api_model')
            if inferred_model:
                caption_model = str(inferred_model)
                caption_source = caption_source or 'runtime.vision.provider_model_map'

        return {
            'caption_generation': {
                'provider': caption_provider,
                'model': caption_model,
                'source': caption_source,
            },
            'report_generation': {
                'provider': report_provider,
                'model': report_model,
                'source': report_source,
            },
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
            or f'ollama pull {LOCAL_OLLAMA_UNIFIED_MODEL}'.lower() in lowered
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
        nlp_integrity = detection_data.get('nlp_integrity') if isinstance(detection_data, dict) else None
        nlp_analysis = _safe_parse_json_like(violation.get('nlp_analysis'))
        generation_models = _extract_generation_model_info(detection_data, nlp_analysis)

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
                'nlp_integrity': nlp_integrity,
                'generation_models': generation_models,
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
        position: fixed !important;
        top: 8px !important;
        left: 8px !important;
        right: auto !important;
        bottom: auto !important;
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
        transform: none !important;
        transition: background 0.15s ease;
    }}
    .report-back-btn:hover {{
        background: #374151;
    }}
    .traceability-widget {{
        position: fixed !important;
        top: 8px !important;
        right: 8px !important;
        left: auto !important;
        bottom: auto !important;
        z-index: 2147483647;
        font-family: Consolas, 'Courier New', monospace;
        transform: none !important;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
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
        transform: none !important;
        transition: background 0.15s ease;
    }}
    .traceability-toggle:hover {{
        background: #fbbf24;
        transform: none !important;
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
            if (window.opener && !window.opener.closed) {{
                try {{
                    window.opener.focus();
                    window.close();
                    return;
                }} catch (e) {{
                    // Fall through to local navigation when opener is not accessible.
                }}
            }}

            // Try closing current tab even without opener (works only if browser permits).
            window.close();
            if (window.closed) return;

            if (window.history.length > 1) {{
                window.history.back();
                return;
            }}

            // Final fallback: stay on the report page (avoid forcing homepage redirect).
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


def _normalize_report_footer_branding(html_content: str) -> str:
        """Normalize legacy footer branding text so older generated reports match current UI branding."""
        if not html_content:
            return html_content

        replacements = (
            (
                'PPE Safety Monitor - AI-Powered Workplace Safety System',
                'CASM PPE Safety Monitor - FYPA AI Model Development & Integration',
            ),
            (
                'Powered by YOLOv8 • LLaVA • Llama3 • Computer Vision',
                'Powered by YOLO PPE Detection • Local + Cloud AI Routing • Supabase-backed Report Pipeline',
            ),
            (
                'This NCR was auto-generated by CASM PPE Safety Monitor System',
                'This NCR was auto-generated by CASM PPE Safety Monitor - FYPA AI Model Development & Integration',
            ),
        )

        normalized = html_content
        for source_text, replacement_text in replacements:
            normalized = normalized.replace(source_text, replacement_text)

        return normalized


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
        html_content = _normalize_report_footer_branding(html_content)
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

def generate_frames(conf=0.25, target_fps=14, jpeg_quality=72):
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
    
    frame_interval = 1.0 / max(1, int(target_fps))
    last_yield_ts = 0.0

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
                violation_detections = _extract_violation_detections(detections) if detections else []

                # Keep a persistent on-frame status HUD so users always see live YOLO state,
                # even when there are no current violation boxes.
                cv2.rectangle(annotated, (10, 10), (390, 72), (0, 0, 0), -1)
                cv2.putText(
                    annotated,
                    f"YOLO active | detections: {len(detections)}",
                    (18, 36),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.62,
                    (80, 255, 120),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    annotated,
                    f"violations: {len(violation_detections)}",
                    (18, 62),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.56,
                    (0, 220, 255),
                    2,
                    cv2.LINE_AA,
                )
                
                # Log all detections for debugging
                if detections:
                    detected_classes = [d['class_name'] for d in detections]
                    logger.debug(f"Detected: {detected_classes}")
                
                # Check for violations in background thread (non-blocking)
                if detections and FULL_PIPELINE_AVAILABLE:
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
                        
                        report_id = enqueue_violation(frame_copy, detections_copy, trigger_source='live')
                        if report_id:
                            logger.info(f"✓ Violation {report_id} queued for processing")
                        else:
                            logger.debug("Violation not queued (cooldown or already processing)")
                
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
                if not ret:
                    continue
                
                # Pace stream frames to keep latency predictable on slower machines/networks.
                now = time.monotonic()
                wait_s = frame_interval - (now - last_yield_ts)
                if wait_s > 0:
                    time.sleep(wait_s)

                frame_bytes = buffer.tobytes()
                
                # Yield frame in multipart format
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                last_yield_ts = time.monotonic()
                
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

    def _to_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    conf = max(0.01, min(0.90, _to_float(request.args.get('conf', 0.10), 0.10)))
    target_fps = int(max(5, min(30, _to_float(request.args.get('fps', 14), 14))))
    jpeg_quality = int(max(45, min(90, _to_float(request.args.get('quality', 72), 72))))

    return Response(
        generate_frames(conf=conf, target_fps=target_fps, jpeg_quality=jpeg_quality),
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
    requested_camera_index = payload.get('camera_index')
    if requested_camera_index is not None:
        try:
            requested_camera_index = int(requested_camera_index)
        except (TypeError, ValueError):
            requested_camera_index = None

    with camera_lock:
        result = _start_live_source_locked(requested_source, requested_camera_index)

    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('message', 'Failed to start live monitoring')}), 500

    response = {
        'success': True,
        'source': result.get('source', 'webcam'),
        'camera_index': result.get('camera_index'),
        'fallback_to_webcam': bool(result.get('fallback_to_webcam')),
        'message': result.get('message', 'Live monitoring started')
    }

    state_payload = _build_live_state_payload()
    response['realsense_available'] = state_payload.get('realsense_available', False)
    response['realsense_device_name'] = state_payload.get('realsense_device_name')
    response['realsense_capabilities'] = state_payload.get('realsense_capabilities', {})
    response['edge_realsense_available'] = state_payload.get('edge_realsense_available', False)
    response['edge_realsense_device_name'] = state_payload.get('edge_realsense_device_name')
    response['edge_realsense_age_ms'] = state_payload.get('edge_realsense_age_ms')
    response['edge_realsense_capabilities'] = state_payload.get('edge_realsense_capabilities', {})

    if response['source'] == 'webcam':
        response['webcam_devices'] = state_payload.get('webcam_devices', [])

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


@app.route('/api/live/edge/realsense/frame', methods=['POST'])
def ingest_edge_realsense_frame():
    """Ingest a local-machine RealSense frame/depth payload for hosted live streaming."""
    if not _is_edge_ingest_authorized():
        return jsonify({'success': False, 'error': 'Unauthorized edge ingest token'}), 401

    frame_file = request.files.get('frame') or request.files.get('image')
    if frame_file is None:
        return jsonify({'success': False, 'error': 'No frame/image file provided'}), 400

    try:
        raw_bytes = frame_file.read()
        nparr = np.frombuffer(raw_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Invalid frame payload: {exc}'}), 400

    if frame is None:
        return jsonify({'success': False, 'error': 'Invalid frame image format'}), 400

    def _parse_json_field(field_name: str):
        raw_value = request.form.get(field_name)
        if not raw_value:
            return None

        raw_text = str(raw_value).strip()
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            # Some shell form uploads escape quotes (e.g. {\"key\":\"value\"}).
            try:
                unescaped = raw_text.encode('utf-8').decode('unicode_escape')
                parsed = json.loads(unescaped)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
        return None

    device_name = (request.form.get('device_name') or 'Intel RealSense (Edge Relay)').strip()
    depth_telemetry = _parse_json_field('depth_telemetry')
    capabilities = _parse_json_field('capabilities')

    depth_preview_file = request.files.get('depth_preview')
    depth_preview_bytes = None
    if depth_preview_file is not None:
        try:
            depth_preview_bytes = depth_preview_file.read()
        except Exception:
            depth_preview_bytes = None

    with camera_lock:
        edge_snapshot = live_source_adapter.ingest_edge_realsense_locked(
            frame,
            device_name=device_name,
            depth_telemetry=depth_telemetry,
            depth_preview_jpeg=depth_preview_bytes,
            capabilities=capabilities,
        )

    return jsonify({'success': True, **edge_snapshot})


@app.route('/api/live/edge/realsense/status')
def edge_realsense_status():
    """Return current edge RealSense relay status for UI/source selection."""
    payload = _build_live_state_payload()
    return jsonify({
        'success': True,
        'source': payload.get('source'),
        'active': payload.get('active'),
        'default_source': payload.get('default_source'),
        'edge_realsense_available': payload.get('edge_realsense_available', False),
        'edge_realsense_device_name': payload.get('edge_realsense_device_name'),
        'edge_realsense_age_ms': payload.get('edge_realsense_age_ms'),
        'edge_realsense_capabilities': payload.get('edge_realsense_capabilities', {}),
    })


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
            queued_report_id = enqueue_violation(frame_copy, detections_copy, trigger_source='upload')
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


@app.route('/api/inference/live-frame', methods=['POST'])
def live_frame_inference():
    """Low-latency near-edge inference path for browser-owned live camera frames (phone/web)."""
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No image selected'}), 400

    try:
        img_bytes = file.read()
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({'error': 'Invalid image format'}), 400

        conf = float(request.form.get('conf', 0.10))
        detections, _annotated = predict_image(frame, conf=conf)

        violation_detections = _extract_violation_detections(detections)
        report_queued = False
        report_queue_reason = None
        queued_report_id = None

        if violation_detections and FULL_PIPELINE_AVAILABLE:
            frame_copy = frame.copy()
            detections_copy = detections.copy()
            # Treat browser-submitted live frames as live source so dedup logic applies.
            queued_report_id = enqueue_violation(frame_copy, detections_copy, trigger_source='live')
            report_queued = queued_report_id is not None
            if not report_queued:
                report_queue_reason = 'cooldown_or_dedup_or_already_processing'
        elif violation_detections and not FULL_PIPELINE_AVAILABLE:
            report_queue_reason = 'pipeline_components_unavailable'

        return jsonify({
            'success': True,
            'source': 'near_edge_live_frame',
            'detections': detections,
            'count': len(detections),
            'violations_detected': len(violation_detections) > 0,
            'violation_count': len(violation_detections),
            'report_queued': report_queued,
            'report_queue_reason': report_queue_reason,
            'report_id': queued_report_id
        })

    except Exception as e:
        logger.error(f"Live-frame inference error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/testing/live-dedup/probe', methods=['POST'])
def api_live_dedup_probe():
    """
    Deterministic test probe for live dedup behavior without requiring camera hardware.

    This endpoint simulates repeated live violations with identical spatial signatures.
    Expected behavior:
      - first trigger queues a report
      - subsequent identical triggers are blocked by live dedup
    """
    startup_gate = _startup_gate_response()
    if startup_gate is not None:
        return startup_gate

    # Safety default: keep synthetic testing endpoints disabled unless explicitly enabled.
    if not ENABLE_TESTING_ENDPOINTS:
        return jsonify({
            'success': False,
            'error': 'testing_endpoints_disabled',
            'hint': 'Set ENABLE_TESTING_ENDPOINTS=true only in non-production environments.'
        }), 403

    if not FULL_PIPELINE_AVAILABLE:
        return jsonify({'success': False, 'error': 'pipeline_components_unavailable'}), 503

    try:
        payload = request.get_json(silent=True) or {}
        repeats = int(payload.get('repeats', 4))
        repeats = max(2, min(repeats, 12))

        bbox = payload.get('bbox') or [120, 90, 310, 430]
        if not isinstance(bbox, list) or len(bbox) != 4:
            bbox = [120, 90, 310, 430]

        # Reset recent signatures for deterministic probe behavior.
        with recent_live_violation_lock:
            recent_live_violation_signatures.clear()

        global last_violation_time, VIOLATION_COOLDOWN
        previous_cooldown = VIOLATION_COOLDOWN
        previous_last_violation_time = last_violation_time

        # Disable short capture cooldown for this test so dedup logic is what blocks repeats.
        VIOLATION_COOLDOWN = 0
        last_violation_time = 0

        accepted_report_ids = []
        blocked_count = 0

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        detections = [{
            'class_name': 'NO-Hardhat',
            'confidence': 0.95,
            'score': 0.95,
            'bbox': bbox
        }]

        try:
            for _ in range(repeats):
                rid = enqueue_violation(frame.copy(), detections.copy(), trigger_source='live')
                if rid:
                    accepted_report_ids.append(str(rid))
                else:
                    blocked_count += 1
        finally:
            VIOLATION_COOLDOWN = previous_cooldown
            last_violation_time = previous_last_violation_time

        return jsonify({
            'success': True,
            'repeats': repeats,
            'accepted_count': len(accepted_report_ids),
            'accepted_report_ids': accepted_report_ids,
            'blocked_count': blocked_count,
            'dedup_window_seconds': LIVE_VIOLATION_DEDUP_WINDOW_SECONDS,
        })
    except Exception as e:
        logger.error(f"Live dedup probe error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
            'worker_running': _is_queue_worker_alive(),
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
# ZERO-TOUCH DEVICE PROVISIONING & NOTIFICATIONS
# =========================================================================

PENDING_DEVICES_FILE = Path('pending_devices.json')
BOOTSTRAP_TOKEN_STATE_FILE = Path('bootstrap_tokens.json')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
PROVISION_EXCHANGE_TOKEN_TTL_SECONDS = int(os.getenv('PROVISION_EXCHANGE_TOKEN_TTL_SECONDS', '300'))
INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS = int(os.getenv('INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS', '600'))
BOOTSTRAP_JTI_RETENTION_SECONDS = int(os.getenv('BOOTSTRAP_JTI_RETENTION_SECONDS', '86400'))
DEFAULT_INSTALLER_REPO_ZIP_URL = (
    'https://github.com/FrankieLingIsHere/FYPA_AI_Model_Development-Integration/archive/refs/heads/main.zip'
)
DEFAULT_INSTALLER_SOURCE_ROOT = 'FYPA_AI_Model_Development-Integration-main'


def _safe_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer env var with bounds and fallback."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


PROVISION_EXCHANGE_TOKEN_TTL_SECONDS = _safe_int_env(
    'PROVISION_EXCHANGE_TOKEN_TTL_SECONDS',
    PROVISION_EXCHANGE_TOKEN_TTL_SECONDS,
    30,
    3600,
)
INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS = _safe_int_env(
    'INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS',
    INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS,
    30,
    3600,
)
BOOTSTRAP_JTI_RETENTION_SECONDS = _safe_int_env(
    'BOOTSTRAP_JTI_RETENTION_SECONDS',
    BOOTSTRAP_JTI_RETENTION_SECONDS,
    300,
    7 * 24 * 3600,
)


def _normalize_pending_device_record(raw_record: Any) -> Dict[str, Any]:
    """Ensure expected keys exist for backward-compatible pending-device records."""
    if not isinstance(raw_record, dict):
        return {
            'status': 'pending',
            'requested_at': datetime.now(timezone.utc).isoformat(),
            'token': '',
            'provision_secret_hash': '',
            'approved_at': None,
            'provisioned_at': None,
        }

    normalized = dict(raw_record)
    normalized.setdefault('status', 'pending')
    normalized.setdefault('requested_at', datetime.now(timezone.utc).isoformat())
    normalized.setdefault('token', '')
    normalized.setdefault('provision_secret_hash', '')
    normalized.setdefault('approved_at', None)
    normalized.setdefault('provisioned_at', None)
    return normalized


def _load_pending_devices() -> Dict[str, Dict[str, Any]]:
    if not PENDING_DEVICES_FILE.exists():
        return {}
    try:
        with open(PENDING_DEVICES_FILE, 'r') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {
                str(machine_id): _normalize_pending_device_record(record)
                for machine_id, record in data.items()
            }
    except Exception:
        return {}


def _save_pending_devices(data: Dict[str, Dict[str, Any]]) -> None:
    with open(PENDING_DEVICES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def _load_bootstrap_token_state() -> Dict[str, Dict[str, str]]:
    if not BOOTSTRAP_TOKEN_STATE_FILE.exists():
        return {'used_jti': {}}
    try:
        with open(BOOTSTRAP_TOKEN_STATE_FILE, 'r') as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return {'used_jti': {}}
        used = state.get('used_jti')
        if not isinstance(used, dict):
            used = {}
        return {'used_jti': used}
    except Exception:
        return {'used_jti': {}}


def _save_bootstrap_token_state(state: Dict[str, Dict[str, str]]) -> None:
    with open(BOOTSTRAP_TOKEN_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def _prune_bootstrap_jti_state(state: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    used = state.get('used_jti') or {}
    if not isinstance(used, dict):
        return {'used_jti': {}}

    now_epoch = time.time()
    retained: Dict[str, str] = {}
    for jti, used_at_iso in used.items():
        try:
            used_epoch = datetime.fromisoformat(str(used_at_iso)).timestamp()
        except Exception:
            continue
        if (now_epoch - used_epoch) <= BOOTSTRAP_JTI_RETENTION_SECONDS:
            retained[jti] = str(used_at_iso)
    return {'used_jti': retained}


def _is_bootstrap_jti_used(jti: str) -> bool:
    state = _load_bootstrap_token_state()
    state = _prune_bootstrap_jti_state(state)
    _save_bootstrap_token_state(state)
    return jti in (state.get('used_jti') or {})


def _mark_bootstrap_jti_used(jti: str) -> None:
    state = _load_bootstrap_token_state()
    state = _prune_bootstrap_jti_state(state)
    state.setdefault('used_jti', {})[jti] = datetime.now(timezone.utc).isoformat()
    _save_bootstrap_token_state(state)


def _get_bootstrap_signing_secret() -> str:
    configured = os.getenv('BOOTSTRAP_TOKEN_SECRET', '').strip()
    if configured:
        return configured

    fallback = (os.getenv('FLASK_SECRET_KEY', '').strip() or ADMIN_PASSWORD.strip())
    if fallback:
        return fallback

    # This fallback keeps local development functional, but should never be used in production.
    logger.warning('BOOTSTRAP_TOKEN_SECRET is not set; using insecure fallback secret')
    return 'luna-insecure-bootstrap-secret'


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('utf-8').rstrip('=')


def _b64url_decode(value: str) -> bytes:
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _hash_provision_secret(secret_value: str) -> str:
    return hashlib.sha256(secret_value.encode('utf-8')).hexdigest()


def _is_valid_provision_secret(device: Dict[str, Any], supplied_secret: str) -> bool:
    expected_hash = str(device.get('provision_secret_hash') or '').strip()
    supplied_secret = str(supplied_secret or '').strip()
    if not expected_hash or not supplied_secret:
        return False
    supplied_hash = _hash_provision_secret(supplied_secret)
    return hmac.compare_digest(expected_hash, supplied_hash)


def _issue_bootstrap_token(machine_id: str, purpose: str, ttl_seconds: int) -> str:
    now_epoch = int(time.time())
    payload = {
        'machine_id': machine_id,
        'purpose': purpose,
        'iat': now_epoch,
        'exp': now_epoch + max(30, int(ttl_seconds)),
        'jti': secrets.token_urlsafe(18),
        'one_time': True,
    }
    payload_blob = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    payload_part = _b64url_encode(payload_blob)
    signature = hmac.new(
        _get_bootstrap_signing_secret().encode('utf-8'),
        payload_part.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    signature_part = _b64url_encode(signature)
    return f"{payload_part}.{signature_part}"


def _verify_bootstrap_token(
    token: str,
    expected_purpose: str,
    expected_machine_id: Optional[str] = None,
    consume: bool = False,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    token = str(token or '').strip()
    if '.' not in token:
        return False, None, 'Invalid token format'

    payload_part, signature_part = token.split('.', 1)
    expected_signature = hmac.new(
        _get_bootstrap_signing_secret().encode('utf-8'),
        payload_part.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    expected_signature_part = _b64url_encode(expected_signature)
    if not hmac.compare_digest(signature_part, expected_signature_part):
        return False, None, 'Invalid token signature'

    try:
        payload = json.loads(_b64url_decode(payload_part).decode('utf-8'))
    except Exception:
        return False, None, 'Invalid token payload'

    if str(payload.get('purpose') or '') != expected_purpose:
        return False, None, 'Token purpose mismatch'

    if expected_machine_id and str(payload.get('machine_id') or '') != str(expected_machine_id):
        return False, None, 'Token machine mismatch'

    now_epoch = int(time.time())
    try:
        exp_epoch = int(payload.get('exp'))
    except (TypeError, ValueError):
        return False, None, 'Token expiration is missing'

    if exp_epoch <= now_epoch:
        return False, None, 'Token expired'

    jti = str(payload.get('jti') or '').strip()
    if not jti:
        return False, None, 'Token identifier is missing'

    if payload.get('one_time', True):
        if _is_bootstrap_jti_used(jti):
            return False, None, 'Token already used'
        if consume:
            _mark_bootstrap_jti_used(jti)

    return True, payload, ''


def _get_provision_secret_from_request() -> str:
    return (
        request.args.get('provision_secret')
        or request.headers.get('X-Provision-Secret')
        or ''
    ).strip()


def _issue_installer_redirect(machine_id: str) -> Response:
    installer_token = _issue_bootstrap_token(
        machine_id,
        'installer_download',
        INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS,
    )
    return redirect(f"/api/bootstrap/installer?token={quote(installer_token)}")


def _sanitize_batch_template_value(raw_value: str) -> str:
    """Remove newlines from values before injecting into batch templates."""
    return str(raw_value or '').replace('\r', '').replace('\n', '').strip()


def _resolve_installer_template_context() -> Dict[str, str]:
    repo_zip_url = _sanitize_batch_template_value(
        os.getenv('INSTALLER_REPO_ZIP_URL', DEFAULT_INSTALLER_REPO_ZIP_URL)
    ) or DEFAULT_INSTALLER_REPO_ZIP_URL
    source_root = _sanitize_batch_template_value(
        os.getenv('INSTALLER_SOURCE_ROOT', DEFAULT_INSTALLER_SOURCE_ROOT)
    ) or DEFAULT_INSTALLER_SOURCE_ROOT

    commit_hint = (
        str(os.getenv('RAILWAY_GIT_COMMIT_SHA', '')).strip()
        or str(os.getenv('VERCEL_GIT_COMMIT_SHA', '')).strip()
        or str(os.getenv('RENDER_GIT_COMMIT', '')).strip()
        or str(os.getenv('GITHUB_SHA', '')).strip()
    )
    installer_version = commit_hint[:12] if commit_hint else datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')

    return {
        '__LUNA_REPO_ZIP_URL__': repo_zip_url,
        '__LUNA_SOURCE_ROOT__': source_root,
        '__LUNA_INSTALLER_VERSION__': installer_version,
    }


def _render_installer_batch_script(template_path: Path) -> Tuple[str, str]:
    content = template_path.read_text(encoding='utf-8')
    context = _resolve_installer_template_context()
    for token, replacement in context.items():
        content = content.replace(token, replacement)
    return content, context.get('__LUNA_INSTALLER_VERSION__', 'unknown')


import smtplib
import socket
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _notify_admin_sync(machine_id, status='pending', token=None):
    """Send notification to admin via webhook and/or email."""
    webhook_url = os.getenv('NOTIFICATION_WEBHOOK_URL', '').strip()
    cloud_url = os.getenv('CLOUD_URL', 'Your Cloud Dashboard')

    if status == 'pending':
        magic_link = (
            f"{cloud_url}/admin/devices/quick-approve?machine_id={machine_id}&token={token}"
            if token
            else f"{cloud_url}/admin/devices"
        )
        subject = 'New Edge Node Request'
        message_plain = (
            f"New Device Request: Machine ID {machine_id} is requesting to join the cluster!\n\n"
            f"Approve instantly: {magic_link}\n\n"
            f"Or manage devices: {cloud_url}/admin/devices"
        )
        webhook_msg = (
            f"New Device Request: Machine `{machine_id}` is requesting to join the cluster. "
            f"Approve instantly: {magic_link}"
        )
    else:
        subject = 'Edge Node Approved'
        message_plain = f"Device Approved: Machine ID {machine_id} has been approved and provisioned."
        webhook_msg = f"Device Approved: Machine `{machine_id}` has been approved and provisioned."

    if webhook_url:
        try:
            payload = {'content': webhook_msg, 'text': webhook_msg}
            requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=5,
            )
        except Exception as e:
            logger.error(f'Failed to send webhook notification: {e}')

    admin_email = os.getenv('ADMIN_EMAIL', '').strip()

    resend_api_key = os.getenv('RESEND_API_KEY', '').strip()
    resend_from_email = os.getenv('RESEND_FROM_EMAIL', '').strip()
    resend_api_base_url = os.getenv('RESEND_API_BASE_URL', 'https://api.resend.com').strip().rstrip('/')

    if resend_api_key and resend_from_email and admin_email:
        try:
            resend_response = requests.post(
                f"{resend_api_base_url}/emails",
                headers={
                    'Authorization': f'Bearer {resend_api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'from': resend_from_email,
                    'to': [admin_email],
                    'subject': subject,
                    'text': message_plain,
                },
                timeout=8,
            )
            if resend_response.ok:
                return

            logger.warning(
                f"Resend API email attempt failed ({resend_response.status_code}): "
                f"{str(resend_response.text or '')[:240]}"
            )
        except Exception as resend_err:
            logger.warning(f'Failed Resend API email attempt: {resend_err}')

    smtp_server = os.getenv('SMTP_SERVER', '').strip()
    if smtp_server and admin_email:
        try:
            smtp_port = int(os.getenv('SMTP_PORT', '587'))
            smtp_user = os.getenv('SMTP_USERNAME', '').strip()
            smtp_pass = os.getenv('SMTP_PASSWORD', '').strip()
            strip_pw_spaces = str(os.getenv('SMTP_PASSWORD_STRIP_SPACES', 'true')).strip().lower() not in {
                '0', 'false', 'no', 'off'
            }
            if strip_pw_spaces:
                smtp_pass = smtp_pass.replace(' ', '')

            force_ipv4 = str(os.getenv('SMTP_FORCE_IPV4', 'true')).strip().lower() not in {
                '0', 'false', 'no', 'off'
            }
            try:
                smtp_timeout_seconds = max(1, int(os.getenv('SMTP_TIMEOUT_SECONDS', '8')))
            except Exception:
                smtp_timeout_seconds = 8

            msg = MIMEMultipart()
            msg['From'] = smtp_user or 'luna-system@localhost'
            msg['To'] = admin_email
            msg['Subject'] = subject
            msg.attach(MIMEText(message_plain, 'plain'))

            smtp_hosts = [smtp_server]
            if force_ipv4:
                try:
                    ipv4_hosts = []
                    for addr_info in socket.getaddrinfo(smtp_server, smtp_port, socket.AF_INET, socket.SOCK_STREAM):
                        ip_addr = str((addr_info[4] or ('',))[0] or '').strip()
                        if ip_addr and ip_addr not in ipv4_hosts:
                            ipv4_hosts.append(ip_addr)
                    if ipv4_hosts:
                        smtp_hosts = ipv4_hosts + [smtp_server]
                except Exception as resolve_err:
                    logger.warning(f'Failed to resolve IPv4 SMTP hosts for {smtp_server}: {resolve_err}')

            last_smtp_error = None
            for smtp_host in smtp_hosts:
                server = None
                try:
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=smtp_timeout_seconds)
                    if smtp_host != smtp_server:
                        # Keep original host for TLS SNI/cert hostname logic.
                        server._host = smtp_server  # type: ignore[attr-defined]
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                    server.quit()
                    last_smtp_error = None
                    break
                except Exception as send_err:
                    last_smtp_error = send_err
                    logger.warning(f'Failed SMTP attempt via {smtp_host}:{smtp_port}: {send_err}')
                    if server is not None:
                        try:
                            server.quit()
                        except Exception:
                            pass

            if last_smtp_error is not None:
                raise last_smtp_error
        except Exception as e:
            logger.error(f'Failed to send email notification: {e}')


def notify_admin(machine_id, status='pending', token=None):
    """Dispatch admin notifications without blocking request lifecycle."""
    async_enabled = str(os.getenv('NOTIFICATION_ASYNC', 'true')).strip().lower() not in {
        '0', 'false', 'no', 'off'
    }

    if not async_enabled:
        _notify_admin_sync(machine_id, status=status, token=token)
        return

    try:
        threading.Thread(
            target=_notify_admin_sync,
            args=(machine_id, status, token),
            daemon=True,
            name='notify-admin',
        ).start()
    except Exception as e:
        logger.error(f'Failed to start async admin notification worker: {e}')
        _notify_admin_sync(machine_id, status=status, token=token)


@app.route('/api/provision/request', methods=['POST'])
def provision_request():
    data = request.get_json() or {}
    machine_id = str(data.get('machine_id') or '').strip()
    if not machine_id:
        return jsonify({'error': 'Missing machine_id'}), 400

    if not re.fullmatch(r'[A-Za-z0-9._:-]{3,120}', machine_id):
        return jsonify({'error': 'Invalid machine_id format'}), 400

    approval_token = secrets.token_urlsafe(32)
    provision_secret = secrets.token_urlsafe(48)

    devices = _load_pending_devices()
    devices[machine_id] = {
        'status': 'pending',
        'requested_at': datetime.now(timezone.utc).isoformat(),
        'token': approval_token,
        'provision_secret_hash': _hash_provision_secret(provision_secret),
        'approved_at': None,
        'provisioned_at': None,
    }
    _save_pending_devices(devices)
    notify_admin(machine_id, 'pending', token=approval_token)

    return jsonify({
        'status': 'stored',
        'machine_id': machine_id,
        'provision_secret': provision_secret,
    })


@app.route('/api/provision/status', methods=['GET'])
def provision_status():
    machine_id = (request.args.get('machine_id') or '').strip()
    if not machine_id:
        return jsonify({'error': 'Missing machine_id'}), 400

    provision_secret = _get_provision_secret_from_request()
    if not provision_secret:
        return jsonify({'error': 'Missing provision_secret'}), 401

    devices = _load_pending_devices()
    device = devices.get(machine_id)
    if not device:
        return jsonify({'status': 'not_found'}), 404

    if not _is_valid_provision_secret(device, provision_secret):
        return jsonify({'error': 'Invalid provision_secret'}), 401

    current_status = str(device.get('status') or 'pending').strip().lower()
    if current_status in ('approved', 'provisioned'):
        bootstrap_token = _issue_bootstrap_token(
            machine_id,
            'provision_exchange',
            PROVISION_EXCHANGE_TOKEN_TTL_SECONDS,
        )
        installer_token = _issue_bootstrap_token(
            machine_id,
            'installer_download',
            INSTALLER_DOWNLOAD_TOKEN_TTL_SECONDS,
        )
        return jsonify({
            'status': current_status,
            'machine_id': machine_id,
            'bootstrap_token': bootstrap_token,
            'installer_token': installer_token,
            'bootstrap_exchange_endpoint': '/api/provision/bootstrap-exchange',
            'installer_download_endpoint': '/api/bootstrap/installer',
        })

    if current_status == 'rejected':
        return jsonify({'status': 'rejected'}), 403

    return jsonify({'status': 'pending'})


@app.route('/api/provision/bootstrap-exchange', methods=['POST'])
def provision_bootstrap_exchange():
    data = request.get_json() or {}
    machine_id = str(data.get('machine_id') or '').strip()
    provision_secret = str(data.get('provision_secret') or '').strip()
    bootstrap_token = str(data.get('bootstrap_token') or '').strip()

    if not machine_id:
        return jsonify({'error': 'Missing machine_id'}), 400
    if not provision_secret:
        return jsonify({'error': 'Missing provision_secret'}), 400
    if not bootstrap_token:
        return jsonify({'error': 'Missing bootstrap_token'}), 400

    devices = _load_pending_devices()
    device = devices.get(machine_id)
    if not device:
        return jsonify({'status': 'not_found'}), 404

    if not _is_valid_provision_secret(device, provision_secret):
        return jsonify({'error': 'Invalid provision_secret'}), 401

    current_status = str(device.get('status') or 'pending').strip().lower()
    if current_status not in ('approved', 'provisioned'):
        return jsonify({'error': 'Device is not approved for bootstrap exchange'}), 409

    token_ok, _, token_error = _verify_bootstrap_token(
        bootstrap_token,
        expected_purpose='provision_exchange',
        expected_machine_id=machine_id,
        consume=True,
    )
    if not token_ok:
        return jsonify({'error': token_error or 'Invalid bootstrap token'}), 403

    db_url = os.getenv('SUPABASE_DB_URL', '').strip()
    supa_url = os.getenv('SUPABASE_URL', '').strip()
    supa_service = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()

    if not db_url or not supa_url or not supa_service:
        return jsonify({'error': 'Provisioning credentials are not configured on the server'}), 503

    device['status'] = 'provisioned'
    device['provisioned_at'] = datetime.now(timezone.utc).isoformat()
    devices[machine_id] = device
    _save_pending_devices(devices)

    return jsonify({
        'status': 'provisioned',
        'credentials': {
            'SUPABASE_DB_URL': db_url,
            'SUPABASE_URL': supa_url,
            'SUPABASE_SERVICE_ROLE_KEY': supa_service,
        },
    })


@app.route('/api/bootstrap/installer/request', methods=['GET'])
def request_bootstrap_installer():
    machine_id = (request.args.get('machine_id') or '').strip()
    provision_secret = (
        request.args.get('provision_secret')
        or request.headers.get('X-Provision-Secret')
        or ''
    ).strip()

    if machine_id or provision_secret:
        if not machine_id or not provision_secret:
            return jsonify({'error': 'machine_id and provision_secret are both required'}), 400

        devices = _load_pending_devices()
        device = devices.get(machine_id)
        if not device:
            return jsonify({'error': 'Unknown machine_id'}), 404

        current_status = str(device.get('status') or 'pending').strip().lower()
        if current_status not in ('approved', 'provisioned'):
            return jsonify({'error': 'Device is not approved for installer access'}), 403

        if not _is_valid_provision_secret(device, provision_secret):
            return jsonify({'error': 'Invalid provision_secret'}), 401

        return _issue_installer_redirect(machine_id)

    if not ADMIN_PASSWORD:
        return 'ADMIN_PASSWORD is not set in the cloud .env! Cannot issue installer token.', 403

    auth = request.authorization
    if not auth or auth.password != ADMIN_PASSWORD:
        return Response(
            'Could not verify your access level for that URL.\n'
            'You have to login with proper credentials to issue an installer token',
            401,
            {'WWW-Authenticate': 'Basic realm="Login Required"'}
        )

    return _issue_installer_redirect(machine_id or 'admin-installer')


@app.route('/api/bootstrap/installer', methods=['GET'])
def download_bootstrap_installer():
    token = (request.args.get('token') or request.args.get('bootstrap_token') or '').strip()
    if not token:
        return jsonify({'error': 'Missing bootstrap token'}), 401

    token_ok, token_payload, token_error = _verify_bootstrap_token(
        token,
        expected_purpose='installer_download',
        consume=True,
    )
    if not token_ok or token_payload is None:
        return jsonify({'error': token_error or 'Invalid bootstrap token'}), 403

    installer_name = 'LUNA_LocalInstaller.bat'
    installer_dir = Path(app.static_folder or 'frontend') / 'static'
    installer_path = installer_dir / installer_name
    if not installer_path.exists():
        return jsonify({'error': 'Installer asset not found'}), 404

    try:
        installer_content, installer_version = _render_installer_batch_script(installer_path)
    except Exception as render_exc:
        logger.error(f"Failed to render installer template: {render_exc}")
        return jsonify({'error': 'Failed to render installer asset'}), 500

    response = Response(installer_content, mimetype='application/x-msdownload')
    response.headers['Content-Disposition'] = f'attachment; filename="{installer_name}"'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Luna-Installer-Version'] = installer_version
    response.headers['X-Luna-Installer-SHA256'] = hashlib.sha256(
        installer_content.encode('utf-8')
    ).hexdigest()
    return response


@app.route('/admin/devices', methods=['GET', 'POST'])
def admin_devices():
    if not ADMIN_PASSWORD:
        return 'ADMIN_PASSWORD is not set in the cloud .env! Cannot access portal.', 403

    auth = request.authorization
    if not auth or auth.password != ADMIN_PASSWORD:
        return Response(
            'Could not verify your access level for that URL.\n'
            'You have to login with proper credentials',
            401,
            {'WWW-Authenticate': 'Basic realm="Login Required"'}
        )

    devices = _load_pending_devices()

    if request.method == 'POST':
        action = request.form.get('action')
        machine_id = request.form.get('machine_id')

        if machine_id in devices:
            if action == 'approve':
                devices[machine_id]['status'] = 'approved'
                devices[machine_id]['approved_at'] = datetime.now(timezone.utc).isoformat()
                _save_pending_devices(devices)
                notify_admin(machine_id, 'approved')
            elif action == 'reject':
                del devices[machine_id]
                _save_pending_devices(devices)

        return redirect('/admin/devices')

    from flask import render_template_string
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>LUNA Device Provisioning</title>
        <style>
            body { font-family: system-ui; max-width: 800px; margin: 40px auto; padding: 20px; }
            .card { border: 1px solid #ccc; padding: 15px; margin-bottom: 10px; border-radius: 8px; }
            .btn { padding: 8px 15px; border-radius: 4px; border: none; cursor: pointer; color: white; margin-right: 10px; text-decoration: none; display: inline-block;}
            .btn-approve { background-color: #28a745; }
            .btn-reject { background-color: #dc3545; }
            .btn-installer { background-color: #007bff; }
        </style>
    </head>
    <body>
        <h2>Edge Device Provisioning Queue</h2>
        <p>Review and verify these pending hardware deployments before they can join the main cluster.</p>
        <hr>
        {% if devices %}
            {% for m_id, details in devices.items() %}
            <div class="card">
                <h3>Machine ID: {{ m_id }}</h3>
                <p>Status: <strong>{{ details.status }}</strong></p>
                <p>Requested At: {{ details.requested_at }}</p>
                {% if details.approved_at %}<p>Approved At: {{ details.approved_at }}</p>{% endif %}
                {% if details.provisioned_at %}<p>Provisioned At: {{ details.provisioned_at }}</p>{% endif %}
                {% if details.status == 'pending' %}
                <form method="POST" style="display:inline;">
                    <input type="hidden" name="machine_id" value="{{ m_id }}">
                    <button type="submit" name="action" value="approve" class="btn btn-approve">Approve Device</button>
                    <button type="submit" name="action" value="reject" class="btn btn-reject">Reject</button>
                </form>
                {% else %}
                <a href="/api/bootstrap/installer/request?machine_id={{ m_id | urlencode }}" class="btn btn-installer">Issue One-Time Installer Download</a>
                {% endif %}
            </div>
            {% endfor %}
        {% else %}
            <p><i>No pending device queries.</i></p>
        {% endif %}
    </body>
    </html>
    """
    return render_template_string(html_template, devices=devices)


@app.route('/admin/devices/quick-approve', methods=['GET'])
def admin_devices_quick_approve():
    if not ADMIN_PASSWORD:
        return 'ADMIN_PASSWORD is not set in the cloud .env! Cannot access portal.', 403

    auth = request.authorization
    if not auth or auth.password != ADMIN_PASSWORD:
        return Response(
            'Could not verify your access level for that URL.\n'
            'You have to login with proper credentials to approve this device',
            401,
            {'WWW-Authenticate': 'Basic realm="Login Required"'}
        )

    machine_id = (request.args.get('machine_id') or '').strip()
    token = (request.args.get('token') or '').strip()

    if not machine_id or not token:
        return 'Missing machine_id or token', 400

    devices = _load_pending_devices()
    device = devices.get(machine_id)

    if not device:
        return 'Device not found or already processed', 404

    if str(device.get('token') or '') != token:
        return 'Invalid or expired token', 403

    if str(device.get('status') or '') == 'pending':
        device['status'] = 'approved'
        device['approved_at'] = datetime.now(timezone.utc).isoformat()
        devices[machine_id] = device
        _save_pending_devices(devices)
        notify_admin(machine_id, 'approved')

    installer_request_link = f"/api/bootstrap/installer/request?machine_id={quote(machine_id)}"

    html_response = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Edge Node Approved</title>
        <style>
            body {{ font-family: system-ui; max-width: 600px; margin: 40px auto; text-align: center; }}
            .btn {{ padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; display: inline-block; }}
        </style>
    </head>
    <body>
        <h2>Device Approved Successfully</h2>
        <p>Machine <strong>{html.escape(machine_id)}</strong> has been granted access.</p>
        <br><br>
        <a href='{installer_request_link}' class='btn'>Issue One-Time Installer Download</a>
        <br><br>
        <a href='/admin/devices' class='btn'>Return to Admin Dashboard</a>
    </body>
    </html>
    """
    return html_response


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
