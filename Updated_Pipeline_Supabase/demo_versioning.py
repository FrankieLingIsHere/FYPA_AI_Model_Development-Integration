
import sys
import os
import json
from datetime import datetime
from pathlib import Path

# Load env
from dotenv import load_dotenv
load_dotenv()

# Setup paths
sys.path.append(os.getcwd())

from pipeline.backend.core.supabase_db import create_db_manager_from_env
from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
from pipeline.config import (
    OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, 
    REPORTS_DIR, VIOLATIONS_DIR, SUPABASE_CONFIG
)

def demo_versioning(report_id):
    print(f"Start demo for {report_id}")
    
    # 1. Init DB
    db_manager = create_db_manager_from_env()
    
    # 2. Get violation
    violation = db_manager.get_violation(report_id)
    if not violation:
        print("Violation not found")
        return
        
    print(f"Current caption: {violation.get('caption')[:50]}...")
    
    # 3. Create history
    existing_detection_data = violation.get('detection_data') or {}
    if isinstance(existing_detection_data, str):
        existing_detection_data = json.loads(existing_detection_data)
        
    caption_history = existing_detection_data.get('caption_history', [])
    
    # Fake V1 if empty
    if not caption_history and violation.get('caption'):
        caption_history.append({
            'version': 1,
            'timestamp': "2025-12-23T17:00:58",
            'caption': violation.get('caption'),
            'model': 'original'
        })
        
    # Generate fake V2
    new_caption = "SCENE: 1 person(s) detected. Person 1 is in center. ACTIVITY: Walking quickly. POSITION: Center. HEAD: No hardhat. TORSO: Blue shirt, no vest. ENVIRONMENT: Office corridor. [Creating V2 for DEMO purpose]"
    
    caption_history.append({
        'version': len(caption_history) + 1,
        'timestamp': datetime.now().isoformat(),
        'caption': new_caption,
        'model': 'llava-phi3:3.8b-DEMO'
    })
    
    print(f"Updated history: {len(caption_history)} versions")
    
    # 4. Generate Report
    report_config = {
        'OLLAMA_CONFIG': OLLAMA_CONFIG,
        'RAG_CONFIG': RAG_CONFIG,
        'REPORT_CONFIG': REPORT_CONFIG,
        'BRAND_COLORS': BRAND_COLORS,
        'REPORTS_DIR': REPORTS_DIR,
        'VIOLATIONS_DIR': VIOLATIONS_DIR,
        'SUPABASE_CONFIG': SUPABASE_CONFIG
    }
    generator = create_supabase_report_generator(report_config)
    
    report_data = {
        'report_id': report_id,
        'timestamp': violation.get('timestamp') or datetime.now(),
        'detections': [], # Keep empty for demo or reuse
        'violation_summary': violation.get('violation_summary'),
        'violation_count': violation.get('violation_count'),
        'caption': new_caption,
        'image_caption': new_caption,
        'caption_history': caption_history,
        'original_image_path': str(Path('temp_image.jpg')), # Dummy path
        'annotated_image_path': str(Path('temp_annotated.jpg')), # Dummy
        'location': "Demo Location",
        'severity': "HIGH",
        'person_count': 1,
        'detection_data': {
            'reprocessed': True,
            'caption_history': caption_history
        }
    }
    
    # We cheat and reuse existing image keys so we don't need real images
    result = generator.generate_report(report_data)
    
    # 5. Update DB
    metadata = existing_detection_data.copy()
    metadata['caption_history'] = caption_history
    
    db_manager.update_violation(
        report_id=report_id,
        caption=new_caption,
        detection_data=metadata,
        # Keep existing keys
        original_image_key=violation.get('original_image_key'),
        annotated_image_key=violation.get('annotated_image_key'),
        report_html_key=result.get('storage_keys', {}).get('report_html_key'), # Update HTML key
    )
    
    print("Success! Report updated with version 2.")

if __name__ == "__main__":
    demo_versioning("20251223_170058")
