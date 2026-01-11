"""
Image Captioning with LLaVA via Ollama

Fast image captioning using Ollama's llava model.
Generates captions in seconds instead of minutes.

Usage:
    python caption_image.py path/to/image.jpg
"""
import sys
import requests
import base64
from pathlib import Path

# --- OLLAMA CONFIGURATION ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# Model options (in order of memory usage, lowest to highest):
# - "moondream:1.8b"  - Smallest, needs ~1.5GB RAM (for low RAM systems)
# - "llava-phi3:3.8b" - Medium, needs ~3.6GB RAM
# - "llava:7b"        - Large, needs ~4.3GB RAM
# - "llava:13b"       - Best quality, needs ~8GB+ RAM

# NOTE: Only ONE Ollama call can run at a time (controlled by semaphore in luna_app.py)
# This prevents VRAM exhaustion from concurrent calls
OLLAMA_MODEL = "llava-phi3:3.8b"  # Original model
TIMEOUT = 120  # 2 minutes timeout
# ---------------------------

def caption_image_llava(image_path):
    """
    Generate caption using Ollama's LLaVA model.
    
    Args:
        image_path: Path to image file
    
    Returns:
        Caption string or None if failed
    """
    print(f"Using Ollama LLaVA model: {OLLAMA_MODEL}")
    
    # Load and encode image to base64
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        print(f"Image loaded: {Path(image_path).name}")
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}")
        return None
    except Exception as e:
        print(f"Error loading image: {e}")
        return None
    
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
    
    # Call Ollama API
    try:
        print("Generating caption with Ollama...")
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': OLLAMA_MODEL,
                'prompt': prompt,
                'images': [image_base64],
                'stream': False,
                'options': {
                    'temperature': 0.6,
                    'num_predict': 250,  # Increased for complete sentences
                    'stop': ['\n\n\n']  # Stop at triple newlines to avoid mid-sentence cuts
                }
            },
            timeout=TIMEOUT
        )
        
        if not response.ok:
            print(f"Error: Ollama API returned {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        data = response.json()
        caption = data.get('response', '').strip()
        
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
            print("Error: Empty response from Ollama")
            return None
            
    except requests.exceptions.Timeout:
        print(f"Error: Request timed out after {TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to Ollama. Make sure Ollama is running.")
        print("Start Ollama with: ollama serve")
        return None
    except Exception as e:
        print(f"Error calling Ollama API: {e}")
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
    
    # Load and encode image to base64
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        print(f"Error loading image: {e}")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'Could not load image for validation'}
    
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

    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': OLLAMA_MODEL,
                'prompt': prompt,
                'images': [image_base64],
                'stream': False,
                'options': {
                    'temperature': 0.3,  # Lower temperature for more consistent classification
                    'num_predict': 30,   # Short response
                }
            },
            timeout=30  # Shorter timeout for quick check
        )
        
        if not response.ok:
            print(f"Environment validation failed: {response.status_code}")
            return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'API error - defaulting to valid'}
        
        data = response.json()
        answer = data.get('response', '').strip().upper()
        
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
            
    except requests.exceptions.Timeout:
        print("Environment validation timed out - defaulting to valid")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'Timeout'}
    except Exception as e:
        print(f"Environment validation error: {e}")
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
        print("Please ensure you have installed all required libraries:")
        print("pip install --upgrade transformers accelerate bitsandbytes torch pillow")
    except Exception as e:
        print(f"\nAn error occurred: {e}")