"""
YOLO Stream Manager - Real-time video detection system
======================================================

Handles:
- Video capture (webcam/RTSP)
- Real-time YOLOv8 inference
- Pause/Resume functionality
- Motion JPEG encoding for web streaming
- Thread-safe operation
- Frame callbacks to pipeline orchestrator

Usage:
    stream = YOLOStreamManager(config)
    stream.start(on_frame_callback=process_frame)
    stream.pause()  # Pause detection
    stream.resume()  # Resume detection
    stream.stop()  # Stop stream
"""

import logging
import threading
import time
import cv2
import numpy as np
from typing import Optional, Callable, List, Dict, Any, Tuple
from queue import Queue, Empty
from datetime import datetime
from ultralytics import YOLO
from pathlib import Path

logger = logging.getLogger(__name__)


class YOLOStreamManager:
    """
    Manages video stream capture and YOLO detection.
    
    Thread-safe with pause/resume support.
    Provides Motion JPEG frames for web streaming.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize YOLO stream manager.
        
        Args:
            config: Configuration dictionary from config.py
        """
        self.config = config
        
        # Video source
        stream_config = config.get('STREAM_CONFIG', {})
        self.source = stream_config.get('source', 0)
        self.fps_limit = stream_config.get('fps_limit', 30)
        self.display_width = stream_config.get('display_width', 1280)
        self.display_height = stream_config.get('display_height', 720)
        self.jpeg_quality = stream_config.get('motion_jpeg_quality', 85)
        
        # YOLO model
        yolo_config = config.get('YOLO_CONFIG', {})
        model_path = yolo_config.get('model_path', 'yolov8s.pt')
        self.conf_threshold = yolo_config.get('conf_threshold', 0.10)
        self.iou_threshold = yolo_config.get('iou_threshold', 0.45)
        self.device = yolo_config.get('device', 0)
        
        # Load YOLO model
        logger.info(f"Loading YOLO model: {model_path}")
        self.model = YOLO(model_path)
        logger.info(f"[OK] YOLO model loaded successfully")
        
        # Class names
        self.class_names = config.get('PPE_CLASSES', {})
        
        # State
        self.running = False
        self.paused = False
        self.capture: Optional[cv2.VideoCapture] = None
        
        # Threading
        self.capture_thread: Optional[threading.Thread] = None
        self.should_stop = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Not paused initially
        
        # Frame buffer for web streaming (Motion JPEG)
        self.current_frame: Optional[np.ndarray] = None
        self.current_jpeg: Optional[bytes] = None
        self.frame_lock = threading.Lock()
        
        # Callback for processed frames (to orchestrator)
        self.on_frame_callback: Optional[Callable] = None
        
        # Statistics
        self.stats = {
            'frames_processed': 0,
            'fps': 0.0,
            'last_fps_update': time.time(),
            'frame_count_since_update': 0
        }
        
        logger.info("YOLO Stream Manager initialized")
    
    # =========================================================================
    # STREAM CONTROL
    # =========================================================================
    
    def start(self, on_frame_callback: Optional[Callable] = None):
        """
        Start video capture and detection.
        
        Args:
            on_frame_callback: Function to call with (frame, detections) after each detection
        """
        if self.running:
            logger.warning("Stream already running")
            return False
        
        self.on_frame_callback = on_frame_callback
        
        # Open video capture
        logger.info(f"Opening video source: {self.source}")
        self.capture = cv2.VideoCapture(self.source)
        
        if not self.capture.isOpened():
            logger.error(f"[X] Failed to open video source: {self.source}")
            return False
        
        # Set resolution to maximum for high-quality capture
        # We'll resize for YOLO inference but keep original for captioning
        max_width = 1920  # Full HD
        max_height = 1080
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, max_width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, max_height)
        self.capture.set(cv2.CAP_PROP_FPS, self.fps_limit)
        
        # Get actual resolution
        actual_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(f"Webcam capturing at: {actual_width}x{actual_height}")
        logger.info(f"YOLO inference at: {self.display_width}x{self.display_height}")
        
        # Reset state
        self.running = True
        self.paused = False
        self.should_stop.clear()
        self.pause_event.set()
        
        # Start capture thread
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            name="YOLOCaptureThread",
            daemon=True
        )
        self.capture_thread.start()
        
        logger.info("[OK] YOLO stream started")
        return True
    
    def stop(self):
        """Stop video capture and detection."""
        if not self.running:
            logger.warning("Stream not running")
            return
        
        logger.info("Stopping YOLO stream...")
        
        # Signal stop
        self.should_stop.set()
        self.pause_event.set()  # Unpause if paused
        
        # Wait for thread
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=5)
        
        # Release capture
        if self.capture:
            self.capture.release()
            self.capture = None
        
        self.running = False
        logger.info("[OK] YOLO stream stopped")
    
    def pause(self):
        """Pause detection (frame capture continues but no inference)."""
        if not self.running:
            logger.warning("Cannot pause - stream not running")
            return False
        
        if self.paused:
            logger.debug("Stream already paused")
            return False
        
        self.paused = True
        self.pause_event.clear()  # Block processing
        logger.info("[PAUSED] YOLO stream paused")
        return True
    
    def resume(self):
        """Resume detection."""
        if not self.running:
            logger.warning("Cannot resume - stream not running")
            return False
        
        if not self.paused:
            logger.debug("Stream already running")
            return False
        
        self.paused = False
        self.pause_event.set()  # Unblock processing
        logger.info("[RESUMED] YOLO stream resumed")
        return True
    
    # =========================================================================
    # CAPTURE LOOP (Runs in separate thread)
    # =========================================================================
    
    def _capture_loop(self):
        """Main capture and detection loop."""
        logger.info("Capture loop started")
        
        fps_counter = 0
        fps_start = time.time()
        
        while not self.should_stop.is_set():
            # Wait if paused
            self.pause_event.wait()
            
            if self.should_stop.is_set():
                break
            
            # Read frame (high resolution)
            ret, frame_original = self.capture.read()
            
            if not ret:
                logger.error("Failed to read frame")
                time.sleep(0.1)
                continue
            
            # Resize for YOLO inference (faster processing)
            frame_resized = cv2.resize(frame_original, (self.display_width, self.display_height))
            
            # FPS limiting
            time.sleep(1.0 / self.fps_limit)
            
            # Run YOLO inference on RESIZED frame
            try:
                results = self.model.predict(
                    frame_resized,
                    conf=self.conf_threshold,
                    iou=self.iou_threshold,
                    device=self.device,
                    verbose=False
                )
                
                # Parse detections
                detections = self._parse_yolo_results(results[0])
                
                # Annotate RESIZED frame for display
                annotated_frame = results[0].plot()
                
                # Update current frame for streaming
                with self.frame_lock:
                    self.current_frame = annotated_frame.copy()
                    # Encode as JPEG
                    _, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                    self.current_jpeg = buffer.tobytes()
                
                # Callback to orchestrator with ORIGINAL HIGH-RES frame (unannotated)
                # This ensures high quality for captioning!
                if self.on_frame_callback and not self.paused:
                    try:
                        self.on_frame_callback(frame_original.copy(), detections)
                    except Exception as e:
                        logger.error(f"Error in frame callback: {e}", exc_info=True)
                
                # Update stats
                self.stats['frames_processed'] += 1
                fps_counter += 1
                
                # Update FPS every second
                if time.time() - fps_start >= 1.0:
                    self.stats['fps'] = fps_counter / (time.time() - fps_start)
                    fps_counter = 0
                    fps_start = time.time()
                
            except Exception as e:
                logger.error(f"Error in detection: {e}", exc_info=True)
                time.sleep(0.1)
        
        logger.info("Capture loop stopped")
    
    def _parse_yolo_results(self, result) -> List[Dict[str, Any]]:
        """
        Parse YOLO results into detection dictionaries.
        
        Args:
            result: YOLO result object
        
        Returns:
            List of detection dictionaries
        """
        detections = []
        
        if result.boxes is None or len(result.boxes) == 0:
            return detections
        
        boxes = result.boxes.cpu().numpy()
        
        for box in boxes:
            # Get box coordinates
            x1, y1, x2, y2 = box.xyxy[0]
            
            # Get class and confidence
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            
            # Get class name
            class_name = self.class_names.get(class_id, f'Class_{class_id}')
            
            detection = {
                'class_id': class_id,
                'class_name': class_name,
                'confidence': confidence,
                'bbox': [float(x1), float(y1), float(x2), float(y2)],
                'bbox_normalized': [
                    float(x1) / result.orig_shape[1],
                    float(y1) / result.orig_shape[0],
                    float(x2) / result.orig_shape[1],
                    float(y2) / result.orig_shape[0]
                ]
            }
            
            detections.append(detection)
        
        return detections
    
    # =========================================================================
    # FRAME STREAMING (Motion JPEG)
    # =========================================================================
    
    def get_current_frame(self) -> Optional[np.ndarray]:
        """
        Get the current annotated frame.
        
        Returns:
            Current frame as numpy array, or None if no frame available
        """
        with self.frame_lock:
            return self.current_frame.copy() if self.current_frame is not None else None
    
    def get_current_jpeg(self) -> Optional[bytes]:
        """
        Get the current frame as JPEG bytes (for Motion JPEG streaming).
        
        Returns:
            JPEG bytes, or None if no frame available
        """
        with self.frame_lock:
            return self.current_jpeg
    
    def generate_mjpeg_stream(self):
        """
        Generator for Motion JPEG streaming (for Flask response).
        
        Yields:
            JPEG frames in multipart format
        """
        while self.running:
            jpeg = self.get_current_jpeg()
            
            if jpeg is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
            
            time.sleep(1.0 / self.fps_limit)
    
    # =========================================================================
    # STATUS
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get stream status."""
        return {
            'running': self.running,
            'paused': self.paused,
            'source': str(self.source),
            'fps': round(self.stats['fps'], 2),
            'frames_processed': self.stats['frames_processed'],
            'resolution': f"{self.display_width}x{self.display_height}"
        }


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import YOLO_CONFIG, STREAM_CONFIG, PPE_CLASSES
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("YOLO STREAM MANAGER TEST")
    print("=" * 70)
    
    # Create config
    config = {
        'YOLO_CONFIG': YOLO_CONFIG,
        'STREAM_CONFIG': STREAM_CONFIG,
        'PPE_CLASSES': PPE_CLASSES
    }
    
    # Create stream manager
    stream = YOLOStreamManager(config)
    
    print(f"\n[OK] YOLO Stream Manager initialized")
    print(f"Source: {stream.source}")
    print(f"FPS Limit: {stream.fps_limit}")
    print(f"Resolution: {stream.display_width}x{stream.display_height}")
    print(f"Model loaded: {stream.model is not None}")
    print(f"Classes: {len(stream.class_names)}")
    
    # Test callback
    def test_callback(frame, detections):
        print(f"Frame: {frame.shape}, Detections: {len(detections)}")
        if detections:
            for det in detections[:3]:  # Show first 3
                print(f"  - {det['class_name']}: {det['confidence']:.2f}")
    
    print("\n--- Testing Stream Start ---")
    print("NOTE: This will open your webcam. Press Ctrl+C to stop.")
    print("Starting in 3 seconds...")
    time.sleep(3)
    
    try:
        stream.start(on_frame_callback=test_callback)
        
        # Run for 10 seconds
        for i in range(10):
            time.sleep(1)
            status = stream.get_status()
            print(f"[{i+1}s] FPS: {status['fps']}, Frames: {status['frames_processed']}")
            
            # Test pause/resume at 5 seconds
            if i == 4:
                print("Testing pause...")
                stream.pause()
            elif i == 6:
                print("Testing resume...")
                stream.resume()
        
        stream.stop()
        print("\n[OK] All tests completed!")
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        stream.stop()
    
    print("=" * 70)
