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
    
    # Build prompt based on model capability
    if 'moondream' in str(model):
        # HYPER-SPECIFIC SAFETY ASSESSMENT PROMPT
        # Designed to capture unique physical geometry and inter-object relationships
        prompt = """You are a JKR-certified Safety Officer conducting a STRICT site inspection. Analyze this image and write a HYPER-SPECIFIC safety assessment.

Your response MUST capture UNIQUE SCENE DETAILS, not generic observations:

1. SCENE GEOMETRY:
   - Environment type (construction site, roadside, industrial, excavation, etc.)
   - Ground condition: Is it level/sloped/unstable? Estimate incline angle if visible.
   - Key objects and their SPATIAL RELATIONSHIPS (distances, proximity to workers)

2. PERSONNEL ANALYSIS (for EACH person):
   - Exact position: Near edge? On slope? In traffic path? Under suspended load?
   - Specific activity: Working? Supervising? ON MOBILE PHONE? (distraction = behavioral violation)
   - Clothing description (colors, type)
   - PPE STATUS (STRICT CHECK):
     * HEAD: Rigid MS 183 helmet with chin strap? (Sun hats/caps = NON-COMPLIANT)
     * VEST: Neon MS 1731 high-viz as OUTERMOST layer?
     * FEET: Safety boots visible?
     * Other: Gloves, goggles, harness if at height

3. MATERIAL HAZARDS:
   - Are materials (logs, pipes, bricks) properly stacked or UNSECURED?
   - On level ground or INCLINE/SLOPE (gravity roll risk)?
   - Stop-blocks or restraints present?

4. TRAFFIC & EXCLUSION ZONES:
   - Are workers separated from vehicle paths?
   - Any TRAFFIC CONES, barriers, or "Men at Work" signs?
   - Is there an EXCLUSION ZONE around heavy materials or equipment?

5. HOUSEKEEPING (BOWEC Reg. 26):
   - Debris, scattered materials, trip hazards?
   - Tool storage condition
   - Are walkways clear?

6. VEHICLE STATUS:
   - Any trucks/equipment: Parked? Active loading/unloading?
   - Engine running? Chocked wheels if on slope?

Write as ONE DETAILED PARAGRAPH. Describe EXACTLY what you see with specific details about distances, angles, positions, and inter-object relationships. Avoid generic phrases like "near edge" - instead say "within 2 meters of unsecured log pile"."""
    else:
        # LLaVA/Phi3 can handle structured output better
        prompt = """You are a JKR-certified Safety Officer. Analyze this image for strict OSHA 1994 and BOWEC 1986 compliance. Provide a DETAILED, STRUCTURED description.

REQUIRED OUTPUT FORMAT:
=======================
Start with: "SCENE: [number] person(s) detected."

Then for EACH person, describe in this order:
1. ACTIVITY: What are they doing? (e.g., "Welding", "Working at height >2m", "Excavating trench >1.5m").
2. POSITION: Where are they? (e.g., "On scaffold", "Near open edge", "Under suspended load").
3. BODY VISIBILITY: (full body / upper half / head only).
4. HEAD PROTECTION (MS 183):
   - Helmet present? (Yes/No)
   - Chin strap visible/fastened? (CRITICAL for JKR)
   - Color? (White=Supervisor/Yellow=Worker)
5. HI-VIZ VEST (MS 1731):
   - Present? (Yes/No)
   - Color? (Neon Yellow/Orange/Green)
   - Retroreflective strips visible?
6. FALL PROTECTION (MS 2311) [If >2m height]:
   - Full-body harness present?
   - Lanyard anchored? (Safe/Unsafe tie-off)
7. HANDS/FEET: Gloves? Safety boots (reinforced toe)?
8. FACE: Masks/goggles?

End with: "ENVIRONMENT: [Brief description - note Hazards like 'Unshored trench', 'Loose scaffolding', 'Trip hazards', 'Poor housekeeping']"

CRITICAL JKR MONITORING RULES:
==============================
1. HEAD: Rigid helmet required. Caps/Hats = NON-COMPLIANCE. Chin strap check is mandatory.
2. VEST: Must be outermost layer. Must be high-visibility neon.
3. HEIGHT: If feet >2m off ground, look for HARNESS + ANCHOR.
4. EXCAVATION: If trench >1.5m, look for SHORING. Spoil heap >0.6m from edge?
5. HOUSEKEEPING: Cables, debris, oil spills?

Analyze now using strict JKR/OSHA standards:"""

    import time
    timestamp_seed = int(time.time() * 1000)
    
    # Call Ollama API
    try:
        print(f"Generating caption with Ollama (Image size: {len(image_base64)} chars)...")
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': model,
                'prompt': prompt, # Salt removed to improve model compatibility
                'context': [],  # FORCE STATELESS: Empty context prevents caching of previous conversations
                'images': [image_base64],
                'stream': False,
                'options': {
                    'temperature': 0.3,  # Increased for more variety in descriptions
                    'num_predict': 500,
                    'stop': ['\n\n\n']
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
            
            # Remove bullet points and list markers (preserve structure)
            # caption = re.sub(r'^[\-\*\•]\s*', '', caption, flags=re.MULTILINE) 
            
            # Merge multiple spaces and newlines
            caption = re.sub(r'\s+', ' ', caption).strip()
            
            # Ensure complete sentence - truncate to last period if incomplete
            if caption and not caption.endswith(('.', '!', '?')):
                last_period = caption.rfind('.')
                if last_period > 0:
                    caption = caption[:last_period + 1]
                else:
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
    Quick check to determine if the image shows a valid work environment.
    Strictly filters out residential/home settings.
    """
    print(f"Validating work environment...")
    
    # Find available VLM model with automatic fallback
    model = find_working_model()
    if not model:
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'VLM not available - defaulting to valid'}
    
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        print(f"Error loading image: {e}")
        return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'Could not load image for validation'}
    
    # Quick environment classification prompt - STRICT with CLOSE-UP HANDLERS
    prompt = """Classify the ENVIRONMENT/BACKGROUND. IGNORE the person's clothing.

RULES:
1. FOCUS ON BACKGROUND: Look past the person. Walls, furniture, equipment?
2. CLOSE-UPS/BLURRY: If the background is blurry or just a wall/ceiling (Close-up face shot) -> Default to D (Other) or C (Residential) if ANY home hint exists.
3. ANTI-BIAS: Do NOT assume "Construction" just because of a hardhat.

CATEGORIES (Check in order):

C - RESIDENTIAL (Highest Priority - Home Context):
   - ANY sign of home: Sofa, Couch, TV, Bed, Wardrobe, Curtain
   - Kitchen cabinets, Fridge, Carpet, Rug
   - Living room wall decor, family photos
   - Home hallway, staircase, wooden flooring
   -> If you see a sofa or TV, it IS Residential, even if the person looks like a worker.

B - OFFICE/COMMERCIAL:
   - Computer screens, Keyboards, Whiteboards
   - Office desks, Cubicles, Meeting rooms
   - Retail shelves

A - CONSTRUCTION/INDUSTRIAL (Require PROOF):
   - Scaffolding, Excavators, Cranes
   - Concrete mixer, Bricks, Lumber stacks
   - Industrial pipes, Factory machinery
   - Warehouse racking
   -> MUST see actual heavy equipment or raw materials.
   -> A plain wall or door is NOT construction.

D - OTHER/UNCLEAR:
   - Close-up face shot with no background context
   - Blurry/Indistinguishable background
   - Car interior
   - Outdoor street/sky only

ANSWER FORMAT: Just the letter and 2-5 words.
Examples:
"C - living room couch"
"D - close-up face unclear background"
"A - scaffolding and concrete"
"B - office computer"

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
                    'temperature': 0.05,  # Very strict
                    'num_predict': 25,
                }
            },
            timeout=30
        )
        
        if not response.ok:
            print(f"Environment validation failed: {response.status_code}")
            return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': 'API error - defaulting to valid'}
        
        data = response.json()
        answer = data.get('response', '').strip().upper()
        
        print(f"Environment check result: {answer}")
        
        if answer.startswith('A'):
            return {'is_valid': True, 'confidence': 'high', 'environment_type': 'construction/industrial', 'reason': answer}
        elif answer.startswith('B'):
            return {'is_valid': True, 'confidence': 'medium', 'environment_type': 'office/commercial', 'reason': answer}
        elif answer.startswith('C'):
            return {'is_valid': False, 'confidence': 'high', 'environment_type': 'residential/casual', 'reason': answer}
        elif answer.startswith('D'):
            return {'is_valid': True, 'confidence': 'low', 'environment_type': 'other/unclear', 'reason': answer}
        else:
            return {'is_valid': True, 'confidence': 'low', 'environment_type': 'unknown', 'reason': f'Unparseable: {answer[:30]}'}
            
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