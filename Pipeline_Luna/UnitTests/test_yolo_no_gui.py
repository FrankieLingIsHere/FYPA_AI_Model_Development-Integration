"""
Quick YOLO Test - No GUI
=========================
Tests YOLO detection and saves annotated frames to disk.
No display window required.
"""

import cv2
import time
from pathlib import Path
from ultralytics import YOLO

def main():
    print("="*70)
    print("YOLO Detection Test - No GUI")
    print("="*70)
    print()
    
    # Create output directory
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    
    print(f"Output directory: {output_dir}")
    print()
    
    # Load YOLO model
    print("Loading YOLO model...")
    model = YOLO("yolov8s.pt")
    print("[OK] Model loaded")
    print()
    
    # Open webcam
    print("Opening webcam...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("[ERROR] Cannot open webcam")
        return
    
    print("[OK] Webcam opened")
    print()
    
    print("Processing frames... (Press Ctrl+C to stop)")
    print("Saving every 10th frame to disk")
    print()
    
    frame_count = 0
    start_time = time.time()
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Cannot read frame")
                break
            
            frame_count += 1
            
            # Run YOLO inference
            results = model(frame, verbose=False)
            
            # Get annotated frame
            annotated = results[0].plot()
            
            # Save every 10th frame
            if frame_count % 10 == 0:
                output_path = output_dir / f"frame_{frame_count:04d}.jpg"
                cv2.imwrite(str(output_path), annotated)
                
                elapsed = time.time() - start_time
                fps = frame_count / elapsed
                
                # Count detections
                detections = len(results[0].boxes)
                
                print(f"Frame {frame_count:04d} | FPS: {fps:.1f} | Detections: {detections} | Saved: {output_path.name}")
            
            # Run for 30 seconds then stop
            if time.time() - start_time > 30:
                print("\n30 seconds elapsed - stopping test")
                break
                
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    
    finally:
        cap.release()
        
        elapsed = time.time() - start_time
        print()
        print("="*70)
        print("Test Complete")
        print("="*70)
        print(f"Runtime: {elapsed:.1f} seconds")
        print(f"Frames: {frame_count}")
        print(f"Average FPS: {frame_count/elapsed:.1f}")
        print(f"Saved frames: {len(list(output_dir.glob('*.jpg')))}")
        print(f"Output: {output_dir}")
        print("="*70)

if __name__ == "__main__":
    main()
