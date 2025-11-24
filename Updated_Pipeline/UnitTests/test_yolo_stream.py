"""
Quick Test - YOLO Stream Only
==============================

Quick test of YOLO detection without full pipeline.
Use this to verify webcam and YOLO model are working.

Usage:
    python test_yolo_stream.py
"""

import sys
import cv2
import logging
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from pipeline.config import PPE_CLASSES, YOLO_CONFIG, STREAM_CONFIG
from pipeline.backend.core.yolo_stream import YOLOStreamManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("="*70)
print("QUICK TEST: YOLO STREAM")
print("="*70)

# Configuration
config = {
    'YOLO_CONFIG': YOLO_CONFIG,
    'STREAM_CONFIG': STREAM_CONFIG,
    'PPE_CLASSES': PPE_CLASSES
}

# Create stream
logger.info("Initializing YOLO stream...")
stream = YOLOStreamManager(config)

# Callback to print detections
def on_frame(frame, detections):
    if detections:
        print(f"\rDetections: {len(detections)} | ", end="")
        for det in detections[:3]:
            print(f"{det['class_name']}:{det['confidence']:.2f} ", end="")

print("\nStarting stream (Press 'q' to quit)...\n")

try:
    # Start stream
    stream.start(on_frame_callback=on_frame)
    
    # Display loop
    while True:
        frame = stream.get_current_frame()
        
        if frame is not None:
            # Add FPS counter
            fps = stream.stats['fps']
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            cv2.imshow('YOLO Stream Test', frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\n\nInterrupted")

finally:
    stream.stop()
    cv2.destroyAllWindows()
    print("\n✅ Test completed")
