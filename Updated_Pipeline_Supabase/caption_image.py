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
    {"name": "llava:7b", "description": "Full LLaVA model, ~4GB RAM", "min_ram_gb": 4},
]

# Cache the working model to avoid repeated checks
_working_model = None
_model_check_done = False

TIMEOUT = 120  # 2 minutes timeout
MAX_RETRIES = 3  # Number of retries for empty responses
RETRY_DELAY = 2  # Seconds between retries
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
        # Moondream is small and struggles with complex formatting instructions
        prompt = """Describe this workplace scene in detail. Start with "A worker...". Mention activities, safety gear (hardhats, vests), and environment."""
    else:
        # LLaVA/Phi3 can handle structured output better
        prompt = """You are a workplace safety observer. Analyze this image and provide a DETAILED, STRUCTURED description.

REQUIRED OUTPUT FORMAT:
=======================
Start with: "SCENE: [number] person(s) detected."

Then for EACH person, describe in this order:
1. ACTIVITY: What are they doing? (CRITICAL - BE SPECIFIC. Avoid just "standing". Say "Welding a pipe", "Climbing a ladder", "Holding a blueprint", "Hammering a nail".)
2. POSITION: Where are they in the frame? (left/center/right)
3. BODY VISIBILITY: What body parts are visible? (full body / upper half / head only)
4. HEAD: Hair/headwear. ONLY say "hardhat" if you see a RIGID safety helmet.
5. TORSO: Clothing. ONLY say "safety vest" if fluorescent with reflective strips. **If torso not visible, say "Not visible".**
6. HANDS: **If hands NOT visible, say "Not visible".** ONLY say "gloves" if clearly seen.
7. FEET: **If feet NOT visible, say "Not visible".** DO NOT halluciante boots if feet aren't there.
8. FACE: Masks/goggles (only if clearly visible)

End with: "ENVIRONMENT: [brief 2-4 word description]"

CRITICAL ANTI-HALLUCINATION RULES:
==================================
1. VISIBILITY COMPLIANCE:
   - If BODY VISIBILITY is "Head only" -> TORSO, HANDS, FEET must be "Not visible".
   - If BODY VISIBILITY is "Upper half" -> FEET must be "Not visible".
   - DO NOT describe clothing/PPE for missing body parts.

2. HARDHAT vs HAIR:
   - Rigid helmet = Hardhat.
   - Hair/Cap/Beanie = NOT Hardhat.

3. ENVIRONMENT TRUTH:
   - Sofa/Couch/TV/Bed = "residential indoor".
   - Office desk/Computer = "office".
   - ONLY say "construction site" if you see heavy machinery/scaffolding/raw materials.

1. EXAMPLE (Partial Visibility):
"SCENE: 1 person(s) detected. Person 1 is in center foreground, head and shoulders only. Facing camera. Has short dark hair, no hardhat. Torso is partially visible wearing a grey t-shirt, no safety vest. Hands not visible. Feet not visible. Face is clear, no mask. ENVIRONMENT: residential room with couch."

Analyze now:"""

    import time
    timestamp_seed = int(time.time() * 1000)
    
    # Call Ollama API with retry logic
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Generating caption with Ollama (Image size: {len(image_base64)} chars)... Attempt {attempt + 1}/{MAX_RETRIES}")
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
                        'num_predict': 250,
                        'stop': ['\n\n\n']
                    }
                },
                timeout=TIMEOUT
            )
            
            if not response.ok:
                print(f"Error: Ollama API returned {response.status_code}")
                print(f"Response: {response.text}")
                if attempt < MAX_RETRIES - 1:
                    print(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                    continue
                return "Caption generation failed - API error."
            
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
                print(f"Warning: Empty response from Ollama (attempt {attempt + 1}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES - 1:
                    print(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    print("Error: Empty response from Ollama after all retries")
                    return "Caption generation failed - model returned empty response. Please try again."
                
        except requests.exceptions.Timeout:
            print(f"Error: Request timed out after {TIMEOUT} seconds")
            if attempt < MAX_RETRIES - 1:
                print(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
                continue
            return "Caption generation timed out. Please try again."
        except requests.exceptions.ConnectionError:
            print("Error: Could not connect to Ollama. Make sure Ollama is running.")
            print("Start Ollama with: ollama serve")
            return "Could not connect to Ollama - please ensure it is running."
        except Exception as e:
            print(f"Error calling Ollama API: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return f"Caption generation error: {str(e)[:100]}"

    # If we get here, all retries failed
    return "Caption generation failed after multiple attempts."


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