"""
Image Captioning with local Ollama vision model

Fast and accurate image captioning using the configured local Ollama model.

Usage:
    python caption_image.py path/to/image.jpg

Requirements:
    - Ollama installed and running
    - Unified local model: ollama pull gemma3:4b
"""
# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.
import sys
import os
import base64
import requests
import json
import time
import hashlib
import io
import re
import shutil
import subprocess
import logging
from pathlib import Path

# Prepare logger for the next step.
logger = logging.getLogger(__name__)

# --- PROVIDER CONFIGURATION ---
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_TAGS_URL = os.getenv('OLLAMA_TAGS_URL', f"{OLLAMA_BASE_URL}/api/tags")
OLLAMA_MODEL_NAME = os.getenv('OLLAMA_VISION_MODEL', os.getenv('OLLAMA_MODEL', os.getenv('LOCAL_OLLAMA_UNIFIED_MODEL', 'gemma3:4b')))
DEFAULT_ROUTING_PROFILE = str(os.getenv('CASM_ROUTING_PROFILE', 'cloud')).strip().lower()
DEFAULT_VISION_PROVIDER_ORDER = 'ollama' if DEFAULT_ROUTING_PROFILE == 'local' else 'gemini'


# Section: run the safe int env workflow with clear inputs and outputs.
def _safe_int_env(name: str, default: int) -> int:
    """Parse integer environment variables safely with fallback."""
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Return the prepared result to the caller.
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)

VISION_PROVIDER_ORDER = [
    provider.strip().lower()
    for provider in os.getenv('VISION_PROVIDER_ORDER', DEFAULT_VISION_PROVIDER_ORDER).split(',')
    if provider.strip()
]

# Prepare strict provider mode split for the next step.
STRICT_PROVIDER_MODE_SPLIT = os.getenv('STRICT_PROVIDER_MODE_SPLIT', 'true').lower() in ('1', 'true', 'yes', 'on')


# Section: run the strict vision order for profile workflow with clear inputs and outputs.
def _strict_vision_order_for_profile(profile: str):
    """Return strict provider order for local/cloud profile."""
    # Prepare normalized for the next step.
    normalized = str(profile or '').strip().lower()
    if normalized == 'local':
        # Return the prepared result to the caller.
        return ['ollama']
    if normalized == 'cloud':
        return ['gemini']
    return []


# Choose the correct branch before the workflow continues.
if STRICT_PROVIDER_MODE_SPLIT:
    # Prepare profile order for the next step.
    profile_order = _strict_vision_order_for_profile(os.getenv('CASM_ROUTING_PROFILE', DEFAULT_ROUTING_PROFILE))
    if profile_order:
        # Prepare vision provider order for the next step.
        VISION_PROVIDER_ORDER = profile_order

# OpenAI-compatible model API (e.g., first-party/hosted Qwen, Moondream, Llama providers)
VISION_API_URL = os.getenv('VISION_API_URL', '').strip()
VISION_API_KEY = os.getenv('VISION_API_KEY', '').strip()
VISION_API_MODEL = os.getenv('VISION_API_MODEL', '').strip()

# Google Gemini fallback
# Prepare gemini api key for the next step.
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_VISION_MODEL = os.getenv('GEMINI_VISION_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')).strip()
GEMINI_VISION_THINKING_BUDGET = _safe_int_env('GEMINI_VISION_THINKING_BUDGET', 0)

TIMEOUT = int(os.getenv('VISION_TIMEOUT', '60'))
OLLAMA_CONNECT_TIMEOUT_SECONDS = max(1, _safe_int_env('OLLAMA_CONNECT_TIMEOUT_SECONDS', 8))
OLLAMA_VISION_READ_TIMEOUT_SECONDS = _safe_int_env('OLLAMA_VISION_READ_TIMEOUT_SECONDS', 60)
LOCAL_OLLAMA_VISION_CONNECT_TIMEOUT_SECONDS = max(
    1,
    _safe_int_env('LOCAL_OLLAMA_VISION_CONNECT_TIMEOUT_SECONDS', 3)
)
# Prepare local ollama vision read timeout seconds for the next step.
LOCAL_OLLAMA_VISION_READ_TIMEOUT_SECONDS = max(
    12,
    _safe_int_env('LOCAL_OLLAMA_VISION_READ_TIMEOUT_SECONDS', 120)
)
LOCAL_OLLAMA_CPU_VISION_READ_TIMEOUT_SECONDS = max(
    LOCAL_OLLAMA_VISION_READ_TIMEOUT_SECONDS,
    min(_safe_int_env('LOCAL_OLLAMA_CPU_VISION_READ_TIMEOUT_SECONDS', 210), 420)
)
LOCAL_OLLAMA_CAPTION_MAX_TOKENS = max(
    160,
    min(_safe_int_env('LOCAL_OLLAMA_CAPTION_MAX_TOKENS', 420), 750)
)
# Prepare local ollama structured caption max tokens for the next step.
LOCAL_OLLAMA_STRUCTURED_CAPTION_MAX_TOKENS = max(
    256,
    min(_safe_int_env('LOCAL_OLLAMA_STRUCTURED_CAPTION_MAX_TOKENS', 520), 850)
)
LOCAL_OLLAMA_CAPTION_EXPANSION_ENABLED = os.getenv(
    'LOCAL_OLLAMA_CAPTION_EXPANSION_ENABLED',
    'true',
).lower() in ('1', 'true', 'yes', 'on')
LOCAL_OLLAMA_CAPTION_WARMUP_ENABLED = os.getenv('LOCAL_OLLAMA_CAPTION_WARMUP_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
# Prepare local ollama caption warmup timeout seconds for the next step.
LOCAL_OLLAMA_CAPTION_WARMUP_TIMEOUT_SECONDS = max(
    8,
    min(_safe_int_env('LOCAL_OLLAMA_CAPTION_WARMUP_TIMEOUT_SECONDS', 45), 90)
)
LOCAL_OLLAMA_CAPTION_MAX_IMAGE_DIM = max(
    224,
    min(_safe_int_env('LOCAL_OLLAMA_CAPTION_MAX_IMAGE_DIM', 448), 640)
)
OLLAMA_VISION_NUM_CTX = max(512, _safe_int_env('OLLAMA_VISION_NUM_CTX', 2048))
# Prepare ollama vision num gpu raw for the next step.
_OLLAMA_VISION_NUM_GPU_RAW = os.getenv('OLLAMA_VISION_NUM_GPU', '').strip()
OLLAMA_VISION_NUM_GPU = (
    _safe_int_env('OLLAMA_VISION_NUM_GPU', 0)
    if _OLLAMA_VISION_NUM_GPU_RAW
    else None
)
OLLAMA_VISION_NUM_THREAD = _safe_int_env('OLLAMA_VISION_NUM_THREAD', 4)
ENVIRONMENT_VALIDATION_MAX_IMAGE_DIM = max(256, _safe_int_env('ENVIRONMENT_VALIDATION_MAX_IMAGE_DIM', 512))
ENVIRONMENT_VALIDATION_OLLAMA_NUM_CTX = max(512, _safe_int_env('ENVIRONMENT_VALIDATION_OLLAMA_NUM_CTX', 768))
# Prepare environment validation ollama keep alive for the next step.
ENVIRONMENT_VALIDATION_OLLAMA_KEEP_ALIVE = os.getenv('ENVIRONMENT_VALIDATION_OLLAMA_KEEP_ALIVE', '5m')
OLLAMA_AUTO_RECOVER_ENABLED = os.getenv('OLLAMA_AUTO_RECOVER_ENABLED', 'true').lower() in ('1', 'true', 'yes', 'on')
OLLAMA_AUTO_RECOVER_COOLDOWN_SECONDS = max(5, _safe_int_env('OLLAMA_AUTO_RECOVER_COOLDOWN_SECONDS', 45))
OLLAMA_AUTO_RECOVER_WAIT_SECONDS = max(1, _safe_int_env('OLLAMA_AUTO_RECOVER_WAIT_SECONDS', 8))
OLLAMA_AUTO_RECOVER_PULL_TIMEOUT_SECONDS = max(60, _safe_int_env('OLLAMA_AUTO_RECOVER_PULL_TIMEOUT_SECONDS', 600))
OLLAMA_AUTO_RECOVER_RETRY_HTTP_STATUSES = {500, 502, 503, 504}

# Lightweight response cache + provider diagnostics to reduce repeated API calls.
VISION_CACHE_ENABLED = os.getenv('VISION_CACHE_ENABLED', 'true').lower() == 'true'
VISION_CACHE_TTL_SECONDS = int(os.getenv('VISION_CACHE_TTL_SECONDS', '900'))
VISION_CACHE_MAX_SIZE = int(os.getenv('VISION_CACHE_MAX_SIZE', '128'))
GEMINI_QUOTA_COOLDOWN_SECONDS = int(os.getenv('GEMINI_QUOTA_COOLDOWN_SECONDS', '900'))

_VISION_RESPONSE_CACHE = {}
_LAST_PROVIDER_FAILURES = []
_gemini_quota_backoff_until = 0.0
_LAST_PROVIDER_USED = None
_ollama_auto_recover_next_allowed_ts = 0.0
# Prepare local gpu hint available cache for the next step.
_local_gpu_hint_available_cache = None
# ---------------------------


def _env_flag(name: str, default: bool = False) -> bool:
    # Prepare raw for the next step.
    raw = os.getenv(name)
    if raw is None:
        # Return the prepared result to the caller.
        return bool(default)
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


# Section: run the local gpu hint available workflow with clear inputs and outputs.
def _local_gpu_hint_available() -> bool:
    """Best-effort GPU hint for choosing local Ollama timeout gates."""
    global _local_gpu_hint_available_cache
    # Choose the correct branch before the workflow continues.
    if _env_flag('LOCAL_OLLAMA_ASSUME_CPU_ONLY', False):
        return False
    if _env_flag('LOCAL_OLLAMA_ASSUME_GPU_AVAILABLE', False):
        # Return the prepared result to the caller.
        return True
    if _local_gpu_hint_available_cache is not None:
        return bool(_local_gpu_hint_available_cache)

    available = False
    nvidia_smi = shutil.which('nvidia-smi')
    # Choose the correct branch before the workflow continues.
    if nvidia_smi:
        try:
            # Prepare completed for the next step.
            completed = subprocess.run(
                [nvidia_smi, '-L'],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            available = completed.returncode == 0 and bool((completed.stdout or '').strip())
        except Exception:
            # Prepare available for the next step.
            available = False

    # Prepare local gpu hint available cache for the next step.
    _local_gpu_hint_available_cache = bool(available)
    return bool(available)


# Section: run the local ollama cpu timeout needed workflow with clear inputs and outputs.
def _local_ollama_cpu_timeout_needed() -> bool:
    if OLLAMA_VISION_NUM_GPU is not None and OLLAMA_VISION_NUM_GPU <= 0:
        # Return the prepared result to the caller.
        return True
    return not _local_gpu_hint_available()


# Section: run the get ollama request timeout workflow with clear inputs and outputs.
def _get_ollama_request_timeout():
    """Use finite connect/read timeouts so a stalled local model cannot wedge routing."""
    # Prepare active profile for the next step.
    active_profile = str(os.getenv('CASM_ROUTING_PROFILE', DEFAULT_ROUTING_PROFILE)).strip().lower()
    local_profile = active_profile == 'local'

    connect_timeout = OLLAMA_CONNECT_TIMEOUT_SECONDS
    if local_profile and 'OLLAMA_CONNECT_TIMEOUT_SECONDS' not in os.environ:
        # Prepare connect timeout for the next step.
        connect_timeout = LOCAL_OLLAMA_VISION_CONNECT_TIMEOUT_SECONDS

    if local_profile and 'OLLAMA_VISION_READ_TIMEOUT_SECONDS' not in os.environ:
        read_timeout = LOCAL_OLLAMA_VISION_READ_TIMEOUT_SECONDS
        if _local_ollama_cpu_timeout_needed():
            # Prepare read timeout for the next step.
            read_timeout = max(read_timeout, LOCAL_OLLAMA_CPU_VISION_READ_TIMEOUT_SECONDS)
    # Choose the correct branch before the workflow continues.
    elif OLLAMA_VISION_READ_TIMEOUT_SECONDS <= 0:
        read_timeout = 120
    else:
        # Prepare read timeout for the next step.
        read_timeout = max(1, OLLAMA_VISION_READ_TIMEOUT_SECONDS)

    return (max(1, connect_timeout), max(1, read_timeout))


# Section: run the record provider failure workflow with clear inputs and outputs.
def _record_provider_failure(provider: str, reason: str):
    """Record provider-level failure reasons for user-facing diagnostics."""
    # Prepare clean reason for the next step.
    clean_reason = str(reason or '').strip()
    _LAST_PROVIDER_FAILURES.append({
        'provider': provider,
        'reason': clean_reason
    })
    logger.warning("[VLM:%s] provider failure: %s", provider, clean_reason)


# Section: run the compute cache key workflow with clear inputs and outputs.
def _compute_cache_key(prompt: str, image_base64: str, temperature: float, max_tokens: int) -> str:
    """Create a stable cache key for image+prompt requests."""
    # Prepare source for the next step.
    source = f"{prompt}\n|{temperature}|{max_tokens}|{image_base64}"
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


# Section: run the get cached response workflow with clear inputs and outputs.
def _get_cached_response(cache_key: str) -> str:
    """Return cached response if still valid."""
    if not VISION_CACHE_ENABLED:
        # Return the prepared result to the caller.
        return ''
    entry = _VISION_RESPONSE_CACHE.get(cache_key)
    # Choose the correct branch before the workflow continues.
    if not entry:
        return ''

    if entry['expires_at'] < time.time():
        _VISION_RESPONSE_CACHE.pop(cache_key, None)
        return ''

    return entry.get('response', '')


# Section: run the set cached response workflow with clear inputs and outputs.
def _set_cached_response(cache_key: str, response_text: str):
    """Store response in TTL cache with simple size cap eviction."""
    # Choose the correct branch before the workflow continues.
    if not VISION_CACHE_ENABLED or not response_text:
        # Return the prepared result to the caller.
        return

    if len(_VISION_RESPONSE_CACHE) >= VISION_CACHE_MAX_SIZE:
        oldest_key = min(_VISION_RESPONSE_CACHE, key=lambda k: _VISION_RESPONSE_CACHE[k].get('expires_at', 0))
        _VISION_RESPONSE_CACHE.pop(oldest_key, None)

    _VISION_RESPONSE_CACHE[cache_key] = {
        'response': response_text,
        'expires_at': time.time() + max(10, VISION_CACHE_TTL_SECONDS)
    }


# Section: run the build user facing failure message workflow with clear inputs and outputs.
def _build_user_facing_failure_message() -> str:
    """Build a clear alert string when all providers fail."""
    # Choose the correct branch before the workflow continues.
    if not _LAST_PROVIDER_FAILURES:
        # Return the prepared result to the caller.
        return ''

    failures = {f.get('provider'): f.get('reason', '') for f in _LAST_PROVIDER_FAILURES}
    local_reason = failures.get('ollama', '')

    if local_reason:
        return (
            "ALERT_LOCAL_MODE_UNAVAILABLE: Local mode is unavailable on this device "
            f"({local_reason}). Please start Ollama/pull model or switch to API mode."
        )

    # Return the prepared result to the caller.
    return (
        "ALERT_PROVIDER_UNAVAILABLE: All configured caption providers are currently unavailable. "
        "Please retry later or adjust provider routing."
    )


# Section: run the get runtime provider diagnostics workflow with clear inputs and outputs.
def get_runtime_provider_diagnostics() -> dict:
    """Return runtime diagnostics for vision provider routing and cooldown state."""
    cooldown_remaining = max(0, int(_gemini_quota_backoff_until - time.time()))
    # Prepare ollama recovery cooldown remaining for the next step.
    ollama_recovery_cooldown_remaining = max(0, int(_ollama_auto_recover_next_allowed_ts - time.time()))
    return {
        'vision_provider_order': list(VISION_PROVIDER_ORDER),
        'last_provider_used': _LAST_PROVIDER_USED,
        'recent_failures': list(_LAST_PROVIDER_FAILURES[-6:]),
        'gemini_quota_cooldown_remaining_s': cooldown_remaining,
        'ollama_auto_recover_enabled': OLLAMA_AUTO_RECOVER_ENABLED,
        'ollama_auto_recover_cooldown_remaining_s': ollama_recovery_cooldown_remaining,
        'gemini_model': GEMINI_VISION_MODEL,
        'ollama_model': OLLAMA_MODEL_NAME,
        'ollama_request_timeout': _get_ollama_request_timeout(),
        'ollama_num_gpu_override': OLLAMA_VISION_NUM_GPU,
        'ollama_cpu_timeout_gate': _local_ollama_cpu_timeout_needed(),
        'vision_api_model': VISION_API_MODEL,
    }


# Section: run the get runtime provider settings workflow with clear inputs and outputs.
def get_runtime_provider_settings():
    """Return current in-memory vision provider settings."""
    # Return the prepared result to the caller.
    return {
        'vision_provider_order': list(VISION_PROVIDER_ORDER),
        'vision_api_url': VISION_API_URL,
        'vision_api_model': VISION_API_MODEL,
        'ollama_vision_model': OLLAMA_MODEL_NAME,
        'gemini_vision_model': GEMINI_VISION_MODEL,
    }


# Section: run the update runtime provider settings workflow with clear inputs and outputs.
def update_runtime_provider_settings(settings: dict):
    """Update in-memory vision provider settings for immediate runtime effect."""
    global VISION_PROVIDER_ORDER, VISION_API_MODEL, OLLAMA_MODEL_NAME, GEMINI_VISION_MODEL

    # Choose the correct branch before the workflow continues.
    if not settings:
        # Return the prepared result to the caller.
        return get_runtime_provider_settings()

    if 'vision_provider_order' in settings and settings['vision_provider_order'] is not None:
        raw = settings['vision_provider_order']
        if isinstance(raw, str):
            # Prepare providers for the next step.
            providers = [p.strip().lower() for p in raw.split(',') if p.strip()]
        elif isinstance(raw, list):
            providers = [str(p).strip().lower() for p in raw if str(p).strip()]
        else:
            providers = []

        # Prepare allowed for the next step.
        allowed = {'model_api', 'gemini', 'ollama'}
        normalized = []
        for provider in providers:
            # Choose the correct branch before the workflow continues.
            if provider in allowed and provider not in normalized:
                # Trigger the side effect required for this stage.
                normalized.append(provider)
        if STRICT_PROVIDER_MODE_SPLIT:
            requested_profile = str(settings.get('routing_profile') or os.getenv('CASM_ROUTING_PROFILE', '')).strip().lower()
            strict_order = _strict_vision_order_for_profile(requested_profile)
            if strict_order:
                VISION_PROVIDER_ORDER = strict_order
            elif normalized:
                inferred_profile = 'local' if normalized[0] == 'ollama' else 'cloud'
                VISION_PROVIDER_ORDER = _strict_vision_order_for_profile(inferred_profile)
        # Choose the correct branch before the workflow continues.
        elif normalized:
            # Prepare vision provider order for the next step.
            VISION_PROVIDER_ORDER = normalized

    # Choose the correct branch before the workflow continues.
    if settings.get('vision_model'):
        VISION_API_MODEL = str(settings['vision_model']).strip()
        os.environ['VISION_API_MODEL'] = VISION_API_MODEL

    if settings.get('ollama_vision_model'):
        OLLAMA_MODEL_NAME = str(settings['ollama_vision_model']).strip()
        # Prepare values needed by the next step.
        os.environ['OLLAMA_VISION_MODEL'] = OLLAMA_MODEL_NAME

    if settings.get('gemini_vision_model'):
        GEMINI_VISION_MODEL = str(settings['gemini_vision_model']).strip()
        os.environ['GEMINI_VISION_MODEL'] = GEMINI_VISION_MODEL

    # Prepare values needed by the next step.
    os.environ['VISION_PROVIDER_ORDER'] = ','.join(VISION_PROVIDER_ORDER)
    return get_runtime_provider_settings()

# Section: run the encode image to base64 workflow with clear inputs and outputs.
def encode_image_to_base64(image_path):
    """Convert image to base64 string for API."""
    with open(image_path, 'rb') as image_file:
        # Return the prepared result to the caller.
        return base64.b64encode(image_file.read()).decode('utf-8')


# Section: run the encode environment validation image workflow with clear inputs and outputs.
def _encode_environment_validation_image(image_path):
    """Encode a smaller JPEG for fast scene gating; fall back to original bytes."""
    # Protect this step so expected failures can fall back cleanly.
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as image:
            # Prepare image for the next step.
            image = ImageOps.exif_transpose(image)
            if max(image.size) > ENVIRONMENT_VALIDATION_MAX_IMAGE_DIM:
                # Trigger the side effect required for this stage.
                image.thumbnail(
                    (ENVIRONMENT_VALIDATION_MAX_IMAGE_DIM, ENVIRONMENT_VALIDATION_MAX_IMAGE_DIM),
                    Image.Resampling.LANCZOS,
                )
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Prepare buffer for the next step.
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=82, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        # Trigger the side effect required for this stage.
        logger.debug("Environment validation image downscale failed; using original bytes: %s", e)
        return encode_image_to_base64(image_path)


# Section: run the encode local caption image workflow with clear inputs and outputs.
def _encode_local_caption_image(image_path):
    """Encode a compact local-caption image so Gemma vision can finish promptly."""
    # Protect this step so expected failures can fall back cleanly.
    try:
        from PIL import Image, ImageOps

        # Open the managed resource only for the block that needs it.
        with Image.open(image_path) as image:
            # Prepare image for the next step.
            image = ImageOps.exif_transpose(image)
            if max(image.size) > LOCAL_OLLAMA_CAPTION_MAX_IMAGE_DIM:
                # Trigger the side effect required for this stage.
                image.thumbnail(
                    (LOCAL_OLLAMA_CAPTION_MAX_IMAGE_DIM, LOCAL_OLLAMA_CAPTION_MAX_IMAGE_DIM),
                    Image.Resampling.LANCZOS,
                )
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Prepare buffer for the next step.
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=78, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        # Trigger the side effect required for this stage.
        logger.debug("Local caption image downscale failed; using environment image bytes: %s", e)
        return _encode_environment_validation_image(image_path)


# Section: run the normalize openai base url workflow with clear inputs and outputs.
def _normalize_openai_base_url(raw_url: str, endpoint_suffix: str) -> str:
    """Normalize URL for OpenAI-compatible endpoints."""
    # Choose the correct branch before the workflow continues.
    if not raw_url:
        return ''
    url = raw_url.rstrip('/')
    if url.endswith(endpoint_suffix):
        # Return the prepared result to the caller.
        return url
    if url.endswith('/v1'):
        return f"{url}{endpoint_suffix}"
    return f"{url}/v1{endpoint_suffix}"


# Section: run the extract gemini text workflow with clear inputs and outputs.
def _extract_gemini_text(data: dict) -> str:
    """Extract text from Gemini generateContent response."""
    # Prepare candidates for the next step.
    candidates = data.get('candidates', [])
    if not candidates:
        # Return the prepared result to the caller.
        return ''
    parts = candidates[0].get('content', {}).get('parts', [])
    texts = [part.get('text', '') for part in parts if part.get('text')]
    return '\n'.join(texts).strip()


# Section: run the call model api vision workflow with clear inputs and outputs.
def _call_model_api_vision(prompt: str, image_base64: str, max_tokens: int = 350) -> str:
    """Call model-specific cloud API using OpenAI-compatible chat/completions format."""
    # Choose the correct branch before the workflow continues.
    if not (VISION_API_URL and VISION_API_MODEL):
        # Trigger the side effect required for this stage.
        _record_provider_failure('model_api', 'API URL or model is not configured')
        return ''

    endpoint = _normalize_openai_base_url(VISION_API_URL, '/chat/completions')
    headers = {'Content-Type': 'application/json'}
    if VISION_API_KEY:
        headers['Authorization'] = f"Bearer {VISION_API_KEY}"

    # Prepare payload for the next step.
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

    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare response for the next step.
        response = requests.post(endpoint, headers=headers, json=payload, timeout=TIMEOUT)
        if not response.ok:
            # Trigger the side effect required for this stage.
            _record_provider_failure('model_api', f"HTTP {response.status_code}")
            return ''
        data = response.json()
        choices = data.get('choices', [])
        if not choices:
            _record_provider_failure('model_api', 'Empty choices in response')
            return ''
        # Return the prepared result to the caller.
        return choices[0].get('message', {}).get('content', '').strip()
    except Exception as e:
        _record_provider_failure('model_api', str(e))
        return ''


# Section: run the call gemini vision workflow with clear inputs and outputs.
def _call_gemini_vision(prompt: str, image_base64: str, temperature: float = 0.6, max_tokens: int = 300) -> str:
    """Call Gemini generateContent REST API for multimodal vision responses."""
    global _gemini_quota_backoff_until

    # Choose the correct branch before the workflow continues.
    if not GEMINI_API_KEY:
        # Trigger the side effect required for this stage.
        _record_provider_failure('gemini', 'GEMINI_API_KEY is not configured')
        return ''

    if _gemini_quota_backoff_until > time.time():
        wait_left = int(_gemini_quota_backoff_until - time.time())
        _record_provider_failure('gemini', f'Quota cooldown active ({wait_left}s remaining)')
        return ''

    # Prepare endpoint for the next step.
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
    # Choose the correct branch before the workflow continues.
    if GEMINI_VISION_THINKING_BUDGET >= 0:
        # Prepare values needed by the next step.
        payload['generationConfig']['thinkingConfig'] = {
            'thinkingBudget': GEMINI_VISION_THINKING_BUDGET
        }

    try:
        response = requests.post(endpoint, json=payload, timeout=TIMEOUT)
        if not response.ok:
            # Prepare body for the next step.
            body = response.text[:300] if response.text else ''
            upper = body.upper()
            if response.status_code == 429 or 'RESOURCE_EXHAUSTED' in upper or 'QUOTA' in upper:
                # Prepare gemini quota backoff until for the next step.
                _gemini_quota_backoff_until = time.time() + max(60, GEMINI_QUOTA_COOLDOWN_SECONDS)
                _record_provider_failure('gemini', 'Quota/rate limit reached (429)')
            else:
                _record_provider_failure('gemini', f"HTTP {response.status_code}")
            return ''
        # Prepare text for the next step.
        text = _extract_gemini_text(response.json())
        if not text:
            # Trigger the side effect required for this stage.
            _record_provider_failure('gemini', 'Empty response text')
        return text
    except Exception as e:
        _record_provider_failure('gemini', str(e))
        return ''


# Section: run the detect ollama executable workflow with clear inputs and outputs.
def _detect_ollama_executable() -> str:
    """Return best-effort Ollama executable path, including common non-PATH installs."""
    # Prepare from path for the next step.
    from_path = shutil.which('ollama')
    if from_path:
        # Return the prepared result to the caller.
        return from_path

    candidates = []
    if os.name == 'nt':
        local_app_data = os.getenv('LOCALAPPDATA', '')
        program_files = os.getenv('ProgramFiles', '')
        program_files_x86 = os.getenv('ProgramFiles(x86)', '')
        candidates.extend([
            os.path.join(local_app_data, 'Programs', 'Ollama', 'ollama.exe'),
            os.path.join(local_app_data, 'Programs', 'Ollama', 'Ollama app.exe'),
            os.path.join(program_files, 'Ollama', 'ollama.exe'),
            os.path.join(program_files, 'Ollama', 'Ollama app.exe'),
            os.path.join(program_files_x86, 'Ollama', 'ollama.exe'),
            os.path.join(program_files_x86, 'Ollama', 'Ollama app.exe'),
        ])
    # Choose the correct branch before the workflow continues.
    elif sys.platform == 'darwin':
        # Trigger the side effect required for this stage.
        candidates.extend([
            '/Applications/Ollama.app/Contents/MacOS/Ollama',
            '/opt/homebrew/bin/ollama',
            '/usr/local/bin/ollama',
        ])
    else:
        candidates.extend([
            '/usr/local/bin/ollama',
            '/usr/bin/ollama',
            '/snap/bin/ollama',
        ])

    # Process each item in this collection using the same rule set.
    for candidate in candidates:
        # Choose the correct branch before the workflow continues.
        if candidate and os.path.exists(candidate):
            # Return the prepared result to the caller.
            return candidate

    return ''


# Section: run the start ollama service if needed workflow with clear inputs and outputs.
def _start_ollama_service_if_needed(wait_seconds: int = 8) -> dict:
    """Best-effort start for local Ollama service when it is not running."""
    # Choose the correct branch before the workflow continues.
    if check_ollama_running():
        # Return the prepared result to the caller.
        return {
            'attempted': False,
            'started': False,
            'already_running': True,
            'error': None,
        }

    ollama_cmd = _detect_ollama_executable()
    # Choose the correct branch before the workflow continues.
    if not ollama_cmd:
        # Return the prepared result to the caller.
        return {
            'attempted': True,
            'started': False,
            'already_running': False,
            'error': 'Ollama executable not found in PATH.',
        }

    try:
        kwargs = {
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'stdin': subprocess.DEVNULL,
        }

        # Choose the correct branch before the workflow continues.
        if os.name == 'nt':
            # Prepare values needed by the next step.
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs['start_new_session'] = True

        cmd_lower = os.path.basename(ollama_cmd).lower()
        if cmd_lower == 'ollama app.exe':
            subprocess.Popen([ollama_cmd], **kwargs)
        else:
            subprocess.Popen([ollama_cmd, 'serve'], **kwargs)

        # Prepare deadline for the next step.
        deadline = time.time() + max(1, int(wait_seconds))
        while time.time() < deadline:
            # Choose the correct branch before the workflow continues.
            if check_ollama_running():
                # Return the prepared result to the caller.
                return {
                    'attempted': True,
                    'started': True,
                    'already_running': False,
                    'error': None,
                }
            time.sleep(1)

        # Return the prepared result to the caller.
        return {
            'attempted': True,
            'started': False,
            'already_running': False,
            'error': 'Ollama did not become reachable in time.',
        }
    except Exception as e:
        return {
            'attempted': True,
            'started': False,
            'already_running': False,
            'error': str(e),
        }


# Section: run the pull ollama model if needed workflow with clear inputs and outputs.
def _pull_ollama_model_if_needed(model_name: str, timeout_seconds: int = 600) -> dict:
    """Best-effort pull for required Ollama model when not yet available."""
    # Prepare target model for the next step.
    target_model = str(model_name or '').strip() or OLLAMA_MODEL_NAME
    if check_model_available(target_model):
        # Return the prepared result to the caller.
        return {
            'attempted': False,
            'pulled': False,
            'already_available': True,
            'error': None,
        }

    # Choose the correct branch before the workflow continues.
    if not check_ollama_running():
        return {
            'attempted': False,
            'pulled': False,
            'already_available': False,
            'error': 'Ollama is not running; cannot pull model yet.',
        }

    pull_url = f"{OLLAMA_BASE_URL}/api/pull"
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare response for the next step.
        response = requests.post(
            pull_url,
            json={'model': target_model, 'stream': False},
            timeout=max(60, int(timeout_seconds)),
        )
        if not response.ok:
            # Return the prepared result to the caller.
            return {
                'attempted': True,
                'pulled': False,
                'already_available': False,
                'error': f"Model pull failed (HTTP {response.status_code})",
            }

        # Return the prepared result to the caller.
        return {
            'attempted': True,
            'pulled': bool(check_model_available(target_model)),
            'already_available': False,
            'error': None if check_model_available(target_model) else 'Model pull returned without availability confirmation.',
        }
    except Exception as e:
        return {
            'attempted': True,
            'pulled': False,
            'already_available': False,
            'error': str(e),
        }


# Section: run the attempt ollama auto recover workflow with clear inputs and outputs.
def attempt_ollama_auto_recover(reason: str = '', model_name: str = '', require_model: bool = True) -> dict:
    """Attempt to recover Ollama runtime readiness (service + model) with cooldown."""
    global _ollama_auto_recover_next_allowed_ts

    # Prepare target model for the next step.
    target_model = str(model_name or '').strip() or OLLAMA_MODEL_NAME
    now = time.time()
    result = {
        'attempted': False,
        'ready': False,
        'cooldown_skipped': False,
        'reason': str(reason or '').strip(),
        'target_model': target_model,
        'start_service': {
            'attempted': False,
            'started': False,
            'already_running': False,
            'error': None,
        },
        'pull_model': {
            'attempted': False,
            'pulled': False,
            'already_available': False,
            'error': None,
        },
    }

    # Prepare running for the next step.
    running = check_ollama_running()
    model_ready = check_model_available(target_model) if running else False
    if running and (model_ready or not require_model):
        # Prepare values needed by the next step.
        result['ready'] = True
        return result

    if not OLLAMA_AUTO_RECOVER_ENABLED:
        return result

    # Choose the correct branch before the workflow continues.
    if now < _ollama_auto_recover_next_allowed_ts:
        result['cooldown_skipped'] = True
        return result

    _ollama_auto_recover_next_allowed_ts = now + float(OLLAMA_AUTO_RECOVER_COOLDOWN_SECONDS)
    result['attempted'] = True

    if not running:
        # Prepare values needed by the next step.
        result['start_service'] = _start_ollama_service_if_needed(wait_seconds=OLLAMA_AUTO_RECOVER_WAIT_SECONDS)

    # Prepare running for the next step.
    running = check_ollama_running()
    if require_model and running and not check_model_available(target_model):
        result['pull_model'] = _pull_ollama_model_if_needed(
            target_model,
            timeout_seconds=OLLAMA_AUTO_RECOVER_PULL_TIMEOUT_SECONDS,
        )

    running = check_ollama_running()
    model_ready = check_model_available(target_model) if running else False
    # Prepare values needed by the next step.
    result['ready'] = bool(running and (model_ready or not require_model))
    return result


# Section: run the call ollama vision workflow with clear inputs and outputs.
def _call_ollama_vision(
    prompt: str,
    image_base64: str,
    temperature: float = 0.6,
    max_tokens: int = 250,
    ollama_options: dict = None,
    ollama_format=None,
) -> str:
    """Call local Ollama vision model."""
    # Prepare target model for the next step.
    target_model = str(OLLAMA_MODEL_NAME or '').strip() or 'gemma3:4b'
    logger.info(
        "[VLM:ollama] preflight start model=%s api_url=%s timeout=%s prompt_chars=%s image_sha256=%s",
        target_model,
        OLLAMA_API_URL,
        _get_ollama_request_timeout(),
        len(prompt or ''),
        hashlib.sha256((image_base64 or '').encode('utf-8')).hexdigest()[:12],
    )

    # Choose the correct branch before the workflow continues.
    if not check_ollama_running():
        # Trigger the side effect required for this stage.
        logger.warning("[VLM:ollama] service is not running before auto-recover")
        recovery = attempt_ollama_auto_recover(
            reason='Ollama service is not running',
            model_name=target_model,
            require_model=True,
        )
        if not recovery.get('ready'):
            # Trigger the side effect required for this stage.
            _record_provider_failure('ollama', 'Ollama service is not running')
            return ''

    # Choose the correct branch before the workflow continues.
    if not check_model_available(target_model):
        # Trigger the side effect required for this stage.
        logger.warning("[VLM:ollama] model '%s' is not available before auto-recover", target_model)
        recovery = attempt_ollama_auto_recover(
            reason=f"Model '{target_model}' is not available",
            model_name=target_model,
            require_model=True,
        )
        if not recovery.get('ready'):
            # Trigger the side effect required for this stage.
            _record_provider_failure('ollama', f"Model '{target_model}' is not available")
            return ''

    # Prepare request overrides for the next step.
    request_overrides = dict(ollama_options or {})
    active_profile = str(os.getenv('CASM_ROUTING_PROFILE', DEFAULT_ROUTING_PROFILE)).strip().lower()
    local_profile = active_profile == 'local'
    keep_alive_default = '5m' if local_profile else '0'
    keep_alive = request_overrides.pop('keep_alive', os.getenv('OLLAMA_VISION_KEEP_ALIVE', keep_alive_default))
    options = {
        'temperature': temperature,
        'num_predict': max_tokens,
        'num_ctx': OLLAMA_VISION_NUM_CTX,
    }
    # Choose the correct branch before the workflow continues.
    if OLLAMA_VISION_NUM_GPU is not None:
        # Prepare values needed by the next step.
        options['num_gpu'] = OLLAMA_VISION_NUM_GPU
    options.update(request_overrides)

    payload = {
        'model': target_model,
        'prompt': prompt,
        'images': [image_base64],
        'stream': False,
        'keep_alive': keep_alive,
        'options': options,
    }
    # Choose the correct branch before the workflow continues.
    if ollama_format:
        # Prepare values needed by the next step.
        payload['format'] = ollama_format
    if OLLAMA_VISION_NUM_THREAD > 0:
        payload['options']['num_thread'] = OLLAMA_VISION_NUM_THREAD

    try:
        started = time.perf_counter()
        logger.info("[VLM:ollama] request start model=%s", target_model)
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=_get_ollama_request_timeout())

        # Choose the correct branch before the workflow continues.
        if not response.ok and response.status_code in OLLAMA_AUTO_RECOVER_RETRY_HTTP_STATUSES:
            # Trigger the side effect required for this stage.
            logger.warning("[VLM:ollama] HTTP %s; attempting auto-recover before retry", response.status_code)
            recovery = attempt_ollama_auto_recover(
                reason=f"HTTP {response.status_code}",
                model_name=target_model,
                require_model=True,
            )
            if recovery.get('ready'):
                # Prepare response for the next step.
                response = requests.post(OLLAMA_API_URL, json=payload, timeout=_get_ollama_request_timeout())

        # Choose the correct branch before the workflow continues.
        if not response.ok:
            # Protect this step so expected failures can fall back cleanly.
            try:
                error_detail = response.json().get('error', '')
            except Exception:
                error_detail = response.text[:160] if response.text else ''
            error_suffix = f": {error_detail}" if error_detail else ''
            _record_provider_failure('ollama', f"HTTP {response.status_code}{error_suffix}")
            return ''

        # Prepare text for the next step.
        text = response.json().get('response', '').strip()
        if not text:
            # Trigger the side effect required for this stage.
            _record_provider_failure('ollama', 'Empty response text')
        else:
            logger.info(
                "[VLM:ollama] request complete model=%s duration_ms=%.1f output_chars=%s preview=%r",
                target_model,
                (time.perf_counter() - started) * 1000,
                len(text),
                text[:160],
            )
        # Return the prepared result to the caller.
        return text
    except requests.exceptions.Timeout as e:
        _record_provider_failure('ollama', f"Ollama vision request timed out: {e}")
        return ''
    except Exception as e:
        recovery = attempt_ollama_auto_recover(
            reason=str(e),
            model_name=target_model,
            require_model=True,
        )
        # Choose the correct branch before the workflow continues.
        if recovery.get('ready'):
            # Protect this step so expected failures can fall back cleanly.
            try:
                # Prepare retry started for the next step.
                retry_started = time.perf_counter()
                logger.info("[VLM:ollama] retry request start model=%s", target_model)
                retry_response = requests.post(OLLAMA_API_URL, json=payload, timeout=_get_ollama_request_timeout())
                if retry_response.ok:
                    # Prepare text for the next step.
                    text = retry_response.json().get('response', '').strip()
                    if text:
                        # Trigger the side effect required for this stage.
                        logger.info(
                            "[VLM:ollama] retry request complete model=%s duration_ms=%.1f output_chars=%s preview=%r",
                            target_model,
                            (time.perf_counter() - retry_started) * 1000,
                            len(text),
                            text[:160],
                        )
                        return text
                    # Trigger the side effect required for this stage.
                    _record_provider_failure('ollama', 'Empty response text')
                    return ''
                # Protect this step so expected failures can fall back cleanly.
                try:
                    retry_error_detail = retry_response.json().get('error', '')
                except Exception:
                    retry_error_detail = retry_response.text[:160] if retry_response.text else ''
                retry_error_suffix = f": {retry_error_detail}" if retry_error_detail else ''
                _record_provider_failure('ollama', f"HTTP {retry_response.status_code}{retry_error_suffix}")
                return ''
            except Exception as retry_error:
                _record_provider_failure('ollama', str(retry_error))
                # Return the prepared result to the caller.
                return ''

        # Trigger the side effect required for this stage.
        _record_provider_failure('ollama', str(e))
        return ''


# Section: run the generate vision response workflow with clear inputs and outputs.
def _generate_vision_response(
    prompt: str,
    image_base64: str,
    temperature: float = 0.6,
    max_tokens: int = 300,
    ollama_options: dict = None,
    ollama_format=None,
) -> str:
    """Try providers in configured order until one returns a response."""
    global _LAST_PROVIDER_USED
    # Trigger the side effect required for this stage.
    _LAST_PROVIDER_FAILURES.clear()
    _LAST_PROVIDER_USED = None
    logger.info(
        "[VLM] generation route start routing_profile=%s providers=%s cache_enabled=%s prompt_chars=%s max_tokens=%s",
        os.getenv('CASM_ROUTING_PROFILE', DEFAULT_ROUTING_PROFILE),
        list(VISION_PROVIDER_ORDER),
        VISION_CACHE_ENABLED,
        len(prompt or ''),
        max_tokens,
    )

    # Prepare cache key for the next step.
    cache_key = _compute_cache_key(prompt, image_base64, temperature, max_tokens)
    cached = _get_cached_response(cache_key)
    if cached:
        # Trigger the side effect required for this stage.
        print("Using vision response from cache")
        _LAST_PROVIDER_USED = 'cache'
        logger.info(
            "[VLM] cache hit; no provider executed cache_key=%s output_chars=%s preview=%r",
            cache_key[:12],
            len(cached),
            cached[:160],
        )
        return cached

    # Process each item in this collection using the same rule set.
    for provider in VISION_PROVIDER_ORDER:
        # Trigger the side effect required for this stage.
        logger.info("[VLM] trying provider=%s", provider)
        if provider == 'model_api':
            # Prepare output for the next step.
            output = _call_model_api_vision(prompt, image_base64, max_tokens=max_tokens)
        elif provider == 'gemini':
            output = _call_gemini_vision(prompt, image_base64, temperature=temperature, max_tokens=max_tokens)
        elif provider == 'ollama':
            output = _call_ollama_vision(
                prompt,
                image_base64,
                temperature=temperature,
                max_tokens=max_tokens,
                ollama_options=ollama_options,
                ollama_format=ollama_format,
            )
        else:
            # Prepare output for the next step.
            output = ''

        # Choose the correct branch before the workflow continues.
        if output:
            print(f"Using vision provider: {provider}")
            _LAST_PROVIDER_USED = provider
            _set_cached_response(cache_key, output)
            logger.info("[VLM] provider=%s succeeded output_chars=%s", provider, len(output))
            return output

    # Trigger the side effect required for this stage.
    logger.warning("[VLM] all configured providers failed; returning user-facing provider failure message")
    return _build_user_facing_failure_message()


# Section: run the parse environment validation category workflow with clear inputs and outputs.
def _parse_environment_validation_category(answer: str) -> str:
    """Extract the A/B/C/D environment category from short model answers."""
    text = str(answer or '').strip().upper()
    if not text:
        # Return the prepared result to the caller.
        return ''
    # Prepare match for the next step.
    match = re.search(r'^\s*(?:CATEGORY\s*)?([ABCD])(?:\b|[\s\)\]\-:./])', text)
    return match.group(1) if match else ''


# Section: run the normalize caption text workflow with clear inputs and outputs.
def _normalize_caption_text(caption: str) -> str:
    """Remove model meta sections and return a concise natural-language caption."""
    if not caption:
        return ''

    # Prepare text for the next step.
    text = str(caption).strip()
    lines = [ln.strip() for ln in text.replace('\r', '\n').split('\n') if ln.strip()]
    filtered = []
    skip_prefixes = (
        'confidence score',
        'mental sandbox',
        'initial thought',
        'revised thought',
        'final answer',
        'reasoning',
    )
    # Process each item in this collection using the same rule set.
    for ln in lines:
        # Prepare low for the next step.
        low = ln.lower().strip(' *-')
        if any(low.startswith(prefix) for prefix in skip_prefixes):
            continue
        filtered.append(ln.strip(' *'))

    text = ' '.join(filtered).strip()
    text = text.replace('  ', ' ')
    text = re.sub(
        r"(?is)^here[’']s\s+(?:a\s+)?(?:brief|descriptive|factual)?\s*paragraph\s+"
        r"(?:based\s+(?:solely\s+)?on|from|describing)[^:]{0,120}:\s*",
        "",
        text,
    ).strip()
    # Prepare text for the next step.
    text = re.sub(
        r"(?is)^here(?:[â€™']s|\s+is)\s+(?:a\s+)?description\s+"
        r"(?:of\s+the\s+image\s+)?(?:based\s+(?:solely\s+)?on\s+[^:]{0,120})?:\s*",
        "",
        text,
    ).strip()
    return text


# Section: run the strip caption inference sentences workflow with clear inputs and outputs.
def _strip_caption_inference_sentences(text: str) -> str:
    """Remove evaluative caption sentences while preserving visible facts."""
    # Prepare sentences for the next step.
    sentences = re.split(r'(?<=[.!?])\s+', str(text or '').strip())
    kept = []
    blocked_patterns = (
        'appears safe',
        'appears unsafe',
        'overall setting appears',
        'overall scene appears',
        'scene suggests',
        'suggests a typical',
        'typical ',
        'immediately apparent hazards',
        'apparent hazards',
        'unusual elements',
        'not interacting with',
        'no hazards',
        'likely ',
        'probably ',
    )
    # Process each item in this collection using the same rule set.
    for sentence in sentences:
        # Prepare cleaned for the next step.
        cleaned = sentence.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(pattern in lowered for pattern in blocked_patterns):
            continue
        kept.append(cleaned)
    return ' '.join(kept).strip()


# Section: run the try parse local caption json workflow with clear inputs and outputs.
def _try_parse_local_caption_json(raw_text: str):
    """Parse Ollama local caption JSON payloads, including fenced code blocks."""
    # Choose the correct branch before the workflow continues.
    if not raw_text:
        # Return the prepared result to the caller.
        return None

    text = str(raw_text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

    start = text.find("{")
    # Prepare end for the next step.
    end = text.rfind("}")
    if start < 0 or end <= start:
        # Return the prepared result to the caller.
        return None

    candidate = text[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None

    # Return the prepared result to the caller.
    return parsed if isinstance(parsed, dict) else None


# Section: run the render local caption from json workflow with clear inputs and outputs.
def _render_local_caption_from_json(payload: dict) -> str:
    """Render a deterministic prose caption from structured local-model output."""
    if not isinstance(payload, dict):
        # Return the prepared result to the caller.
        return ""

    raw_model_caption = (
        payload.get("caption")
        or payload.get("narrative")
        or payload.get("description")
        or ""
    )
    # Choose the correct branch before the workflow continues.
    if isinstance(raw_model_caption, list):
        # Prepare raw model caption for the next step.
        raw_model_caption = " ".join(str(item).strip() for item in raw_model_caption if str(item).strip())
    model_caption = _normalize_caption_text(raw_model_caption)
    model_caption = _strip_caption_inference_sentences(model_caption)
    scene = str(payload.get("scene") or "").strip().rstrip(".")
    people_count = payload.get("people_count")
    visible_people = payload.get("visible_people")
    major_objects = payload.get("major_objects")
    ppe_visible = payload.get("ppe_visible")
    # Prepare activity context for the next step.
    activity_context = payload.get("activity_context")

    if not isinstance(visible_people, list):
        # Prepare visible people for the next step.
        visible_people = [visible_people] if visible_people else []
    if not isinstance(major_objects, list):
        major_objects = [major_objects] if major_objects else []
    if isinstance(ppe_visible, str):
        ppe_visible = [ppe_visible] if ppe_visible.strip() else []
    elif not isinstance(ppe_visible, list):
        ppe_visible = []
    # Choose the correct branch before the workflow continues.
    if not isinstance(activity_context, list):
        activity_context = [activity_context] if activity_context else []

    visible_people = [str(item).strip().strip(".") for item in visible_people if str(item).strip()]
    major_objects = [str(item).strip().strip(".") for item in major_objects if str(item).strip()]
    ppe_visible = [
        str(item).strip().strip(".")
        for item in ppe_visible
        if str(item).strip()
        and str(item).strip().lower() not in ('none', 'no ppe', 'no ppe visible', 'not visible', 'n/a', 'na')
    ]
    # Prepare activity context for the next step.
    activity_context = [str(item).strip().strip(".").lower() for item in activity_context if str(item).strip()]

    activity_map = {
        "restricted_area": "a restricted or cordoned zone",
        "restricted area": "a restricted or cordoned zone",
        "unsafe_posture": "awkward bending, leaning, or climbing posture",
        "unsafe posture": "awkward bending, leaning, or climbing posture",
        "machinery": "machinery or mobile plant near the person",
        "traffic_interface": "a road or street area with a bus or other vehicle near the person",
        "traffic interface": "a road or street area with a bus or other vehicle near the person",
        "work_at_height": "a ladder, scaffold, platform, roof, or elevated edge",
        "work at height": "a ladder, scaffold, platform, roof, or elevated edge",
        "material_stability": "stacked or potentially unstable materials",
        "material stability": "stacked or potentially unstable materials",
    }
    # Prepare activity items for the next step.
    activity_items = []
    seen_activity = set()
    for item in activity_context:
        # Prepare normalized for the next step.
        normalized = item.replace("-", "_").replace(" ", "_")
        mapped = activity_map.get(normalized) or activity_map.get(item)
        if not mapped or mapped in seen_activity:
            continue
        seen_activity.add(mapped)
        activity_items.append(mapped)

    # Section: run the join naturally workflow with clear inputs and outputs.
    def _join_naturally(items, limit: int = 4) -> str:
        cleaned = [str(item).strip() for item in items[:limit] if str(item).strip()]
        # Choose the correct branch before the workflow continues.
        if not cleaned:
            # Return the prepared result to the caller.
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    # Section: run the caption has activity terms workflow with clear inputs and outputs.
    def _caption_has_activity_terms(caption: str, activity: str) -> bool:
        # Prepare lowered for the next step.
        lowered = caption.lower()
        term_map = {
            "a restricted or cordoned zone": ("restricted", "cordoned", "barrier", "cone", "tape"),
            "awkward bending, leaning, or climbing posture": ("bending", "leaning", "climbing", "kneeling", "posture"),
            "machinery or mobile plant near the person": ("machinery", "mobile plant", "excavator", "forklift", "crane", "loader"),
            "a road or street area with a bus or other vehicle near the person": ("road", "street", "bus", "vehicle", "lane", "sidewalk"),
            "a ladder, scaffold, platform, roof, or elevated edge": ("ladder", "scaffold", "platform", "roof", "elevated", "edge"),
            "stacked or potentially unstable materials": ("stacked", "unstable", "materials", "pile", "timber"),
        }
        # Return the prepared result to the caller.
        return any(term in lowered for term in term_map.get(activity, (activity,)))

    # Choose the correct branch before the workflow continues.
    if model_caption:
        caption = model_caption.rstrip()
        lowered_caption = caption.lower()
        if not ppe_visible and not any(
            term in lowered_caption
            for term in ('ppe', 'hard hat', 'hardhat', 'helmet', 'vest', 'mask', 'glove', 'goggle', 'safety glasses')
        ):
            # Prepare caption for the next step.
            caption = f"{caption.rstrip('.')} . No PPE is clearly visible."
            caption = caption.replace(' .', '.')
        # Prepare missing activity items for the next step.
        missing_activity_items = [
            item for item in activity_items
            if not _caption_has_activity_terms(caption, item)
        ]
        if missing_activity_items:
            caption = (
                f"{caption.rstrip('.')}."
                f" The visible surroundings also include {_join_naturally(missing_activity_items, 4)}."
            )
        # Return the prepared result to the caller.
        return caption

    # Protect this step so expected failures can fall back cleanly.
    try:
        people_count = max(0, int(people_count))
    except (TypeError, ValueError):
        people_count = len(visible_people)

    if people_count <= 0 and not scene and not visible_people and not major_objects:
        return ""

    scene_lower = scene.lower()
    # Choose the correct branch before the workflow continues.
    if scene_lower in ("indoor", "outdoor"):
        # Prepare scene for the next step.
        scene = f"{scene_lower} setting"
        scene_lower = scene

    # Section: run the with article workflow with clear inputs and outputs.
    def _with_article(text: str) -> str:
        cleaned = str(text or "").strip().lower()
        if not cleaned:
            # Return the prepared result to the caller.
            return ""
        if cleaned.startswith(("a ", "an ", "the ")):
            return cleaned
        # Prepare last word for the next step.
        last_word = cleaned.split()[-1]
        plural_or_uncountable = {
            "bollards", "buildings", "cars", "cones", "equipment", "glasses",
            "gloves", "machinery", "people", "persons", "posts", "ppe",
            "shoes", "tools", "trees", "trucks", "vehicles", "workers",
        }
        if last_word in plural_or_uncountable or (last_word.endswith("s") and last_word != "bus"):
            # Return the prepared result to the caller.
            return cleaned
        article = "an" if cleaned[0] in "aeiou" else "a"
        # Return the prepared result to the caller.
        return f"{article} {cleaned}"

    # Section: run the count text workflow with clear inputs and outputs.
    def _count_text(value: int) -> str:
        words = {
            0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
            6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
        }
        return words.get(value, str(value))

    # Section: run the person phrase workflow with clear inputs and outputs.
    def _person_phrase(text: str, with_article: bool = True) -> str:
        # Prepare cleaned for the next step.
        cleaned = str(text or "").strip().lower()
        if not cleaned:
            # Return the prepared result to the caller.
            return ""
        if cleaned.startswith(("a ", "an ", "the ")):
            return cleaned if with_article else re.sub(r"^(?:a|an|the)\s+", "", cleaned)
        if re.fullmatch(r"person\s+(standing|sitting|walking|kneeling|crouching|bending|leaning|climbing)", cleaned):
            action = cleaned.split(None, 1)[1]
            return f"a {action} person" if with_article else f"person {action}"
        if with_article and cleaned.startswith(("person ", "man ", "woman ", "worker ", "individual ")):
            article = "an" if cleaned[0] in "aeiou" else "a"
            return f"{article} {cleaned}"
        # Return the prepared result to the caller.
        return _with_article(cleaned) if with_article else cleaned

    # Section: run the single person clause workflow with clear inputs and outputs.
    def _single_person_clause(text: str) -> str:
        cleaned = str(text or "").strip().lower()
        cleaned = re.sub(r"^(?:a|an|the)\s+", "", cleaned)
        if not cleaned:
            # Return the prepared result to the caller.
            return "one visible person is present"
        action_match = re.fullmatch(
            r"person\s+(standing|sitting|walking|kneeling|crouching|bending|leaning|climbing)",
            cleaned,
        )
        # Choose the correct branch before the workflow continues.
        if action_match:
            return f"one visible person is {action_match.group(1)}"
        for noun in ("person", "man", "woman", "worker", "individual"):
            prefix = f"{noun} "
            # Choose the correct branch before the workflow continues.
            if cleaned.startswith(prefix):
                # Prepare detail for the next step.
                detail = cleaned[len(prefix):].strip()
                if detail.startswith(("in ", "on ", "near ", "beside ", "wearing ", "holding ", "facing ")):
                    # Return the prepared result to the caller.
                    return f"one visible {noun} is {detail}"
                return f"one visible {cleaned}"
        # Return the prepared result to the caller.
        return f"one visible {_person_phrase(cleaned, with_article=False)}"

    # Prepare count phrase for the next step.
    count_phrase = f"{_count_text(people_count)} visible {'person' if people_count == 1 else 'people'}"
    single_person_clause = _single_person_clause(visible_people[0]) if people_count == 1 and len(visible_people) == 1 else ""
    if scene and single_person_clause:
        caption = f"The image shows {_with_article(scene)} where {single_person_clause}"
    elif single_person_clause:
        caption = f"The image shows {single_person_clause}"
    elif scene:
        # Prepare caption for the next step.
        caption = f"The image shows {_with_article(scene)} with {count_phrase}"
    else:
        caption = f"The image shows {count_phrase}"

    # Prepare people text for the next step.
    people_text = _join_naturally([_person_phrase(item) for item in visible_people], 3)
    if people_text and not single_person_clause:
        caption += f", including {people_text}"

    object_text = _join_naturally([_with_article(item) for item in major_objects], 4)
    if object_text:
        # Choose the correct branch before the workflow continues.
        if single_person_clause:
            caption += f" near {object_text}"
        else:
            caption += f", with {object_text} visible nearby"

    # Prepare activity text for the next step.
    activity_text = _join_naturally(activity_items, 4)
    if activity_text:
        caption += f", while the surrounding context includes {activity_text}"

    if ppe_visible:
        caption += f"; visible PPE includes {_join_naturally(ppe_visible, 4)}."
    else:
        caption += "; no PPE is clearly visible."

    # Return the prepared result to the caller.
    return caption.strip()


# Section: run the caption needs expansion workflow with clear inputs and outputs.
def _caption_needs_expansion(caption: str) -> bool:
    """Heuristic to trigger a richer-caption retry when output is too short/generic."""
    if not caption:
        # Return the prepared result to the caller.
        return True
    lowered = caption.lower()
    if len(caption) < 120:
        return True
    # Prepare generic markers for the next step.
    generic_markers = (
        'person is visible',
        'outdoor setting',
        'a person is visible',
        'people are visible',
    )
    if any(marker in lowered for marker in generic_markers):
        # Return the prepared result to the caller.
        return True
    if 'indoor setting' in lowered and len(caption) < 180:
        return True
    # Return the prepared result to the caller.
    return False

# Section: run the check ollama running workflow with clear inputs and outputs.
def check_ollama_running():
    """Check if Ollama is running."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        # Return the prepared result to the caller.
        return response.status_code == 200
    except Exception:
        return False

# Section: run the check model available workflow with clear inputs and outputs.
def check_model_available(model_name):
    """Check if the specified model is available in Ollama."""
    # Prepare target for the next step.
    target = str(model_name or '').strip()
    if not target:
        return False

    try:
        # Prepare response for the next step.
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        if response.status_code == 200:
            # Prepare models for the next step.
            models = response.json().get('models', [])
            for model in models:
                # Choose the correct branch before the workflow continues.
                if not isinstance(model, dict):
                    continue
                name = str(model.get('name') or model.get('model') or '').strip()
                if not name:
                    continue
                if name == target or name.startswith(f"{target}:") or name.split(':', 1)[0] == target:
                    # Return the prepared result to the caller.
                    return True
    except Exception:
        pass
    # Return the prepared result to the caller.
    return False


# Section: run the ensure ollama local caption ready workflow with clear inputs and outputs.
def _ensure_ollama_local_caption_ready() -> dict:
    """Check local model readiness and optionally warm it before the image call."""
    target_model = str(OLLAMA_MODEL_NAME or '').strip() or 'gemma3:4b'
    if not check_ollama_running():
        # Prepare recovery for the next step.
        recovery = attempt_ollama_auto_recover(
            reason='Ollama service is not running',
            model_name=target_model,
            require_model=True,
        )
        if not recovery.get('ready'):
            # Return the prepared result to the caller.
            return {'ready': False, 'error': 'Ollama service is not running'}

    # Choose the correct branch before the workflow continues.
    if not check_model_available(target_model):
        # Prepare recovery for the next step.
        recovery = attempt_ollama_auto_recover(
            reason=f"Model '{target_model}' is not available",
            model_name=target_model,
            require_model=True,
        )
        if not recovery.get('ready'):
            # Return the prepared result to the caller.
            return {'ready': False, 'error': f"Model '{target_model}' is not available"}

    # Choose the correct branch before the workflow continues.
    if not LOCAL_OLLAMA_CAPTION_WARMUP_ENABLED:
        # Return the prepared result to the caller.
        return {'ready': True, 'warmup_skipped': True}

    payload = {
        'model': target_model,
        'prompt': 'Return OK only.',
        'stream': False,
        'keep_alive': os.getenv('OLLAMA_VISION_KEEP_ALIVE', '5m'),
        'options': {
            'temperature': 0.0,
            'num_predict': 4,
            'num_ctx': 512,
        },
    }
    # Choose the correct branch before the workflow continues.
    if OLLAMA_VISION_NUM_THREAD > 0:
        # Prepare values needed by the next step.
        payload['options']['num_thread'] = OLLAMA_VISION_NUM_THREAD

    try:
        started = time.perf_counter()
        response = requests.post(
            OLLAMA_API_URL,
            json=payload,
            timeout=(
                max(1, LOCAL_OLLAMA_VISION_CONNECT_TIMEOUT_SECONDS),
                max(8, LOCAL_OLLAMA_CAPTION_WARMUP_TIMEOUT_SECONDS),
            ),
        )
        # Prepare elapsed ms for the next step.
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if not response.ok:
            # Return the prepared result to the caller.
            return {
                'ready': False,
                'error': f"Ollama warm-up failed with HTTP {response.status_code}",
                'elapsed_ms': elapsed_ms,
            }
        text = ''
        try:
            text = str((response.json() or {}).get('response') or '').strip()
        except Exception:
            # Prepare text for the next step.
            text = ''
        # Return the prepared result to the caller.
        return {'ready': True, 'elapsed_ms': elapsed_ms, 'response_preview': text[:24]}
    except requests.exceptions.Timeout as e:
        return {
            'ready': False,
            'error': f"Ollama warm-up timed out after {LOCAL_OLLAMA_CAPTION_WARMUP_TIMEOUT_SECONDS}s: {e}",
        }
    except Exception as e:
        return {'ready': False, 'error': f"Ollama warm-up failed: {e}"}

# Section: run the caption image llava workflow with clear inputs and outputs.
def caption_image_llava(image_path, prompt=None):
    """
    Generate caption using Qwen2.5-VL via Ollama API.

    Args:
        image_path: Path to image file

    Returns:
        Caption string or None if failed
    """
    # Verify image exists
    # Choose the correct branch before the workflow continues.
    if not Path(image_path).exists():
        # Trigger the side effect required for this stage.
        print(f"Error: Image file not found at {image_path}")
        return None

    print(f"Image loaded: {Path(image_path).name}")

    strict_local_profile = (
        str(os.getenv('STRICT_PROVIDER_MODE_SPLIT', 'true')).strip().lower() in ('1', 'true', 'yes', 'on')
        and str(os.getenv('CASM_ROUTING_PROFILE', '')).strip().lower() == 'local'
    )

    # Local Gemma/Ollama needs strict grounding, but over-compressing the prompt
    # starves useful visual detail. Keep the local prompt factual while still
    # asking for the richer observer-style caption Gemma produced in earlier
    # local runs.
    if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER:
        structured_prompt = """Return JSON only with keys caption, scene, people_count, visible_people, major_objects, ppe_visible, activity_context.

Requirements:
- caption must be one factual paragraph with 5-7 complete sentences from visible evidence only.
- In caption, describe indoor/outdoor setting, visible people count, visible body region, posture, gaze direction, clothing, eyewear, nearby room/site objects, windows, walls, vehicles, tools, or machinery when clearly visible.
- Mention PPE only when clearly visible; if none is visible, say no PPE is clearly visible.
- Do not use markdown, safety conclusions, legal conclusions, hazard conclusions, or guessed worksite context.
- If visibility is unclear, say it is unclear instead of guessing."""
        default_prompt = """Describe only what is clearly visible in this image in one factual paragraph of 5-7 complete sentences.

Requirements:
- Start with whether the scene is indoor or outdoor and the total visible people count, including partially visible people at the image edges.
- Mention visible body region, posture, gaze direction, clothing, eyewear, vehicles, buildings, trees, posts, tools, machinery, windows, walls, or other nearby objects only when clearly visible.
- Mention PPE only when clearly visible; if none is visible, explicitly say no PPE is visible.

Strict grounding rules:
- Do not use intro phrases like "Here is a description" or "Based on the image".
- Do not guess hidden actions, occupations, hazards, traffic context, worksite context, or unseen objects.
- If something is unclear, say it is unclear instead of inventing detail.
"""
        # Prepare expansion prompt for the next step.
        expansion_prompt = """Rewrite the caption with slightly richer factual detail from the image only.

Requirements:
- Keep one paragraph with 5-7 complete sentences.
- Start with indoor/outdoor and total visible people count, including edge-cropped people.
- Describe the most visible people, body region, posture, gaze direction, clothing, eyewear, and major visible background objects such as vehicles, windows, walls, room objects, tools, or buildings.
- End by stating whether any PPE is visible.
- No intro phrase, no bullet points, no guessing.
"""
    else:
        # Build prompt for higher quality people/action/situation captions (works across model_api/gemini/ollama).
        # Prepare default prompt for the next step.
        default_prompt = """You are a workplace visual analyst. Write one descriptive visual caption from this image only.

Output requirements:
- Single paragraph, 5-8 complete narrative sentences, similar to a safety observer's visual note.
- Do not answer with only one sentence.
- Start in the style "The scene depicts..." or "The image depicts..." and name the actual setting plus total visible people count.
- Describe visible body region, posture, gaze direction, clothing, eyewear, held objects, and nearby room or site features such as shelves, cabinets, windows, walls, desks, vehicles, tools, or machinery when clearly visible.
- Mention PPE only when clearly visible; if none is visible, say no PPE is clearly visible.

Strict grounding rules:
- Do not begin with meta wording such as "Here is a description" or "Based on the image".
- Do not invent objects, actions, hazards, phones, tablets, vehicles, roads, machinery, tools, or construction activity.
- Do not infer a worksite or traffic context unless those objects are clearly visible.
- Do not state that the scene is safe/unsafe, typical, likely, or suggestive of a condition.
- Do not state that hazards, unusual elements, machinery, or traffic interactions are absent; only describe visible objects and PPE absence.
- If visibility is unclear, say it is unclear instead of guessing.
- Natural professional English, no bullet points, no markdown, no preamble.
"""
        # Prepare expansion prompt for the next step.
        expansion_prompt = """The previous caption was too short or generic. Rewrite it with richer factual detail from the image only.

Requirements:
- Single paragraph, 5-8 complete narrative sentences.
- Do not answer with only one sentence.
- Start in the style "The scene depicts..." or "The image depicts..." and state environment type and visible people count first.
- For each visible person: visible body region, posture, gaze direction, clothing, eyewear, held objects, and context near objects.
- Mention nearby objects only when visible.
- Mention PPE only when clearly visible; if not visible, say no PPE is clearly visible.
- Do not write safety conclusions such as safe, unsafe, typical, likely, no hazards, or no interaction with traffic/machinery.
- No bullet points, no markdown, no meta commentary, no "Here is a description" preamble.
"""
    # Prepare caption prompt for the next step.
    caption_prompt = str(prompt or '').strip() or default_prompt

    if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER and not str(prompt or '').strip():
        # Prepare readiness for the next step.
        readiness = _ensure_ollama_local_caption_ready()
        if not readiness.get('ready'):
            # Trigger the side effect required for this stage.
            _record_provider_failure('ollama', readiness.get('error') or 'Ollama local caption warm-up failed')
            return _build_user_facing_failure_message()

    # Encode image to base64. In strict local mode, use a smaller JPEG so a
    # slow local VLM cannot dominate the whole report-generation window.
    try:
        if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER:
            image_base64 = _encode_local_caption_image(image_path)
        else:
            # Prepare image base64 for the next step.
            image_base64 = encode_image_to_base64(image_path)
    except Exception as e:
        # Trigger the side effect required for this stage.
        print(f"Error encoding image: {e}")
        return None

    # Generate caption using provider routing
    # Protect this step so expected failures can fall back cleanly.
    try:
        print("Generating caption...")
        if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER and not str(prompt or '').strip():
            # Prepare structured caption for the next step.
            structured_caption = _generate_vision_response(
                prompt=structured_prompt,
                image_base64=image_base64,
                temperature=0.18,
                max_tokens=LOCAL_OLLAMA_STRUCTURED_CAPTION_MAX_TOKENS,
                ollama_options={'num_ctx': 1536}
            )
            if structured_caption and not structured_caption.startswith('ALERT_'):
                # Prepare parsed structured caption for the next step.
                parsed_structured_caption = _try_parse_local_caption_json(structured_caption)
                rendered_structured_caption = _render_local_caption_from_json(parsed_structured_caption or {})
                if rendered_structured_caption:
                    # Trigger the side effect required for this stage.
                    print("Caption generation complete!")
                    return rendered_structured_caption
            # Choose the correct branch before the workflow continues.
            elif structured_caption:
                return structured_caption

        # Prepare caption for the next step.
        caption = _generate_vision_response(
            prompt=caption_prompt,
            image_base64=image_base64,
            temperature=0.6,
            max_tokens=LOCAL_OLLAMA_CAPTION_MAX_TOKENS if strict_local_profile else 650
        )

        if caption:
            # Prepare caption for the next step.
            caption = _normalize_caption_text(caption)
            caption = _strip_caption_inference_sentences(caption)

            should_expand = _caption_needs_expansion(caption) and not caption.startswith('ALERT_')
            if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER:
                # Prepare should expand for the next step.
                should_expand = bool(LOCAL_OLLAMA_CAPTION_EXPANSION_ENABLED and should_expand)

            if should_expand:
                expanded = _generate_vision_response(
                    prompt=expansion_prompt,
                    image_base64=image_base64,
                    temperature=0.4,
                    max_tokens=750
                )
                # Prepare expanded for the next step.
                expanded = _normalize_caption_text(expanded)
                expanded = _strip_caption_inference_sentences(expanded)
                if expanded and not expanded.startswith('ALERT_'):
                    # Prepare caption for the next step.
                    caption = expanded

            # Clean up common prefixes
            # Prepare prefixes to remove for the next step.
            prefixes_to_remove = [
                "In the image, ",
                "In the image ",
                "In this image, ",
                "In this image "
            ]

            for prefix in prefixes_to_remove:
                # Choose the correct branch before the workflow continues.
                if caption.startswith(prefix):
                    # Prepare caption for the next step.
                    caption = caption[len(prefix):]
                    # Capitalize first letter after removal
                    if caption:
                        # Prepare caption for the next step.
                        caption = caption[0].upper() + caption[1:]
                    break

            # Ensure complete sentence - truncate to last period if incomplete
            # Choose the correct branch before the workflow continues.
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
        # Trigger the side effect required for this stage.
        print(f"Error during caption generation: {e}")
        return None


# Section: run the validate work environment workflow with clear inputs and outputs.
def validate_work_environment(image_path):
    """
    Quick check to determine if the image shows a construction-related work
    environment where PPE report generation is appropriate.

    CLASSIFICATION LOGIC:
    =====================
    The LLaVA model classifies the scene into 4 categories:

    A) CONSTRUCTION/INDUSTRIAL WORK ZONE  is_valid=TRUE, confidence=HIGH
       - Construction sites, factories, warehouses, workshops
       - Manufacturing plants, work zones, industrial areas
       - Any place where PPE is typically required

    B) OFFICE/COMMERCIAL  is_valid=FALSE, confidence=MEDIUM
       - Office buildings, retail stores, meeting rooms
       - Not enough construction-related evidence for a PPE violation report

    C) RESIDENTIAL/CASUAL  is_valid=FALSE, confidence=HIGH
       - Homes, living rooms, bedrooms, kitchens
       - Parks, beaches, restaurants, casual settings
       - These are SKIPPED (no report generated)

    D) OTHER/UNCLEAR  is_valid=FALSE, confidence=LOW
       - Outdoor roads, vehicle interiors, unclear scenes
       - Skipped unless clear construction/industrial/work-zone evidence is present

    ONLY Category A proceeds to report generation.
    Categories B, C, and D are skipped.

    Args:
        image_path: Path to image file

    Returns:
        dict with:
            - is_valid: bool - True only if this is category A
            - confidence: str - 'high', 'medium', 'low'
            - environment_type: str - type of environment detected
            - reason: str - explanation
    """
    # Trigger the side effect required for this stage.
    print(f"Validating work environment...")

    # Section: run the with provider diagnostics workflow with clear inputs and outputs.
    def _with_provider_diagnostics(result: dict) -> dict:
        # Prepare diagnostics for the next step.
        diagnostics = get_runtime_provider_diagnostics()
        provider = diagnostics.get('last_provider_used')
        model_by_provider = {
            'gemini': diagnostics.get('gemini_model'),
            'ollama': diagnostics.get('ollama_model'),
            'model_api': diagnostics.get('vision_api_model'),
        }
        result.update({
            'provider': provider,
            'model': model_by_provider.get(str(provider or '').lower()) or diagnostics.get('vision_api_model'),
            'vision_provider_order': diagnostics.get('vision_provider_order'),
            'routing_profile': os.getenv('CASM_ROUTING_PROFILE', DEFAULT_ROUTING_PROFILE),
        })
        # Return the prepared result to the caller.
        return result

    # Verify image exists
    # Choose the correct branch before the workflow continues.
    if not Path(image_path).exists():
        print(f"Error: Image not found at {image_path}")
        return _with_provider_diagnostics({
            'is_valid': False,
            'confidence': 'low',
            'environment_type': 'unknown',
            'reason': 'Image file not found',
        })

    # Quick environment classification prompt - strict scene recognition.
    # Prepare prompt for the next step.
    prompt = """Classify the ACTUAL environment in the image for PPE report generation.

A = valid construction/industrial/work zone: construction site, factory, warehouse, workshop, scaffolding, concrete/lumber, machinery, barriers, tools, or active roadworks with cones/signage/workers.
B = office/commercial but not construction-related: office desks, meeting rooms, retail, checkout counters, business furniture.
C = residential/casual: home, living room, bedroom, kitchen, sofa, dining area, park, beach, restaurant, cafe, leisure venue. Safety gear alone does NOT make it A.
D = other/unclear: public street, sidewalk, bus stop, vehicle area, road without visible roadworks, unclear background.

Only choose A when visible construction, industrial, or active work-zone evidence is clear.
Answer as one category letter followed by a dash and 2 to 5 words, for example: "A - construction site", "C - home living room", or "D - public street"."""

    # Encode image to base64
    # Protect this step so expected failures can fall back cleanly.
    try:
        image_base64 = _encode_environment_validation_image(image_path)
    except Exception as e:
        print(f"Error encoding image: {e}")
        return _with_provider_diagnostics({
            'is_valid': False,
            'confidence': 'low',
            'environment_type': 'unknown',
            'reason': 'Image encoding failed',
        })

    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare raw answer for the next step.
        raw_answer = _generate_vision_response(
            prompt=prompt,
            image_base64=image_base64,
            temperature=0.2,
            max_tokens=24,
            ollama_options={
                'num_ctx': ENVIRONMENT_VALIDATION_OLLAMA_NUM_CTX,
                'keep_alive': ENVIRONMENT_VALIDATION_OLLAMA_KEEP_ALIVE,
            },
        )
        # Prepare answer for the next step.
        answer = str(raw_answer or '').strip()

        if not answer:
            # Return the prepared result to the caller.
            return _with_provider_diagnostics({
                'is_valid': False,
                'confidence': 'low',
                'environment_type': 'unknown',
                'reason': 'No response from configured providers'
            })

        # Trigger the side effect required for this stage.
        print(f"Environment check result: {answer.upper()}")

        # Parse the response - ONLY category A proceeds to report generation.
        category = _parse_environment_validation_category(answer)
        if category == 'A':
            return _with_provider_diagnostics({
                'is_valid': True,
                'confidence': 'high',
                'environment_type': 'construction/industrial',
                'reason': answer,
                'raw_response': answer,
            })
        # Choose the correct branch before the workflow continues.
        elif category == 'B':
            return _with_provider_diagnostics({
                'is_valid': False,
                'confidence': 'medium',
                'environment_type': 'office/commercial',
                'reason': answer,
                'raw_response': answer,
            })
        elif category == 'C':
            # Return the prepared result to the caller.
            return _with_provider_diagnostics({
                'is_valid': False,
                'confidence': 'high',
                'environment_type': 'residential/casual',
                'reason': answer,
                'raw_response': answer,
            })
        # Choose the correct branch before the workflow continues.
        elif category == 'D':
            return _with_provider_diagnostics({
                'is_valid': False,
                'confidence': 'low',
                'environment_type': 'other',
                'reason': answer,
                'raw_response': answer,
            })
        else:
            # Couldn't parse - fail closed so non-construction scenes cannot generate reports.
            # Return the prepared result to the caller.
            return _with_provider_diagnostics({
                'is_valid': False,
                'confidence': 'low',
                'environment_type': 'unknown',
                'reason': f'Unparseable response: {answer[:50]}'
            })

    except Exception as e:
        # Trigger the side effect required for this stage.
        print(f"Environment validation error: {e} - blocking report generation")
        return _with_provider_diagnostics({
            'is_valid': False,
            'confidence': 'low',
            'environment_type': 'unknown',
            'reason': str(e),
        })


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    # Choose the correct branch before the workflow continues.
    if len(sys.argv) < 2:
        # Trigger the side effect required for this stage.
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
            # Trigger the side effect required for this stage.
            print("\n--- Generating full caption ---")
            caption = caption_image_llava(image_path)
            if caption:
                # Trigger the side effect required for this stage.
                print("Caption:", caption)
        else:
            print("\nSkipping caption. Not a valid work environment")

    except ImportError as e:
        # Trigger the side effect required for this stage.
        print(f"\nImportError: {e}")
        print("Please ensure you have installed required packages:")
        print("pip install requests")
        print("\nAlso ensure Ollama is installed and the model is pulled:")
        print(f"ollama pull {OLLAMA_MODEL_NAME}")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
