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
from pathlib import Path
from datetime import datetime
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
    from pipeline.config import VIOLATION_RULES, LLAVA_CONFIG, OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, VIOLATIONS_DIR, REPORTS_DIR, SUPABASE_CONFIG
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
active_camera = None

# Violation detection state
violation_detector = None
caption_generator = None
report_generator = None
db_manager = None
storage_manager = None
last_violation_time = 0
VIOLATION_COOLDOWN = 60  # seconds between violation captures (increased to allow model loading time)

# =========================================================================
# VIOLATION PROCESSING
# =========================================================================

def initialize_pipeline_components():
    """Initialize violation detector, caption generator, report generator, and Supabase managers."""
    global violation_detector, caption_generator, report_generator, db_manager, storage_manager
    
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
            
        logger.info("[OK] All pipeline components initialized")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing pipeline components: {e}")
        import traceback
        traceback.print_exc()
        return False


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
        
        # Check for ANY PPE violations
        violation_keywords = ['no-hardhat', 'nohardhat', 'no-gloves', 'nogloves', 
                             'no-vest', 'novest', 'no-boots', 'noboots',
                             'no-mask', 'nomask', 'no-goggles', 'nogoggles']
        
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
        
        # Save original frame
        original_path = violation_dir / 'original.jpg'
        cv2.imwrite(str(original_path), frame)
        logger.info(f"✓ Saved original image: {original_path}")
        
        # Save annotated frame
        _, annotated = predict_image(frame, conf=0.10)
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
                    else:
                        logger.warning(f"❌ Report not found in violations directory: {target_html}")
                else:
                    logger.warning(f"❌ Report generation returned None or no HTML path. Result: {result}")
                    
            except Exception as e:
                logger.error(f"❌ Report generation failed: {e}", exc_info=True)
        
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
                        
                        violations.append({
                            'report_id': report_id,
                            'timestamp': timestamp.isoformat(),
                            'has_original': (violation_dir / 'original.jpg').exists(),
                            'has_annotated': (violation_dir / 'annotated.jpg').exists(),
                            'has_report': (violation_dir / 'report.html').exists(),
                            'severity': metadata.get('severity', 'medium'),
                            'violation_type': metadata.get('violation_type', 'Unknown'),
                            'location': metadata.get('location', 'Unknown')
                        })
                    except ValueError:
                        logger.warning(f"Skipping invalid report directory: {report_id}")
                        continue
        return jsonify(violations)
    
    # Use Supabase
    try:
        violations = db_manager.get_recent_violations(limit=100)
        
        # Format violations for API response
        formatted_violations = []
        for v in violations:
            formatted_violations.append({
                'report_id': v['report_id'],
                'timestamp': v['timestamp'].isoformat() if v.get('timestamp') else None,
                'person_count': v.get('person_count', 0),
                'violation_count': v.get('violation_count', 0),
                'severity': v.get('severity', 'UNKNOWN'),
                'violation_summary': v.get('violation_summary'),
                'has_original': bool(v.get('original_image_key')),
                'has_annotated': bool(v.get('annotated_image_key')),
                'has_report': bool(v.get('report_html_key'))
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
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start.replace(day=week_start.day - week_start.weekday())
        
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
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start.replace(day=week_start.day - week_start.weekday())
        
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


@app.route('/report/<report_id>')
def view_report(report_id):
    """View a specific violation report from Supabase or local storage."""
    if storage_manager is None or db_manager is None:
        # Fallback to local filesystem
        violation_dir = VIOLATIONS_DIR / report_id
        
        if not violation_dir.exists():
            abort(404, description="Report not found")
        
        report_html = violation_dir / 'report.html'
        if report_html.exists():
            return send_from_directory(str(violation_dir), 'report.html')
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
        
        # Get signed URL
        signed_url = storage_manager.get_signed_url(report_html_key)
        
        if not signed_url:
            abort(404, description="Failed to generate signed URL")
        
        # Redirect to signed URL
        return redirect(signed_url)
        
    except Exception as e:
        logger.error(f"Error fetching report from Supabase: {e}")
        abort(500, description="Failed to fetch report")


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

def generate_frames(conf=0.10):
    """Generate frames from webcam with YOLO detection and violation processing."""
    global active_camera
    
    with camera_lock:
        if active_camera is None:
            active_camera = cv2.VideoCapture(0)
            if not active_camera.isOpened():
                logger.error("Failed to open webcam")
                return
        
        cap = active_camera
    
    logger.info("Starting live frame generation...")
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
                if cap is None or not cap.isOpened():
                    break
                
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Failed to read frame")
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
                    # Check for ANY PPE violations (no-hardhat, no-gloves, no-vest, etc.)
                    violation_keywords = ['no-hardhat', 'nohardhat', 'no-gloves', 'nogloves', 
                                         'no-vest', 'novest', 'no-boots', 'noboots',
                                         'no-mask', 'nomask', 'no-goggles', 'nogoggles']
                    
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
                        logger.info("Starting background thread to process violation...")
                        logger.info("=" * 80)
                        
                        # Process violation in background thread
                        frame_copy = frame.copy()
                        detections_copy = detections.copy()
                        violation_thread = Thread(
                            target=process_violation,
                            args=(frame_copy, detections_copy),
                            daemon=True
                        )
                        violation_thread.start()
                        logger.info(f"✓ Background thread started (Thread ID: {violation_thread.ident})")
                
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
    conf = float(request.args.get('conf', 0.10))
    return Response(
        generate_frames(conf=conf),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/live/start', methods=['POST'])
def start_live():
    """Start live monitoring."""
    global active_camera
    
    with camera_lock:
        if active_camera is None:
            active_camera = cv2.VideoCapture(0)
            if not active_camera.isOpened():
                return jsonify({'success': False, 'error': 'Failed to open webcam'}), 500
    
    return jsonify({'success': True, 'message': 'Live monitoring started'})


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
    """Get live monitoring status."""
    with camera_lock:
        is_active = active_camera is not None and active_camera.isOpened()
    
    return jsonify({
        'active': is_active,
        'camera_index': 0 if is_active else None
    })


# =========================================================================
# API ENDPOINTS - IMAGE INFERENCE
# =========================================================================

@app.route('/api/inference/upload', methods=['POST'])
def upload_inference():
    """Run inference on uploaded image."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No image selected'}), 400
    
    try:
        # Read image
        img_bytes = file.read()
        
        # Get confidence threshold
        conf = float(request.form.get('conf', 0.10))
        
        # Run inference
        detections, annotated = predict_image(img_bytes, conf=conf)
        
        # Encode annotated image to base64
        _, buffer = cv2.imencode('.jpg', annotated)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'success': True,
            'detections': detections,
            'annotated_image': f'data:image/jpeg;base64,{img_base64}',
            'count': len(detections)
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
    logger.info("")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 80)
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True,
        use_reloader=False  # Prevent double initialization
    )
