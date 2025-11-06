"""
PPE Detection System - Headless Live Demonstration
===================================================
Runs the system without GUI (no cv2.imshow) - saves frames instead.
Suitable for systems where OpenCV was built without GUI support.
"""

import logging
import sys
import time
import requests
from pathlib import Path
import cv2

# Setup logging (no emoji characters for Windows console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Add pipeline to path
sys.path.append(str(Path(__file__).parent))

from pipeline.config import (
    PPE_CLASSES, VIOLATION_RULES, STREAM_CONFIG, CAPTION_CONFIG, 
    REPORT_CONFIG, DATABASE_CONFIG
)
from pipeline.backend.core.pipeline_orchestrator import PipelineOrchestrator
from pipeline.backend.core.yolo_stream import YOLOStreamManager
from pipeline.backend.core.violation_detector import ViolationDetector
from pipeline.backend.core.image_processor import ImageProcessor
from pipeline.backend.integration.caption_generator import CaptionGenerator
from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.db_manager import db_manager


class HeadlessDemo:
    """
    Headless demonstration - no GUI windows, saves frames to disk.
    """
    
    def __init__(self):
        """Initialize all components."""
        logger.info("Initializing Headless Demonstration...")
        
        # Create output directories
        self.output_dir = Path(__file__).parent / "demo_output"
        self.frames_dir = self.output_dir / "frames"
        self.violations_dir = self.output_dir / "violations"
        
        self.output_dir.mkdir(exist_ok=True)
        self.frames_dir.mkdir(exist_ok=True)
        self.violations_dir.mkdir(exist_ok=True)
        
        # Config
        self.stream_config = STREAM_CONFIG
        self.caption_config = CAPTION_CONFIG
        self.report_config = REPORT_CONFIG
        
        # Initialize components
        self.stream_manager = YOLOStreamManager(self.stream_config)
        self.violation_detector = ViolationDetector(VIOLATION_RULES)
        self.image_processor = ImageProcessor(self.stream_config)
        self.caption_generator = CaptionGenerator(
            self.caption_config.get('model_name'),
            self.caption_config.get('load_in_4bit', True)
        )
        self.report_generator = ReportGenerator(self.report_config)
        
        # Connect to database
        db_manager.connect(DATABASE_CONFIG)
        
        # Create orchestrator
        self.orchestrator = PipelineOrchestrator(
            config=VIOLATION_RULES,
            yolo_stream=self.stream_manager,
            violation_detector=self.violation_detector,
            image_processor=self.image_processor,
            caption_generator=self.caption_generator,
            report_generator=self.report_generator,
            on_violation_detected=self.on_violation,
            on_report_generated=self.on_report
        )
        
        # Statistics
        self.frame_count = 0
        self.violations = []
        self.start_time = None
        self.running = True
        
        logger.info("[OK] All components initialized")
    
    def on_violation(self, event):
        """Callback when violation is detected."""
        self.violations.append(event)
        
        print("\n" + "="*70)
        print("[!]  VIOLATION DETECTED!")
        print("="*70)
        print(f"Report ID: {event.report_id}")
        print(f"Summary: {event.violation_summary}")
        print(f"Severity: {event.severity}")
        print(f"People: {event.person_count}")
        print(f"Violations: {event.violation_count}")
        
        # Save violation frame
        if event.annotated_frame is not None:
            frame_path = self.violations_dir / f"{event.report_id}.jpg"
            cv2.imwrite(str(frame_path), event.annotated_frame)
            print(f"Frame saved: {frame_path}")
        
        print("Processing violation...")
        print("="*70 + "\n")
    
    def on_report(self, report_data):
        """Callback when report is generated."""
        print("\n" + "="*70)
        print("[OK] REPORT GENERATED!")
        print("="*70)
        print(f"Report ID: {report_data.get('report_id')}")
        print(f"File: {report_data.get('file_path')}")
        print(f"NLP Analysis: {len(report_data.get('nlp_analysis', ''))} chars")
        print("="*70 + "\n")
    
    def save_frame(self, frame, detections):
        """Save a sample frame every 30 frames."""
        self.frame_count += 1
        
        # Save every 30th frame
        if self.frame_count % 30 == 0:
            # Annotate frame
            annotated = self.image_processor.annotate_frame(frame.copy(), detections)
            
            # Add overlay
            elapsed = int(time.time() - self.start_time)
            fps = self.frame_count / elapsed if elapsed > 0 else 0
            annotated = self.image_processor.add_info_overlay(
                annotated, 
                time.strftime('%Y-%m-%d %H:%M:%S'),
                fps,
                len(self.violations)
            )
            
            # Save
            frame_path = self.frames_dir / f"frame_{self.frame_count:06d}.jpg"
            cv2.imwrite(str(frame_path), annotated)
            logger.info(f"Saved frame: {frame_path.name} (FPS: {fps:.1f}, Violations: {len(self.violations)})")
    
    def run(self):
        """Run the headless demonstration."""
        print("\n" + "="*70)
        print("PPE COMPLIANCE DETECTION - HEADLESS DEMONSTRATION")
        print("="*70)
        print()
        print("Output directories:")
        print(f"  - Frames: {self.frames_dir}")
        print(f"  - Violations: {self.violations_dir}")
        print()
        print("The system will:")
        print("  - Save every 30th frame with annotations")
        print("  - Save all violation frames")
        print("  - Generate reports for violations")
        print()
        print("Press Ctrl+C to stop...")
        print("="*70 + "\n")
        
        try:
            # Start pipeline
            self.start_time = time.time()
            self.orchestrator.start()
            
            # Run for demonstration (or until Ctrl+C)
            print("System running... monitoring for violations...\n")
            
            while self.running:
                time.sleep(1)
                
                # Print status every 10 seconds
                elapsed = int(time.time() - self.start_time)
                if elapsed > 0 and elapsed % 10 == 0:
                    fps = self.frame_count / elapsed
                    print(f"[STATUS] Runtime: {elapsed}s | Frames: {self.frame_count} | FPS: {fps:.1f} | Violations: {len(self.violations)}")
                
        except KeyboardInterrupt:
            print("\n\nStopping pipeline...")
        
        finally:
            # Stop pipeline
            self.orchestrator.stop()
            
            # Print statistics
            elapsed = time.time() - self.start_time
            print("\n" + "="*70)
            print("DEMONSTRATION COMPLETE")
            print("="*70)
            print(f"Runtime: {elapsed:.1f} seconds")
            print(f"Frames Processed: {self.frame_count}")
            print(f"Average FPS: {self.frame_count/elapsed:.1f}")
            print(f"Violations Detected: {len(self.violations)}")
            print(f"Frames Saved: {len(list(self.frames_dir.glob('*.jpg')))}")
            print(f"Violation Frames: {len(list(self.violations_dir.glob('*.jpg')))}")
            print()
            print("Output saved to:")
            print(f"  {self.output_dir}")
            print("="*70 + "\n")
            
            # Cleanup
            db_manager.disconnect()


def check_prerequisites():
    """Check if system is ready."""
    print("\n" + "="*70)
    print("PPE COMPLIANCE DETECTION SYSTEM")
    print("Headless Demonstration (No GUI)")
    print("="*70 + "\n")
    
    print("Checking prerequisites...")
    
    # Check Ollama
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code == 200:
            print("[OK] Ollama is running")
        else:
            print("[!] Ollama returned status:", response.status_code)
    except:
        print("[!] WARNING: Ollama may not be running (http://localhost:11434)")
        print("    Reports will use fallback mode")
    
    # Check webcam
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        print("[OK] Webcam available")
        cap.release()
    else:
        print("[!] ERROR: Webcam not available")
        return False
    
    print()
    return True


def main():
    """Main entry point."""
    if not check_prerequisites():
        print("\nPrerequisites not met. Please fix errors and try again.")
        return
    
    print("="*70)
    input("Press ENTER to start the demonstration...")
    
    demo = HeadlessDemo()
    demo.run()


if __name__ == "__main__":
    main()
