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
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"

# Model fallback order (will try in order until one works)
# Prioritize CPU-friendly models first for broader compatibility
OLLAMA_MODELS = [
    {"name": "moondream:1.8b", "description": "CPU-friendly, ~1.5GB RAM - recommended", "min_ram_gb": 2},
    {"name": "llava-phi3:3.8b", "description": "Higher quality, ~3.6GB RAM - needs more resources", "min_ram_gb": 4},
]

# Cache the working model to avoid repeated checks
_working_model = None
_model_check_done = False

TIMEOUT = 120  # 2 minutes timeout
# ---------------------------

def check_ollama_running():
    """Check if Ollama is running and accessible."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        return response.ok
    except:
        return False

def get_installed_models():
    """Get list of installed Ollama models."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=10)
        if response.ok:
            data = response.json()
            return [m.get('name', '') for m in data.get('models', [])]
    except:
        pass
    return []

def find_working_model():
    """Find the first available VLM model from the fallback list."""
    global _working_model, _model_check_done
    
    if _model_check_done and _working_model:
        return _working_model
    
    if not check_ollama_running():
        print("❌ Ollama is not running!")
        print("   Start Ollama with: ollama serve")
        print("   Download from: https://ollama.ai")
        return None
    
    installed = get_installed_models()
    print(f"Installed Ollama models: {installed}")
    
    for model in OLLAMA_MODELS:
        model_name = model["name"]
        # Check if model (or partial match) is installed
        if any(model_name.split(':')[0] in m for m in installed):
            print(f"✓ Found VLM model: {model_name}")
            _working_model = model_name
            _model_check_done = True
            return model_name
    
    # No models found - provide helpful message
    print("❌ No VLM models installed!")
    print("   Install a model with one of these commands:")
    print("   ollama pull moondream:1.8b   (lighter, ~1.5GB, good for CPU)")
    print("   ollama pull llava-phi3:3.8b  (better quality, ~3.6GB)")
    
    _model_check_done = True
    return None

def caption_image_llava(image_path):
    """
    Generate caption using Ollama's LLaVA model.
    
    Args:
        image_path: Path to image file
    
    Returns:
        Caption string or None if failed
    """
    # Find available VLM model with automatic fallback
    model = find_working_model()
    if not model:
        return "Image captioning not available - No VLM model installed. Run: ollama pull moondream:1.8b"
    
    print(f"Using Ollama VLM model: {model}")
    
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
    
    # Build prompt for workplace safety analysis (DETAILED and STRUCTURED)
    prompt = """You are a workplace safety observer. Analyze this image and provide a DETAILED, STRUCTURED description.

REQUIRED OUTPUT FORMAT:
=======================
Start with: "SCENE: [number] person(s) detected."

Then for EACH person, describe in this order:
1. POSITION: Where are they in the frame? (left/center/right, foreground/background)
2. BODY VISIBILITY: What body parts are visible? (full body / upper half only / head and shoulders only)
3. ACTIVITY: What are they doing? (standing, walking, working, sitting, etc.)
4. HEAD: Hair color/style, headwear. ONLY say "hardhat" if you see a RIGID safety helmet
5. TORSO: Clothing color and type. ONLY say "safety vest" if fluorescent with reflective strips
6. HANDS: If visible, describe. ONLY say "gloves" if work gloves are clearly visible
7. FEET: If visible, describe footwear. If NOT visible, say "feet not visible"
8. FACE: Any face covering, goggles, mask (only if clearly visible)

End with: "ENVIRONMENT: [brief 2-4 word description of setting]"

CRITICAL RULES:
===============
1. HARDHAT IDENTIFICATION:
   - HARDHAT = RIGID, THICK protective helmet (white, yellow, orange, bright colors)
   - Dark hair is NOT a hardhat
   - Baseball caps, beanies, hoodies are NOT hardhats
   - If uncertain, describe actual appearance: "dark hair" NOT "wearing hardhat"

2. COUNT ACCURACY:
   - Count EVERY person visible in the image
   - If partially visible persons exist, include them with "(partially visible)"

3. ENVIRONMENT ACCURACY:
   - Home furniture (sofa, TV, carpets) → "residential indoor"
   - Office desks, computers → "office environment"
   - Scaffolding, construction materials → "construction site"
   - Factory equipment → "industrial facility"

4. DO NOT FABRICATE:
   - Only describe what you can clearly see
   - If something is unclear or not visible, say so explicitly
   - Never guess or assume PPE that isn't clearly visible

EXAMPLE OUTPUT:
===============
"SCENE: 2 person(s) detected. Person 1 is positioned at center-left foreground, full body visible. Standing and appears to be working. Has short dark hair with no headwear. Wearing a blue work shirt, no safety vest visible. Hands are visible holding tools, wearing yellow work gloves. Feet visible with brown work boots. No face protection. Person 2 is positioned at right background, upper half visible only. Standing and observing. Wearing a white hardhat clearly visible. Orange safety vest with reflective strips. Hands not visible, feet not visible. ENVIRONMENT: construction site outdoors."

Now analyze the image and provide your structured description:"""
    
    # Call Ollama API
    try:
        print("Generating caption with Ollama...")
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': model,
                'prompt': prompt,
                'images': [image_base64],
                'stream': False,
                'options': {
                    'temperature': 0.4,  # Lower temperature for more accurate output
                    'num_predict': 200,  # Shorter, more focused output
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
            # Clean up brackets and raw formatting
            import re
            
            # Remove leading/trailing brackets
            caption = caption.strip('[]{}')
            caption = caption.strip()
            
            # Remove quotes
            caption = caption.replace('"', '').replace("'", "")
            
            # Remove any remaining bracket patterns like [text] or {text}
            caption = re.sub(r'\[([^\]]*)\]', r'\1', caption)
            caption = re.sub(r'\{([^\}]*)\}', r'\1', caption)
            
            # Remove bullet points and list markers
            caption = re.sub(r'^[\-\*\•]\s*', '', caption, flags=re.MULTILINE)
            caption = re.sub(r'\n[\-\*\•]\s*', ' ', caption)
            
            # Clean up common prefixes
            prefixes_to_remove = [
                "In the image, ",
                "In the image ",
                "The image shows ",
                "The image depicts ",
                "This image shows ",
                "This image depicts ",
                "In this image, ",
                "In this image ",
                "Here is ",
                "Here's ",
            ]
            
            for prefix in prefixes_to_remove:
                if caption.lower().startswith(prefix.lower()):
                    caption = caption[len(prefix):]
                    # Capitalize first letter after removal
                    if caption:
                        caption = caption[0].upper() + caption[1:]
                    break
            
            # Merge multiple spaces and newlines
            caption = re.sub(r'\s+', ' ', caption).strip()
            
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
    
    # Find available VLM model with automatic fallback
    model = find_working_model()
    if not model:
        # No model available - default to valid to allow processing
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'VLM not available - defaulting to valid'}
    
    # Load and encode image to base64
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        print(f"Error loading image: {e}")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'Could not load image for validation'}
    
    # Quick environment classification prompt - STRICT scene recognition with tie-breakers
    prompt = """Classify the ENVIRONMENT/BACKGROUND in this image. IGNORE what the person is wearing - focus ONLY on the surroundings.

PRIORITY CLASSIFICATION RULES (check in order):

1. LOOK AT THE BACKGROUND FIRST:
   - What furniture or objects are visible?
   - What does the floor/walls look like?
   - Any equipment, machinery, or work materials?

2. CLASSIFICATION HIERARCHY (if multiple match, use FIRST match):

   C - RESIDENTIAL (check FIRST):
   If you see ANY of these, answer C immediately:
   - Sofa, couch, armchair, coffee table
   - TV, TV stand, home entertainment
   - Bed, bedroom furniture, wardrobe
   - Home kitchen cabinets, refrigerator, home appliances
   - Carpet, home curtains, family photos, home decor
   - Dining table in home setting
   → Even if person wears safety gear, C if background is HOME

   B - OFFICE/COMMERCIAL:
   - Office desks, computer monitors, cubicles
   - Conference tables, meeting rooms
   - Retail store shelves, checkout counters
   - Professional workspace furniture

   A - CONSTRUCTION/INDUSTRIAL:
   - Scaffolding, concrete, bare walls under construction
   - Heavy machinery, cranes, forklifts
   - Lumber, bricks, construction materials
   - Factory equipment, assembly lines
   - Warehouse with industrial racking
   → ONLY choose A if you see ACTUAL construction/industrial materials

   D - OTHER/UNCLEAR:
   - Vehicle interior, outdoor street/road
   - Cannot determine the background setting

TIE-BREAKER RULES:
- If scene has BOTH home furniture AND some work tools → C (home workshop)
- If scene looks like home but person wears PPE → C (testing at home)
- If uncertain between multiple options → Choose the LESS industrial option

ANSWER FORMAT: Just the letter and 3-5 words describing what you see in the BACKGROUND.
Examples:
"C - living room with sofa"
"C - home interior with TV"
"A - construction site scaffolding"
"B - office with computer desks"
"D - outdoor street scene"

Your classification:"""

    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': model,
                'prompt': prompt,
                'images': [image_base64],
                'stream': False,
                'options': {
                    'temperature': 0.1,  # Very low temperature for consistent classification
                    'num_predict': 25,   # Short response
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