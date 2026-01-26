import sys
import logging
from pathlib import Path
from datetime import datetime
import json
import cv2
from dotenv import load_dotenv

# Add parent dir to path
sys.path.insert(0, str(Path.cwd()))

# Load env vars
load_dotenv()

from pipeline.config import OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, REPORTS_DIR, VIOLATIONS_DIR, SUPABASE_CONFIG
from pipeline.backend.core.supabase_db import create_db_manager_from_env
from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
from pipeline.backend.core.violation_queue import ViolationQueueManager
from infer_image import predict_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ManualRecovery")

def manual_recover(report_id):
    print(f"Attempting manual recovery for {report_id}...")
    
    # 1. Setup components
    try:
        db_manager = create_db_manager_from_env()
        storage_manager = create_storage_manager_from_env()
        
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
        
        print("Components initialized.")
    except Exception as e:
        print(f"Failed to intialize components: {e}")
        return

    # 2. Check disk data
    violation_dir = VIOLATIONS_DIR.absolute() / report_id
    if not violation_dir.exists():
        print(f"Directory {violation_dir} does not exist!")
        return

    original_path = violation_dir / 'original.jpg'
    annotated_path = violation_dir / 'annotated.jpg'
    metadata_path = violation_dir / 'metadata.json'
    
    if not original_path.exists():
        print("original.jpg missing!")
        return
        
    # 3. Load/Generate Data
    detections = []
    timestamp = datetime.now()
    caption = ""
    
    # Try metadata first
    if metadata_path.exists():
        with open(metadata_path, 'r') as f:
            meta = json.load(f)
            # Use metadata timestamp if available
            if 'timestamp' in meta:
                # Parse timestamp... simple override for now
                pass
    
    # Re-run inference just to be safe and get fresh detections
    print("Running YOLO inference...")
    image = cv2.imread(str(original_path))
    detections, annotated = predict_image(image, conf=0.25)
    
    # Violation Types
    violation_keywords = ['no-hardhat', 'no-gloves', 'no-safety vest', 'no-mask', 'no-goggles']
    violation_types = [d['class_name'] for d in detections 
                      if any(k in d['class_name'].lower() for k in violation_keywords)]
    
    print(f"Detections: {len(detections)}")
    print(f"Violations: {violation_types}")
    
    # 4. Generate Caption (Manual call)
    try:
        from pipeline.backend.integration.caption_generator import CaptionGenerator
        caption_gen = CaptionGenerator({'LLAVA_CONFIG': {'model_path': 'llava', 'temperature': 0.7}}) # simple config
        caption = caption_gen.generate_caption(str(original_path))
        print(f"Caption: {caption}")
    except Exception as e:
        print(f"Caption gen failed: {e}")
        caption = "Caption generation failed during recovery"

    # 5. Generate Report
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
        'location': 'Recovery',
        'severity': 'HIGH',
        'person_count': len(detections),
        'detection_data': {'reprocessed': True} # Force upsert
    }
    
    print("Generating report...")
    try:
        # Update status to generating
        db_manager.update_detection_status(report_id, 'generating')
        
        result = report_generator.generate_report(report_data)
        if result:
            print("Report generated successfully!")
            db_manager.update_detection_status(report_id, 'completed')
        else:
            print("Report generation returned None")
            db_manager.update_detection_status(report_id, 'failed', 'Recovery returned None')
            
    except Exception as e:
        print(f"Report generation crashed: {e}")
        db_manager.update_detection_status(report_id, 'failed', str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    manual_recover("20260125_194451")
