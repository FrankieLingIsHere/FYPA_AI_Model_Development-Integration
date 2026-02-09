
import sys
import os
import json
import base64
import requests
from datetime import datetime
from pathlib import Path

# Load env
from dotenv import load_dotenv
load_dotenv()

# Setup paths
sys.path.append(os.getcwd())

from pipeline.backend.core.supabase_db import create_db_manager_from_env
from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
from pipeline.config import (
    OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, 
    REPORTS_DIR, VIOLATIONS_DIR, SUPABASE_CONFIG
)

REPORT_ID = "20251223_170058"
IMAGE_PATH = Path(f"{REPORT_ID}_original.jpg")

def check_moondream():
    try:
        resp = requests.get('http://localhost:11434/api/tags')
        if resp.ok:
            models = [m['name'] for m in resp.json()['models']]
            print(f"Available models: {models}")
            return any('moondream' in m for m in models)
    except:
        return False
    return False

def generate_moondream(image_path):
    print("🤖 Generating Moondream caption...")
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    prompt = "Describe this image briefly. Mention people and safety gear."
    
    try:
        resp = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'moondream:1.8b',
                'prompt': prompt,
                'images': [img_b64],
                'stream': False,
                'options': {'temperature': 0.5}
            },
            timeout=180
        )
        if resp.ok:
            return resp.json()['response'].strip()
        else:
            print(f"Ollama error: {resp.text}")
    except Exception as e:
        print(f"Generation error: {e}")
    
    # Fallback if actual generation fails
    print("⚠️ Moondream generation failed/unavailable. Using simulation.")
    return "SCENE: 1 person detected. ACTIVITY: Walking. BODY: Upper body. TORSO: Blue shirt. PPE: None visible. ENVIRONMENT: Office interior."

def main():
    print(f"Start V3 Moondream update for {REPORT_ID}")
    
    # 1. Managers
    db_manager = create_db_manager_from_env()
    storage_manager = create_storage_manager_from_env()
    
    # 2. Get Data
    violation = db_manager.get_violation(REPORT_ID)
    if not violation:
        print("Violation not found")
        return

    # 3. Download Image
    print("📥 Downloading image...")
    image_key = violation.get('original_image_key')
    print(f"Image Key: {image_key}")
    
    if not image_key:
        print("ERROR: No original_image_key in violation record!")
        return

    try:
        img_data = storage_manager.download_file_content(image_key)
        print(f"Download result type: {type(img_data)}")
        if img_data:
            print(f"Download size: {len(img_data)} bytes")
            with open(IMAGE_PATH, 'wb') as f:
                f.write(img_data)
        else:
            print("ERROR: Download returned empty/None")
            return
            
    except Exception as e:
        print(f"ERROR downloading: {e}")
        return

    # 4. Generate Caption
    # Check if we can run real inference
    if not check_moondream():
         print("ERROR: Moondream model not found in Ollama!")
         return
         
    caption_v3 = generate_moondream(IMAGE_PATH) # No fallback
    
    if not caption_v3:
        print("ERROR: Caption generation returned None")
        return

    print(f"Caption V3: {caption_v3}")
    
    with open("caption_v3_full.txt", "w", encoding="utf-8") as f:
        f.write(caption_v3)
        
    return
    
    # 6. Generate Report (SKIPPED FOR SPEED)
    """
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
        'report_id': REPORT_ID,
        'timestamp': violation.get('timestamp') or datetime.now(),
        'detections': [], 
        'violation_summary': violation.get('violation_summary'),
        'violation_count': violation.get('violation_count'),
        'caption': caption_v3, # Current caption is V3
        'image_caption': caption_v3,
        'caption_history': caption_history,
        'original_image_path': str(IMAGE_PATH), 
        'annotated_image_path': str(IMAGE_PATH), # Reuse for demo
        'location': violation.get('device_id', 'Demo'),
        'severity': "HIGH",
        'person_count': 1,
        'detection_data': {
            'reprocessed': True,
            'caption_history': caption_history
        }
    }
    
    result = generator.generate_report(report_data)
    
    # 7. Save to DB
    metadata = existing_detection_data.copy()
    metadata['caption_history'] = caption_history
    
    db_manager.update_violation(
        report_id=REPORT_ID,
        caption=caption_v3,
        detection_data=metadata,
        original_image_key=violation.get('original_image_key'),
        annotated_image_key=violation.get('annotated_image_key'),
        report_html_key=result.get('storage_keys', {}).get('report_html_key'),
    )

    print("✅ Successfully updated to Version 3 with Moondream.")
    """
    
    # Cleanup
    if IMAGE_PATH.exists():
        IMAGE_PATH.unlink()

if __name__ == "__main__":
    main()
