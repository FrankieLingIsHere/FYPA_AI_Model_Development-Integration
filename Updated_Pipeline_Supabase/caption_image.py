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
    
    # Build prompt for construction site safety analysis
    prompt = """You are a construction site safety inspector. Describe what you observe at this construction site in a natural narrative style.

Start directly describing the worker(s) and scene. DO NOT use phrases like "In the image" or "The image shows".

IMPORTANT GUIDELINES:
- HARDHAT vs HAIR: Be VERY careful distinguishing hardhats from hair! A hardhat is a rigid protective helmet, usually white/yellow/orange. Dark hair, styled hair, or hair accessories are NOT hardhats. Only report "wearing hardhat" if you see an actual rigid safety helmet.
- SAFETY BOOTS: ONLY mention safety boots if you can clearly see the person's feet/lower legs. If only upper body is visible, do NOT mention boots at all - say "feet not visible" instead.
- BODY VISIBILITY: Note which parts of body are visible (full body, upper half only, etc.) before commenting on PPE for those areas.

Describe in order:
- Worker(s): What are they doing? What body parts are visible?
- PPE Status: Be EXPLICIT and SPECIFIC:
  * For HEAD: Is there a rigid safety helmet/hardhat? (NOT hair or hair accessories)
  * For TORSO: Is there a high-visibility vest/jacket?
  * For HANDS: Are there work gloves?
  * For FEET: ONLY if feet are visible - are there safety boots?
  * For FACE: Are there goggles, mask, or face shield?
  * DO NOT assume PPE for body parts that are not visible in frame
- Work Environment: Construction area details, equipment, materials
- Safety Concerns: Any visible hazards or unsafe conditions

Treat this as a construction site even if it appears to be indoors or an office area. Write a flowing paragraph, not a numbered list."""
    
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
    
    # Quick environment classification prompt
    prompt = """Classify this image in ONE LINE. Is this:
A) CONSTRUCTION/INDUSTRIAL: construction site, factory, warehouse, workshop, manufacturing plant, work zone, any place with workers doing physical labor
B) OFFICE/COMMERCIAL: office building, retail store, meeting room, reception area
C) RESIDENTIAL/CASUAL: home, living room, bedroom, kitchen, park, beach, restaurant, casual setting with no work activity
D) OTHER: outdoor road, vehicle interior, unclear, or doesn't fit above categories

Answer with just the letter (A/B/C/D) followed by 2-3 words describing what you see. Example: "A - construction workers on scaffolding" or "C - person in living room" """

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