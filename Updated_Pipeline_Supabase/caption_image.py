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
import time
import hashlib
from pathlib import Path

# --- PROVIDER CONFIGURATION ---
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_TAGS_URL = os.getenv('OLLAMA_TAGS_URL', f"{OLLAMA_BASE_URL}/api/tags")
OLLAMA_MODEL_NAME = os.getenv('OLLAMA_VISION_MODEL', 'qwen2.5vl')

VISION_PROVIDER_ORDER = [
    provider.strip().lower()
    for provider in os.getenv('VISION_PROVIDER_ORDER', 'model_api,gemini,ollama').split(',')
    if provider.strip()
]

# OpenAI-compatible model API (e.g., first-party/hosted Qwen, Moondream, Llama providers)
VISION_API_URL = os.getenv('VISION_API_URL', '').strip()
VISION_API_KEY = os.getenv('VISION_API_KEY', '').strip()
VISION_API_MODEL = os.getenv('VISION_API_MODEL', '').strip()

# Google Gemini fallback
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_VISION_MODEL = os.getenv('GEMINI_VISION_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')).strip()

TIMEOUT = int(os.getenv('VISION_TIMEOUT', '60'))

# Lightweight response cache + provider diagnostics to reduce repeated API calls.
VISION_CACHE_ENABLED = os.getenv('VISION_CACHE_ENABLED', 'true').lower() == 'true'
VISION_CACHE_TTL_SECONDS = int(os.getenv('VISION_CACHE_TTL_SECONDS', '900'))
VISION_CACHE_MAX_SIZE = int(os.getenv('VISION_CACHE_MAX_SIZE', '128'))
GEMINI_QUOTA_COOLDOWN_SECONDS = int(os.getenv('GEMINI_QUOTA_COOLDOWN_SECONDS', '900'))

_VISION_RESPONSE_CACHE = {}
_LAST_PROVIDER_FAILURES = []
_gemini_quota_backoff_until = 0.0
# ---------------------------


def _record_provider_failure(provider: str, reason: str):
    """Record provider-level failure reasons for user-facing diagnostics."""
    _LAST_PROVIDER_FAILURES.append({
        'provider': provider,
        'reason': str(reason or '').strip()
    })


def _compute_cache_key(prompt: str, image_base64: str, temperature: float, max_tokens: int) -> str:
    """Create a stable cache key for image+prompt requests."""
    source = f"{prompt}\n|{temperature}|{max_tokens}|{image_base64}"
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def _get_cached_response(cache_key: str) -> str:
    """Return cached response if still valid."""
    if not VISION_CACHE_ENABLED:
        return ''
    entry = _VISION_RESPONSE_CACHE.get(cache_key)
    if not entry:
        return ''

    if entry['expires_at'] < time.time():
        _VISION_RESPONSE_CACHE.pop(cache_key, None)
        return ''

    return entry.get('response', '')


def _set_cached_response(cache_key: str, response_text: str):
    """Store response in TTL cache with simple size cap eviction."""
    if not VISION_CACHE_ENABLED or not response_text:
        return

    if len(_VISION_RESPONSE_CACHE) >= VISION_CACHE_MAX_SIZE:
        oldest_key = min(_VISION_RESPONSE_CACHE, key=lambda k: _VISION_RESPONSE_CACHE[k].get('expires_at', 0))
        _VISION_RESPONSE_CACHE.pop(oldest_key, None)

    _VISION_RESPONSE_CACHE[cache_key] = {
        'response': response_text,
        'expires_at': time.time() + max(10, VISION_CACHE_TTL_SECONDS)
    }


def _build_user_facing_failure_message() -> str:
    """Build a clear alert string when all providers fail."""
    if not _LAST_PROVIDER_FAILURES:
        return ''

    failures = {f.get('provider'): f.get('reason', '') for f in _LAST_PROVIDER_FAILURES}
    local_reason = failures.get('ollama', '')

    if local_reason:
        return (
            "ALERT_LOCAL_MODE_UNAVAILABLE: Local mode is unavailable on this device "
            f"({local_reason}). Please start Ollama/pull model or switch to API mode."
        )

    return (
        "ALERT_PROVIDER_UNAVAILABLE: All configured caption providers are currently unavailable. "
        "Please retry later or adjust provider routing."
    )


def get_runtime_provider_settings():
    """Return current in-memory vision provider settings."""
    return {
        'vision_provider_order': list(VISION_PROVIDER_ORDER),
        'vision_api_url': VISION_API_URL,
        'vision_api_model': VISION_API_MODEL,
        'ollama_vision_model': OLLAMA_MODEL_NAME,
        'gemini_vision_model': GEMINI_VISION_MODEL,
    }


def update_runtime_provider_settings(settings: dict):
    """Update in-memory vision provider settings for immediate runtime effect."""
    global VISION_PROVIDER_ORDER, VISION_API_MODEL, OLLAMA_MODEL_NAME, GEMINI_VISION_MODEL

    if not settings:
        return get_runtime_provider_settings()

    if 'vision_provider_order' in settings and settings['vision_provider_order'] is not None:
        raw = settings['vision_provider_order']
        if isinstance(raw, str):
            providers = [p.strip().lower() for p in raw.split(',') if p.strip()]
        elif isinstance(raw, list):
            providers = [str(p).strip().lower() for p in raw if str(p).strip()]
        else:
            providers = []

        allowed = {'model_api', 'gemini', 'ollama'}
        normalized = []
        for provider in providers:
            if provider in allowed and provider not in normalized:
                normalized.append(provider)
        if normalized:
            VISION_PROVIDER_ORDER = normalized

    if settings.get('vision_model'):
        VISION_API_MODEL = str(settings['vision_model']).strip()
        os.environ['VISION_API_MODEL'] = VISION_API_MODEL

    if settings.get('ollama_vision_model'):
        OLLAMA_MODEL_NAME = str(settings['ollama_vision_model']).strip()
        os.environ['OLLAMA_VISION_MODEL'] = OLLAMA_MODEL_NAME

    if settings.get('gemini_vision_model'):
        GEMINI_VISION_MODEL = str(settings['gemini_vision_model']).strip()
        os.environ['GEMINI_VISION_MODEL'] = GEMINI_VISION_MODEL

    os.environ['VISION_PROVIDER_ORDER'] = ','.join(VISION_PROVIDER_ORDER)
    return get_runtime_provider_settings()

def encode_image_to_base64(image_path):
    """Convert image to base64 string for API."""
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def _normalize_openai_base_url(raw_url: str, endpoint_suffix: str) -> str:
    """Normalize URL for OpenAI-compatible endpoints."""
    if not raw_url:
        return ''
    url = raw_url.rstrip('/')
    if url.endswith(endpoint_suffix):
        return url
    if url.endswith('/v1'):
        return f"{url}{endpoint_suffix}"
    return f"{url}/v1{endpoint_suffix}"


def _extract_gemini_text(data: dict) -> str:
    """Extract text from Gemini generateContent response."""
    candidates = data.get('candidates', [])
    if not candidates:
        return ''
    parts = candidates[0].get('content', {}).get('parts', [])
    texts = [part.get('text', '') for part in parts if part.get('text')]
    return '\n'.join(texts).strip()


def _call_model_api_vision(prompt: str, image_base64: str, max_tokens: int = 350) -> str:
    """Call model-specific cloud API using OpenAI-compatible chat/completions format."""
    if not (VISION_API_URL and VISION_API_MODEL):
        _record_provider_failure('model_api', 'API URL or model is not configured')
        return ''

    endpoint = _normalize_openai_base_url(VISION_API_URL, '/chat/completions')
    headers = {'Content-Type': 'application/json'}
    if VISION_API_KEY:
        headers['Authorization'] = f"Bearer {VISION_API_KEY}"

    payload = {
        'model': VISION_API_MODEL,
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {
                        'type': 'image_url',
                        'image_url': {'url': f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]
            }
        ],
        'temperature': 0.5,
        'max_tokens': max_tokens
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=TIMEOUT)
        if not response.ok:
            _record_provider_failure('model_api', f"HTTP {response.status_code}")
            return ''
        data = response.json()
        choices = data.get('choices', [])
        if not choices:
            _record_provider_failure('model_api', 'Empty choices in response')
            return ''
        return choices[0].get('message', {}).get('content', '').strip()
    except Exception as e:
        _record_provider_failure('model_api', str(e))
        return ''


def _call_gemini_vision(prompt: str, image_base64: str, temperature: float = 0.6, max_tokens: int = 300) -> str:
    """Call Gemini generateContent REST API for multimodal vision responses."""
    global _gemini_quota_backoff_until

    if not GEMINI_API_KEY:
        _record_provider_failure('gemini', 'GEMINI_API_KEY is not configured')
        return ''

    if _gemini_quota_backoff_until > time.time():
        wait_left = int(_gemini_quota_backoff_until - time.time())
        _record_provider_failure('gemini', f'Quota cooldown active ({wait_left}s remaining)')
        return ''

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_VISION_MODEL}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )
    payload = {
        'contents': [
            {
                'parts': [
                    {'text': prompt},
                    {
                        'inline_data': {
                            'mime_type': 'image/jpeg',
                            'data': image_base64
                        }
                    }
                ]
            }
        ],
        'generationConfig': {
            'temperature': temperature,
            'maxOutputTokens': max_tokens
        }
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=TIMEOUT)
        if not response.ok:
            body = response.text[:300] if response.text else ''
            upper = body.upper()
            if response.status_code == 429 or 'RESOURCE_EXHAUSTED' in upper or 'QUOTA' in upper:
                _gemini_quota_backoff_until = time.time() + max(60, GEMINI_QUOTA_COOLDOWN_SECONDS)
                _record_provider_failure('gemini', 'Quota/rate limit reached (429)')
            else:
                _record_provider_failure('gemini', f"HTTP {response.status_code}")
            return ''
        text = _extract_gemini_text(response.json())
        if not text:
            _record_provider_failure('gemini', 'Empty response text')
        return text
    except Exception as e:
        _record_provider_failure('gemini', str(e))
        return ''


def _call_ollama_vision(prompt: str, image_base64: str, temperature: float = 0.6, max_tokens: int = 250) -> str:
    """Call local Ollama vision model."""
    if not check_ollama_running():
        _record_provider_failure('ollama', 'Ollama service is not running')
        return ''
    if not check_model_available(OLLAMA_MODEL_NAME):
        _record_provider_failure('ollama', f"Model '{OLLAMA_MODEL_NAME}' is not available")
        return ''

    payload = {
        'model': OLLAMA_MODEL_NAME,
        'prompt': prompt,
        'images': [image_base64],
        'stream': False,
        'options': {
            'temperature': temperature,
            'num_predict': max_tokens
        }
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=TIMEOUT)
        if not response.ok:
            _record_provider_failure('ollama', f"HTTP {response.status_code}")
            return ''
        text = response.json().get('response', '').strip()
        if not text:
            _record_provider_failure('ollama', 'Empty response text')
        return text
    except Exception as e:
        _record_provider_failure('ollama', str(e))
        return ''


def _generate_vision_response(prompt: str, image_base64: str, temperature: float = 0.6, max_tokens: int = 300) -> str:
    """Try providers in configured order until one returns a response."""
    _LAST_PROVIDER_FAILURES.clear()

    cache_key = _compute_cache_key(prompt, image_base64, temperature, max_tokens)
    cached = _get_cached_response(cache_key)
    if cached:
        print("Using vision response from cache")
        return cached

    for provider in VISION_PROVIDER_ORDER:
        if provider == 'model_api':
            output = _call_model_api_vision(prompt, image_base64, max_tokens=max_tokens)
        elif provider == 'gemini':
            output = _call_gemini_vision(prompt, image_base64, temperature=temperature, max_tokens=max_tokens)
        elif provider == 'ollama':
            output = _call_ollama_vision(prompt, image_base64, temperature=temperature, max_tokens=max_tokens)
        else:
            output = ''

        if output:
            print(f"Using vision provider: {provider}")
            _set_cached_response(cache_key, output)
            return output

    return _build_user_facing_failure_message()

def check_ollama_running():
    """Check if Ollama is running."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        return response.status_code == 200
    except:
        return False

def check_model_available(model_name):
    """Check if the specified model is available in Ollama."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
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
    # Verify image exists
    if not Path(image_path).exists():
        print(f"Error: Image file not found at {image_path}")
        return None
    
    print(f"Image loaded: {Path(image_path).name}")
    
    # Build prompt for higher quality people/action/situation captions (works across model_api/gemini/ollama).
    prompt = """You are a workplace visual analyst. Write a factual caption from this image only.

Output requirements (single paragraph, 4-6 sentences):
1) Start with total visible people count and scene type (residential, office, warehouse, roadside, construction, etc.).
2) For each visible person, describe:
    - what the person is doing (action/posture/interaction)
    - which body region is visible (full body / upper body / head only)
    - the person's situation/context (near vehicle, near machinery, indoors at home, standing idle, using phone, etc.)
3) Mention PPE only when clearly visible and certain.
4) If PPE region is not visible, explicitly say it is not visible instead of guessing.
5) End with concise safety context based on visible facts only.

Strict grounding rules:
- Do NOT invent tools, hazards, or PPE that are not clearly visible.
- Do NOT assume construction/worksite unless visual evidence supports it.
- Hardhat must be a rigid safety helmet; hair/cap/hood is not a hardhat.
- Safety vest must be fluorescent and reflective to be considered a safety vest.

Style:
- Natural professional English, no bullet points, no markdown.
- Avoid generic phrases like "In the image" or "The image shows".
"""
    
    # Encode image to base64
    try:
        image_base64 = encode_image_to_base64(image_path)
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None
    
    # Generate caption using provider routing
    try:
        print("Generating caption...")
        caption = _generate_vision_response(
            prompt=prompt,
            image_base64=image_base64,
            temperature=0.6,
            max_tokens=380
        )
        
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
        answer = _generate_vision_response(
            prompt=prompt,
            image_base64=image_base64,
            temperature=0.3,
            max_tokens=40
        ).upper()

        if not answer:
            return {
                'is_valid': True,
                'confidence': 'low',
                'environment_type': 'unknown',
                'reason': 'No response from configured providers'
            }
        
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
        print(f"ollama pull {OLLAMA_MODEL_NAME}")
    except Exception as e:
        print(f"\nAn error occurred: {e}")