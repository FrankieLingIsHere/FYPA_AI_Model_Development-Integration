"""
Live PPE Compliance Detection - Demonstration Runner
=====================================================

Complete live demonstration of the PPE compliance detection pipeline.

This integrates all components:
- YOLO Stream Manager (real-time detection)
- Violation Detector (checks PPE compliance)
- Pipeline Orchestrator (coordinates workflow)
- Image Processor (annotates frames)
- Caption Generator (LLaVA descriptions)
- Report Generator (NLP analysis with RAG)
- Database logging

Usage:
    python run_live_demo.py

Controls:
    - Press 'q' to quit
    - Press 'p' to pause/resume
    - Violations are automatically detected and processed
"""

import sys
import cv2
import logging
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

# Import all components
from pipeline.config import (
    PPE_CLASSES, VIOLATION_RULES, YOLO_CONFIG, LLAVA_CONFIG,
    OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS,
    STREAM_CONFIG, REPORTS_DIR, VIOLATIONS_DIR
)

from pipeline.backend.core.pipeline_orchestrator import PipelineOrchestrator
from pipeline.backend.core.yolo_stream import YOLOStreamManager
from pipeline.backend.core.violation_detector import ViolationDetector
from pipeline.backend.core.image_processor import ImageProcessor
from pipeline.backend.integration.caption_generator import CaptionGenerator
from pipeline.backend.core.report_generator import ReportGenerator
from pipeline.backend.core.db_manager import db_manager


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline_demo.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class LiveDemonstration:
    """
    Live demonstration runner for PPE compliance detection.
    """
    
    def __init__(self):
        """Initialize the demonstration."""
        logger.info("Initializing Live Demonstration...")
        
        # Create configuration bundles
        self.orchestrator_config = {
            'VIOLATION_RULES': VIOLATION_RULES,
            'VIOLATIONS_DIR': VIOLATIONS_DIR
        }
        
        self.stream_config = {
            'YOLO_CONFIG': YOLO_CONFIG,
            'STREAM_CONFIG': STREAM_CONFIG,
            'PPE_CLASSES': PPE_CLASSES
        }
        
        self.processor_config = {
            'YOLO_CONFIG': YOLO_CONFIG,
            'PPE_CLASSES': PPE_CLASSES
        }
        
        self.caption_config = {
            'LLAVA_CONFIG': LLAVA_CONFIG
        }
        
        self.report_config = {
            'OLLAMA_CONFIG': OLLAMA_CONFIG,
            'RAG_CONFIG': RAG_CONFIG,
            'REPORT_CONFIG': REPORT_CONFIG,
            'BRAND_COLORS': BRAND_COLORS,
            'REPORTS_DIR': REPORTS_DIR,
            'VIOLATIONS_DIR': VIOLATIONS_DIR
        }
        
        # Initialize components
        self.orchestrator = PipelineOrchestrator(self.orchestrator_config)
        self.stream_manager = YOLOStreamManager(self.stream_config)
        self.violation_detector = ViolationDetector(VIOLATION_RULES)
        self.image_processor = ImageProcessor(self.processor_config)
        self.caption_generator = CaptionGenerator(self.caption_config)
        self.report_generator = ReportGenerator(self.report_config)
        
        # Inject components into orchestrator
        self.orchestrator.set_yolo_stream(self.stream_manager)
        self.orchestrator.set_violation_detector(self.violation_detector)
        self.orchestrator.set_image_processor(self.image_processor)
        self.orchestrator.set_caption_generator(self.caption_generator)
        self.orchestrator.set_report_generator(self.report_generator)
        self.orchestrator.set_db_manager(db_manager)
        
        # Register callbacks for notifications
        self.orchestrator.register_callback('on_violation_detected', self._on_violation)
        self.orchestrator.register_callback('on_report_ready', self._on_report)
        self.orchestrator.register_callback('on_error', self._on_error)
        
        logger.info("[OK] All components initialized")
    
    def _on_violation(self, data):
        """Callback when violation is detected."""
        print("\n" + "="*70)
        print("[!]  VIOLATION DETECTED!")
        print("="*70)
        print(f"Report ID: {data['report_id']}")
        print(f"Summary: {data['summary']}")
        print(f"Severity: {data['severity']}")
        print(f"People: {data['person_count']}")
        print(f"Violations: {data['violation_count']}")
        print("Processing violation...")
        print("="*70)
    
    def _on_report(self, data):
        """Callback when report is ready."""
        print("\n" + "="*70)
        print("📄 REPORT GENERATED!")
        print("="*70)
        print(f"Report ID: {data['report_id']}")
        if data.get('html_path'):
            print(f"HTML: {data['html_path']}")
        if data.get('pdf_path'):
            print(f"PDF: {data['pdf_path']}")
        if data.get('caption'):
            print(f"\nCaption: {data['caption'][:100]}...")
        print("="*70)
    
    def _on_error(self, data):
        """Callback when error occurs."""
        print("\n" + "="*70)
        print("[X] ERROR OCCURRED!")
        print("="*70)
        print(f"Error: {data.get('error', 'Unknown')}")
        print(f"Context: {data.get('context', 'N/A')}")
        print("="*70)
    
    def run(self):
        """Run the live demonstration."""
        print("\n" + "="*70)
        print("PPE COMPLIANCE DETECTION - LIVE DEMONSTRATION")
        print("="*70)
        print("\nStarting live detection...")
        print("\nControls:")
        print("  - Press 'q' to quit")
        print("  - Press 'p' to pause/resume detection")
        print("  - Press 's' to show status")
        print("\nViolations will be automatically detected and processed.")
        print("Reports will be saved to:", REPORTS_DIR)
        print("\n" + "="*70)
        
        # Start the pipeline
        self.orchestrator.start()
        
        # Display loop
        try:
            while True:
                # Get current frame from stream
                frame = self.stream_manager.get_current_frame()
                
                if frame is not None:
                    # Add status overlay
                    status = self.orchestrator.get_status()
                    info = {
                        'State': status['state'],
                        'FPS': round(self.stream_manager.stats['fps'], 1),
                        'Queue': f"{status['queue_size']}/{status.get('max_queue_size', 10)}",
                        'Violations': status['statistics']['total_violations'],
                        'Reports': status['statistics']['total_reports']
                    }
                    
                    display_frame = self.image_processor.add_info_overlay(frame, info)
                    
                    # Show frame
                    cv2.imshow('PPE Compliance Detection - Live Demo', display_frame)
                
                # Handle keyboard input
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'):
                    print("\nQuitting...")
                    break
                elif key == ord('p'):
                    if self.stream_manager.paused:
                        self.orchestrator.resume()
                        print("\n[RESUMED]  Detection RESUMED")
                    else:
                        self.orchestrator.pause()
                        print("\n[PAUSED]  Detection PAUSED")
                elif key == ord('s'):
                    self._print_status()
                
                time.sleep(0.01)  # Small delay to reduce CPU usage
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
        
        finally:
            # Cleanup
            print("\nStopping pipeline...")
            self.orchestrator.stop()
            cv2.destroyAllWindows()
            
            # Print final statistics
            self._print_final_stats()
    
    def _print_status(self):
        """Print current status."""
        status = self.orchestrator.get_status()
        stream_status = self.stream_manager.get_status()
        
        print("\n" + "="*70)
        print("CURRENT STATUS")
        print("="*70)
        print(f"Pipeline State: {status['state']}")
        print(f"Stream Running: {stream_status['running']}")
        print(f"Stream Paused: {stream_status['paused']}")
        print(f"FPS: {stream_status['fps']}")
        print(f"Frames Processed: {stream_status['frames_processed']}")
        print(f"Queue Size: {status['queue_size']}/{10}")
        print(f"In Cooldown: {status['in_cooldown']}")
        if status['in_cooldown']:
            print(f"Cooldown Remaining: {status['cooldown_remaining']:.1f}s")
        print(f"\nStatistics:")
        print(f"  Total Violations: {status['statistics']['total_violations']}")
        print(f"  Total Reports: {status['statistics']['total_reports']}")
        print(f"  Errors: {status['statistics']['errors']}")
        if status['statistics']['uptime_seconds']:
            print(f"  Uptime: {status['statistics']['uptime_seconds']:.1f}s")
        print("="*70)
    
    def _print_final_stats(self):
        """Print final statistics."""
        status = self.orchestrator.get_status()
        
        print("\n" + "="*70)
        print("FINAL STATISTICS")
        print("="*70)
        print(f"Total Violations Detected: {status['statistics']['total_violations']}")
        print(f"Total Reports Generated: {status['statistics']['total_reports']}")
        print(f"Errors Encountered: {status['statistics']['errors']}")
        if status['statistics']['uptime_seconds']:
            uptime = status['statistics']['uptime_seconds']
            print(f"Total Runtime: {uptime:.1f}s ({uptime/60:.1f} minutes)")
        
        # Database stats
        if db_manager.is_connected():
            recent = db_manager.get_recent(limit=100)
            print(f"Reports in Database: {len(recent)}")
        
        print("="*70)
        print("\n[OK] Demonstration completed successfully!")
        print(f"\nReports saved to: {REPORTS_DIR}")
        print(f"Violation images saved to: {VIOLATIONS_DIR}")
        print(f"Log file: pipeline_demo.log")
        print("\nThank you for using PPE Compliance Detection System!")
        print("="*70 + "\n")


def main():
    """Main entry point."""
    print("\n" + "="*70)
    print("PPE COMPLIANCE DETECTION SYSTEM")
    print("Live Demonstration")
    print("="*70)
    
    # Check if Ollama is running
    print("\nChecking prerequisites...")
    import requests
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=2)
        if response.ok:
            print("[OK] Ollama is running")
        else:
            print("[!]  Warning: Ollama may not be running properly")
            print("   Report generation will be limited")
    except:
        print("[!]  Warning: Could not connect to Ollama")
        print("   Make sure Ollama is running: ollama serve")
        print("   Report generation will be limited")
    
    # Check webcam
    print("Checking webcam...")
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        print("[OK] Webcam available")
        cap.release()
    else:
        print("[X] ERROR: Could not open webcam")
        print("   Make sure your webcam is connected and not in use")
        return
    
    print("\n" + "="*70)
    input("Press ENTER to start the demonstration...")
    
    # Run demonstration
    demo = LiveDemonstration()
    demo.run()


if __name__ == '__main__':
    main()
