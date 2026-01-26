import sys
import json
import os
from pathlib import Path
from datetime import datetime
import pipeline.config as config_module
from pipeline.backend.core.report_generator import ReportGenerator

# Import Caption Generator
try:
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    CAPTION_AVAILABLE = True
except ImportError:
    CAPTION_AVAILABLE = False
    print("Warning: CaptionGenerator not available")

def load_or_recover_data(report_id):
    print(f"Loading/Recovering data for {report_id}...")
    
    violations_dir = Path("pipeline/violations")
    report_dir = violations_dir / report_id
    meta_path = report_dir / "metadata.json"
    
    # Try current directory first
    if not meta_path.exists():
        # Try finding it relative to cwd
        meta_path = Path.cwd() / "pipeline/violations" / report_id / "metadata.json"
        
    if not meta_path.exists():
        print(f"Metadata not found at {meta_path}. Checking for recovery files...")
        
        # Look for caption.txt
        caption_path = report_dir / "caption.txt"
        if not caption_path.exists():
             caption_path = Path.cwd() / "pipeline/violations" / report_id / "caption.txt"
             
        caption_text = ""
        if caption_path.exists():
            print(f"Found caption.txt at {caption_path}.")
            with open(caption_path, 'r') as f:
                caption_text = f.read().strip()
        else:
            print("Caption.txt not found. Attempting to generate new caption...")
            # Try to find original image
            image_path = report_dir / "original.jpg"
            if not image_path.exists():
                image_path = Path.cwd() / "pipeline/violations" / report_id / "original.jpg"
            
            if image_path.exists() and CAPTION_AVAILABLE:
                print(f"Found image at {image_path}. Running VLM...")
                try:
                    # Initialize Caption Generator
                    cap_gen = CaptionGenerator(vars(config_module))
                    caption_text = cap_gen.generate_caption(str(image_path))
                    print(f"Generated New Caption: {caption_text[:50]}...")
                except Exception as e:
                    print(f"Failed to generate caption: {e}")
            else:
                print("Could not find image or caption generator not available.")
        
        if caption_text:
            # Construct data for REAL inference (no pre-filled risks/persons)
            data = {
                'report_id': report_id,
                'timestamp': datetime.now().isoformat(), 
                'violation_summary': "Violation detected (recovered)",
                'caption': caption_text,
                'detections': [], # Lost detections, but NLP will infer from caption
                'person_count': 1, 
                'violation_count': 1, 
                'severity': 'HIGH',
                'original_image_path': str(report_dir / "original.jpg"),
                'annotated_image_path': str(report_dir / "annotated.jpg")
            }
            return data 
        else:
             print(f"Error: Could not recover enough data to regenerate.")
             return None
    
    print(f"Loading metadata from {meta_path}")
    with open(meta_path, 'r') as f:
        data = json.load(f)
    
    return data

def force_regen(report_id):
    print(f"Force regenerating report {report_id} (REAL INFERENCE)...")
    
    # 1. Setup
    try:
        # Initialize with config
        generator = ReportGenerator(vars(config_module))
    except Exception as e:
        print(f"Failed to init generator: {e}")
        return

    # 2. Get Data
    data = load_or_recover_data(report_id)
    if not data:
        return
        
    # Ensure timestamp is datetime object
    if isinstance(data.get('timestamp'), str):
         try:
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
         except:
            data['timestamp'] = datetime.now()
    if not data.get('timestamp'):
         data['timestamp'] = datetime.now()
        
    # 3. Regenerate
    try:
        # This calls generate_report which calls _call_ollama_api internally
        # Since we REMOVED the monkey patch, it will hit the real API
        result = generator.generate_report(data)
        print("Regeneration complete.")
        print(f"New HTML: {result.get('html')}")
    except Exception as e:
        print(f"Error during generation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Regenerate 201405 (Recovered one)
    # force_regenerate("20260125_201405")
    # Uncomment to try the other one
    force_regen("20260125_201408")
