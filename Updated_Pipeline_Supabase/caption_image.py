"""
Image Captioning with Qwen2.5-VL via Ollama API

Fast and accurate image captioning using Qwen2.5-VL through Ollama.
Superior spatial reasoning, object counting, and PPE detection compared to LLaVA.

Usage:
    python caption_image.py path/to/image.jpg

Requirements:
    - Ollama installed and running
    - Qwen2.5-VL model: ollama pull qwen2.5vl
"""
import sys
import os
import base64
import requests
import json
from pathlib import Path

# --- QWEN2.5-VL CONFIGURATION ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5vl"  # Qwen2.5-VL vision model
TIMEOUT = 60  # Timeout for API requests
# ---------------------------

def encode_image_to_base64(image_path):
    """Convert image to base64 string for API."""
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def check_ollama_running():
    """Check if Ollama is running."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        return response.status_code == 200
    except:
        return False

def check_model_available(model_name):
    """Check if the specified model is available in Ollama."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return any(model_name in model.get('name', '') for model in models)
    except:
        pass
    return False

def caption_image_llava(image_path):
    """
    Generate caption using Qwen2.5-VL via Ollama API.
    
    Args:
        image_path: Path to image file
    
    Returns:
        Caption string or None if failed
    """
    # Check prerequisites
    if not check_ollama_running():
        print("Error: Ollama is not running. Please start Ollama first.")
        print("Run: ollama serve")
        return None
    
    if not check_model_available(MODEL_NAME):
        print(f"Error: Model '{MODEL_NAME}' not found in Ollama.")
        print(f"Please pull the model first: ollama pull {MODEL_NAME}")
        return None
    
    print(f"Using {MODEL_NAME} model via Ollama API")
    
    # Verify image exists
    if not Path(image_path).exists():
        print(f"Error: Image file not found at {image_path}")
        return None
    
    print(f"Image loaded: {Path(image_path).name}")
    
    # Build prompt for workplace safety analysis (NEUTRAL - no construction bias)
    prompt = """You are a workplace safety observer. Describe EXACTLY what you see in this image using a natural narrative style.

Start directly describing the person(s) and their actual environment. DO NOT use phrases like "In the image" or "The image shows".

CRITICAL - ANTI-MISCLASSIFICATION RULES:
========================================
1. HARDHAT vs HAIR/CAPS:
   - A HARDHAT is a RIGID, THICK protective helmet (typically white, yellow, orange, or bright colored)
   - HAIR (even dark, neat hair) is NOT a hardhat
   - Baseball caps, beanies, hoodies are NOT hardhats
   - If unsure, describe what you see: "person has dark hair" NOT "wearing hardhat"
   - ONLY say "hardhat" if you see a clearly identifiable safety helmet with rigid structure

2. ACTUAL ENVIRONMENT (do not fabricate):
   - If you see home furniture (sofa, TV stand, decorative items, carpets) → say "residential indoor setting"
   - If you see office desks, computers, cubicles → say "office environment"
   - If you see construction equipment, scaffolding, concrete → say "construction area"
   - DO NOT call a living room a "construction site" or "work zone"

3. VISIBILITY RULES:
   - SAFETY BOOTS: ONLY mention if feet/ankles are clearly visible. If not visible, say "lower body not visible"
   - GLOVES: Only if hands are clearly visible
   - If only head/shoulders visible, do NOT speculate about lower body PPE

4. PPE MUST BE OBVIOUS:
   - Safety Vest: Bright fluorescent vest with reflective strips
   - Hardhat: Rigid helmet with chin strap area visible
   - Safety Boots: Sturdy work boots (steel toe style)
   - Goggles: Clear protective eyewear
   - DO NOT report PPE unless it is CLEARLY VISIBLE and IDENTIFIABLE

Describe in order:
- Person(s): What are they doing? What body parts are visible (full body / upper half / head only)?
- Clothing/PPE: Describe ONLY what is actually visible and certain
  * HEAD: Describe hair/headwear. Only say "hardhat" if you see a rigid safety helmet
  * TORSO: Describe shirt/jacket. Only say "safety vest" if fluorescent with reflective strips
  * HANDS: Describe if visible. Only say "gloves" if work gloves are clearly visible
  * FEET: If visible, describe footwear. If not visible, state "lower body not visible"
  * FACE: Goggles/mask only if clearly present
- Actual Environment: Describe the real setting (residential/office/industrial/outdoor/etc.)
- Safety Context: Any visible hazards IF this is actually a work environment

Be accurate and honest. Do not assume this is a construction site unless you see construction indicators. Write a flowing paragraph, not a numbered list."""
    
    # Encode image to base64
    try:
        image_base64 = encode_image_to_base64(image_path)
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None
    
    # Call Ollama API
    try:
        print(f"Generating caption with {MODEL_NAME}...")
        
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False,
            "options": {
                "temperature": 0.6,
                "num_predict": 250
            }
        }
        
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        
        result = response.json()
        caption = result.get('response', '').strip()
        
        if caption:
            # Clean up common prefixes
            prefixes_to_remove = [
                "In the image, ",
                "In the image ",
                "The image shows ",
                "The image depicts ",
                "This image shows ",
                "This image depicts ",
                "In this image, ",
                "In this image "
            ]
            
            for prefix in prefixes_to_remove:
                if caption.startswith(prefix):
                    caption = caption[len(prefix):]
                    # Capitalize first letter after removal
                    if caption:
                        caption = caption[0].upper() + caption[1:]
                    break
            
            # Ensure complete sentence - truncate to last period if incomplete
            if caption and not caption.endswith(('.', '!', '?')):
                # Find last complete sentence
                last_period = caption.rfind('.')
                if last_period > 0:
                    caption = caption[:last_period + 1]
                else:
                    # If no period found, add one
                    caption = caption + '.'
            
            print("Caption generation complete!")
            return caption
        else:
            print("Error: Empty response from model")
            return None
            
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to Ollama API. Make sure Ollama is running.")
        print("Run: ollama serve")
        return None
    except requests.exceptions.Timeout:
        print(f"Error: Request timed out after {TIMEOUT} seconds")
        return None
    except Exception as e:
        print(f"Error during caption generation: {e}")
        return None


def validate_work_environment(image_path):
    """
    Quick check to determine if the image shows a valid work environment
    where PPE monitoring is appropriate (construction site, factory, warehouse, etc.).
    
    CLASSIFICATION LOGIC:
    =====================
    The LLaVA model classifies the scene into 4 categories:
    
    A) CONSTRUCTION/INDUSTRIAL → is_valid=TRUE, confidence=HIGH
       - Construction sites, factories, warehouses, workshops
       - Manufacturing plants, work zones, industrial areas
       - Any place where PPE is typically required
    
    B) OFFICE/COMMERCIAL → is_valid=TRUE, confidence=MEDIUM  
       - Office buildings, retail stores, meeting rooms
       - These environments MAY require PPE in certain areas
       - Still processed (not skipped)
    
    C) RESIDENTIAL/CASUAL → is_valid=FALSE, confidence=HIGH
       - Homes, living rooms, bedrooms, kitchens
       - Parks, beaches, restaurants, casual settings
       - These are SKIPPED (no report generated)
    
    D) OTHER/UNCLEAR → is_valid=TRUE, confidence=LOW
       - Outdoor roads, vehicle interiors, unclear scenes
       - Benefit of doubt - still processed
    
    ONLY Category C causes violations to be SKIPPED.
    Categories A, B, D all proceed with normal processing.
    
    Args:
        image_path: Path to image file
    
    Returns:
        dict with:
            - is_valid: bool - True if this is a work environment (A, B, D) or False (C only)
            - confidence: str - 'high', 'medium', 'low'
            - environment_type: str - type of environment detected
            - reason: str - explanation
    """
    print(f"Validating work environment...")
    
    # Verify image exists
    if not Path(image_path).exists():
        print(f"Error: Image not found at {image_path}")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'Image file not found'}
    
    # Quick environment classification prompt - STRICT scene recognition
    prompt = """Look at this image carefully and classify the ACTUAL environment you see.

CHECK FOR THESE INDICATORS:

A) CONSTRUCTION/INDUSTRIAL:
   ✓ Scaffolding, concrete, lumber, construction equipment
   ✓ Factory machinery, assembly lines, warehouses with industrial shelving
   ✓ Visible construction materials, work site barriers, heavy machinery
   ✓ People wearing multiple PPE items in an active work zone
   → Choose A ONLY if you see CLEAR industrial/construction indicators

B) OFFICE/COMMERCIAL:
   ✓ Office desks, computers, cubicles, meeting rooms
   ✓ Retail displays, store shelves, checkout counters
   ✓ Professional indoor setting with business furniture

C) RESIDENTIAL/CASUAL:
   ✓ Home furniture: sofas, TV stands, beds, dining tables, home decor
   ✓ Residential kitchen, living room, bedroom, home interior
   ✓ Parks, beaches, restaurants, cafes, casual outdoor settings
   ✓ Person at home (even if wearing safety gear for testing purposes)
   → Choose C if this looks like someone's HOME or casual setting

D) OTHER:
   ✓ Vehicle interior, outdoor road/street, unclear background
   ✓ Cannot determine the setting

IMPORTANT: Do NOT classify a residential living room as construction site just because someone is wearing safety gear! The ENVIRONMENT determines the category, not the person's clothing.

Answer with just the letter (A/B/C/D) followed by 2-4 words. Examples:
- "A - construction site with scaffolding"
- "C - person in living room"
- "C - home interior with sofa"
- "B - office desk area" """

    # Encode image to base64
    try:
        image_base64 = encode_image_to_base64(image_path)
    except Exception as e:
        print(f"Error encoding image: {e}")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'Image encoding failed'}

    try:
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 30
            }
        }
        
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        
        result = response.json()
        answer = result.get('response', '').strip().upper()
        
        print(f"Environment check result: {answer}")
        
        # Parse the response - ONLY category C causes is_valid=False
        if answer.startswith('A'):
            return {
                'is_valid': True,
                'confidence': 'high',
                'environment_type': 'construction/industrial',
                'reason': answer
            }
        elif answer.startswith('B'):
            # Office environments may still need PPE in certain areas
            return {
                'is_valid': True,
                'confidence': 'medium',
                'environment_type': 'office/commercial',
                'reason': answer
            }
        elif answer.startswith('C'):
            return {
                'is_valid': False,
                'confidence': 'high',
                'environment_type': 'residential/casual',
                'reason': answer
            }
        elif answer.startswith('D'):
            return {
                'is_valid': True,
                'confidence': 'low',
                'environment_type': 'other',
                'reason': answer
            }
        else:
            # Couldn't parse - default to valid with low confidence
            return {
                'is_valid': True,
                'confidence': 'low',
                'environment_type': 'unknown',
                'reason': f'Unparseable response: {answer[:50]}'
            }
            
    except Exception as e:
        print(f"Environment validation error: {e} - defaulting to valid")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python caption_image.py path/to/image.jpg")
        sys.exit(1)
        
    image_path = sys.argv[1]

    try:
        # First validate environment
        env_result = validate_work_environment(image_path)
        print(f"\nEnvironment Validation:")
        print(f"  Valid work environment: {env_result['is_valid']}")
        print(f"  Confidence: {env_result['confidence']}")
        print(f"  Type: {env_result['environment_type']}")
        print(f"  Reason: {env_result['reason']}")
        
        if env_result['is_valid']:
            print("\n--- Generating full caption ---")
            caption = caption_image_llava(image_path)
            if caption:
                print("Caption:", caption)
        else:
            print("\n⚠️ Skipping caption - not a valid work environment")
            
    except ImportError as e:
        print(f"\nImportError: {e}")
        print("Please ensure you have installed required packages:")
        print("pip install requests")
        print("\nAlso ensure Ollama is installed and the model is pulled:")
        print(f"ollama pull {MODEL_NAME}")
    except Exception as e:
        print(f"\nAn error occurred: {e}")