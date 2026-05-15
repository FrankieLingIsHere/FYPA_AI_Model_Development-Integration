"""
Image Captioning with local Ollama vision model

Fast and accurate image captioning using the configured local Ollama model.

Usage:
    python caption_image.py path/to/image.jpg

Requirements:
    - Ollama installed and running
    - Unified local model: ollama pull gemma3:4b
"""
import sys
import os
import base64
import requests
import json
import time
import hashlib
import re
import shutil
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# --- PROVIDER CONFIGURATION ---
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_TAGS_URL = os.getenv('OLLAMA_TAGS_URL', f"{OLLAMA_BASE_URL}/api/tags")
OLLAMA_MODEL_NAME = os.getenv('OLLAMA_VISION_MODEL', os.getenv('OLLAMA_MODEL', os.getenv('LOCAL_OLLAMA_UNIFIED_MODEL', 'gemma3:4b')))
DEFAULT_ROUTING_PROFILE = str(os.getenv('CASM_ROUTING_PROFILE', 'cloud')).strip().lower()
DEFAULT_VISION_PROVIDER_ORDER = 'ollama' if DEFAULT_ROUTING_PROFILE == 'local' else 'gemini'


def _safe_int_env(name: str, default: int) -> int:
    """Parse integer environment variables safely with fallback."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)

VISION_PROVIDER_ORDER = [
    provider.strip().lower()
    for provider in os.getenv('VISION_PROVIDER_ORDER', DEFAULT_VISION_PROVIDER_ORDER).split(',')
    if provider.strip()
]

STRICT_PROVIDER_MODE_SPLIT = os.getenv('STRICT_PROVIDER_MODE_SPLIT', 'true').lower() in ('1', 'true', 'yes', 'on')


def _strict_vision_order_for_profile(profile: str):
    """Return strict provider order for local/cloud profile."""
    normalized = str(profile or '').strip().lower()
    if normalized == 'local':
        return ['ollama']
    if normalized == 'cloud':
        return ['gemini']
    return []


if STRICT_PROVIDER_MODE_SPLIT:
    profile_order = _strict_vision_order_for_profile(os.getenv('CASM_ROUTING_PROFILE', DEFAULT_ROUTING_PROFILE))
    if profile_order:
        VISION_PROVIDER_ORDER = profile_order

# OpenAI-compatible model API (e.g., first-party/hosted Qwen, Moondream, Llama providers)
VISION_API_URL = os.getenv('VISION_API_URL', '').strip()
VISION_API_KEY = os.getenv('VISION_API_KEY', '').strip()
VISION_API_MODEL = os.getenv('VISION_API_MODEL', '').strip()

# Google Gemini fallback
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_VISION_MODEL = os.getenv('GEMINI_VISION_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')).strip()
GEMINI_VISION_THINKING_BUDGET = _safe_int_env('GEMINI_VISION_THINKING_BUDGET', 0)

TIMEOUT = int(os.getenv('VISION_TIMEOUT', '60'))
OLLAMA_CONNECT_TIMEOUT_SECONDS = max(1, _safe_int_env('OLLAMA_CONNECT_TIMEOUT_SECONDS', 8))
OLLAMA_VISION_READ_TIMEOUT_SECONDS = _safe_int_env('OLLAMA_VISION_READ_TIMEOUT_SECONDS', 360)
OLLAMA_VISION_NUM_CTX = max(512, _safe_int_env('OLLAMA_VISION_NUM_CTX', 2048))
OLLAMA_VISION_NUM_GPU = _safe_int_env('OLLAMA_VISION_NUM_GPU', 0)
OLLAMA_VISION_NUM_THREAD = _safe_int_env('OLLAMA_VISION_NUM_THREAD', 4)
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
# ---------------------------


def _get_ollama_request_timeout():
    """Use finite connect/read timeouts so a stalled local model cannot wedge routing."""
    if OLLAMA_VISION_READ_TIMEOUT_SECONDS <= 0:
        return (OLLAMA_CONNECT_TIMEOUT_SECONDS, 120)
    return (OLLAMA_CONNECT_TIMEOUT_SECONDS, max(1, OLLAMA_VISION_READ_TIMEOUT_SECONDS))


def _record_provider_failure(provider: str, reason: str):
    """Record provider-level failure reasons for user-facing diagnostics."""
    clean_reason = str(reason or '').strip()
    _LAST_PROVIDER_FAILURES.append({
        'provider': provider,
        'reason': clean_reason
    })
    logger.warning("[VLM:%s] provider failure: %s", provider, clean_reason)


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


def get_runtime_provider_diagnostics() -> dict:
    """Return runtime diagnostics for vision provider routing and cooldown state."""
    cooldown_remaining = max(0, int(_gemini_quota_backoff_until - time.time()))
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
        'vision_api_model': VISION_API_MODEL,
    }


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
        if STRICT_PROVIDER_MODE_SPLIT:
            requested_profile = str(settings.get('routing_profile') or os.getenv('CASM_ROUTING_PROFILE', '')).strip().lower()
            strict_order = _strict_vision_order_for_profile(requested_profile)
            if strict_order:
                VISION_PROVIDER_ORDER = strict_order
            elif normalized:
                inferred_profile = 'local' if normalized[0] == 'ollama' else 'cloud'
                VISION_PROVIDER_ORDER = _strict_vision_order_for_profile(inferred_profile)
        elif normalized:
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
    if GEMINI_VISION_THINKING_BUDGET >= 0:
        payload['generationConfig']['thinkingConfig'] = {
            'thinkingBudget': GEMINI_VISION_THINKING_BUDGET
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


def _detect_ollama_executable() -> str:
    """Return best-effort Ollama executable path, including common non-PATH installs."""
    from_path = shutil.which('ollama')
    if from_path:
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
    elif sys.platform == 'darwin':
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

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return ''


def _start_ollama_service_if_needed(wait_seconds: int = 8) -> dict:
    """Best-effort start for local Ollama service when it is not running."""
    if check_ollama_running():
        return {
            'attempted': False,
            'started': False,
            'already_running': True,
            'error': None,
        }

    ollama_cmd = _detect_ollama_executable()
    if not ollama_cmd:
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

        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs['start_new_session'] = True

        cmd_lower = os.path.basename(ollama_cmd).lower()
        if cmd_lower == 'ollama app.exe':
            subprocess.Popen([ollama_cmd], **kwargs)
        else:
            subprocess.Popen([ollama_cmd, 'serve'], **kwargs)

        deadline = time.time() + max(1, int(wait_seconds))
        while time.time() < deadline:
            if check_ollama_running():
                return {
                    'attempted': True,
                    'started': True,
                    'already_running': False,
                    'error': None,
                }
            time.sleep(1)

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


def _pull_ollama_model_if_needed(model_name: str, timeout_seconds: int = 600) -> dict:
    """Best-effort pull for required Ollama model when not yet available."""
    target_model = str(model_name or '').strip() or OLLAMA_MODEL_NAME
    if check_model_available(target_model):
        return {
            'attempted': False,
            'pulled': False,
            'already_available': True,
            'error': None,
        }

    if not check_ollama_running():
        return {
            'attempted': False,
            'pulled': False,
            'already_available': False,
            'error': 'Ollama is not running; cannot pull model yet.',
        }

    pull_url = f"{OLLAMA_BASE_URL}/api/pull"
    try:
        response = requests.post(
            pull_url,
            json={'model': target_model, 'stream': False},
            timeout=max(60, int(timeout_seconds)),
        )
        if not response.ok:
            return {
                'attempted': True,
                'pulled': False,
                'already_available': False,
                'error': f"Model pull failed (HTTP {response.status_code})",
            }

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


def attempt_ollama_auto_recover(reason: str = '', model_name: str = '', require_model: bool = True) -> dict:
    """Attempt to recover Ollama runtime readiness (service + model) with cooldown."""
    global _ollama_auto_recover_next_allowed_ts

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

    running = check_ollama_running()
    model_ready = check_model_available(target_model) if running else False
    if running and (model_ready or not require_model):
        result['ready'] = True
        return result

    if not OLLAMA_AUTO_RECOVER_ENABLED:
        return result

    if now < _ollama_auto_recover_next_allowed_ts:
        result['cooldown_skipped'] = True
        return result

    _ollama_auto_recover_next_allowed_ts = now + float(OLLAMA_AUTO_RECOVER_COOLDOWN_SECONDS)
    result['attempted'] = True

    if not running:
        result['start_service'] = _start_ollama_service_if_needed(wait_seconds=OLLAMA_AUTO_RECOVER_WAIT_SECONDS)

    running = check_ollama_running()
    if require_model and running and not check_model_available(target_model):
        result['pull_model'] = _pull_ollama_model_if_needed(
            target_model,
            timeout_seconds=OLLAMA_AUTO_RECOVER_PULL_TIMEOUT_SECONDS,
        )

    running = check_ollama_running()
    model_ready = check_model_available(target_model) if running else False
    result['ready'] = bool(running and (model_ready or not require_model))
    return result


def _call_ollama_vision(prompt: str, image_base64: str, temperature: float = 0.6, max_tokens: int = 250) -> str:
    """Call local Ollama vision model."""
    target_model = str(OLLAMA_MODEL_NAME or '').strip() or 'gemma3:4b'
    logger.info(
        "[VLM:ollama] preflight start model=%s api_url=%s timeout=%s prompt_chars=%s image_sha256=%s",
        target_model,
        OLLAMA_API_URL,
        _get_ollama_request_timeout(),
        len(prompt or ''),
        hashlib.sha256((image_base64 or '').encode('utf-8')).hexdigest()[:12],
    )

    if not check_ollama_running():
        logger.warning("[VLM:ollama] service is not running before auto-recover")
        recovery = attempt_ollama_auto_recover(
            reason='Ollama service is not running',
            model_name=target_model,
            require_model=True,
        )
        if not recovery.get('ready'):
            _record_provider_failure('ollama', 'Ollama service is not running')
            return ''

    if not check_model_available(target_model):
        logger.warning("[VLM:ollama] model '%s' is not available before auto-recover", target_model)
        recovery = attempt_ollama_auto_recover(
            reason=f"Model '{target_model}' is not available",
            model_name=target_model,
            require_model=True,
        )
        if not recovery.get('ready'):
            _record_provider_failure('ollama', f"Model '{target_model}' is not available")
            return ''

    payload = {
        'model': target_model,
        'prompt': prompt,
        'images': [image_base64],
        'stream': False,
        'keep_alive': os.getenv('OLLAMA_VISION_KEEP_ALIVE', '0'),
        'options': {
            'temperature': temperature,
            'num_predict': max_tokens,
            'num_ctx': OLLAMA_VISION_NUM_CTX,
            'num_gpu': OLLAMA_VISION_NUM_GPU,
        }
    }
    if OLLAMA_VISION_NUM_THREAD > 0:
        payload['options']['num_thread'] = OLLAMA_VISION_NUM_THREAD

    try:
        started = time.perf_counter()
        logger.info("[VLM:ollama] request start model=%s", target_model)
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=_get_ollama_request_timeout())

        if not response.ok and response.status_code in OLLAMA_AUTO_RECOVER_RETRY_HTTP_STATUSES:
            logger.warning("[VLM:ollama] HTTP %s; attempting auto-recover before retry", response.status_code)
            recovery = attempt_ollama_auto_recover(
                reason=f"HTTP {response.status_code}",
                model_name=target_model,
                require_model=True,
            )
            if recovery.get('ready'):
                response = requests.post(OLLAMA_API_URL, json=payload, timeout=_get_ollama_request_timeout())

        if not response.ok:
            try:
                error_detail = response.json().get('error', '')
            except Exception:
                error_detail = response.text[:160] if response.text else ''
            error_suffix = f": {error_detail}" if error_detail else ''
            _record_provider_failure('ollama', f"HTTP {response.status_code}{error_suffix}")
            return ''

        text = response.json().get('response', '').strip()
        if not text:
            _record_provider_failure('ollama', 'Empty response text')
        else:
            logger.info(
                "[VLM:ollama] request complete model=%s duration_ms=%.1f output_chars=%s preview=%r",
                target_model,
                (time.perf_counter() - started) * 1000,
                len(text),
                text[:160],
            )
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
        if recovery.get('ready'):
            try:
                retry_started = time.perf_counter()
                logger.info("[VLM:ollama] retry request start model=%s", target_model)
                retry_response = requests.post(OLLAMA_API_URL, json=payload, timeout=_get_ollama_request_timeout())
                if retry_response.ok:
                    text = retry_response.json().get('response', '').strip()
                    if text:
                        logger.info(
                            "[VLM:ollama] retry request complete model=%s duration_ms=%.1f output_chars=%s preview=%r",
                            target_model,
                            (time.perf_counter() - retry_started) * 1000,
                            len(text),
                            text[:160],
                        )
                        return text
                    _record_provider_failure('ollama', 'Empty response text')
                    return ''
                try:
                    retry_error_detail = retry_response.json().get('error', '')
                except Exception:
                    retry_error_detail = retry_response.text[:160] if retry_response.text else ''
                retry_error_suffix = f": {retry_error_detail}" if retry_error_detail else ''
                _record_provider_failure('ollama', f"HTTP {retry_response.status_code}{retry_error_suffix}")
                return ''
            except Exception as retry_error:
                _record_provider_failure('ollama', str(retry_error))
                return ''

        _record_provider_failure('ollama', str(e))
        return ''


def _generate_vision_response(prompt: str, image_base64: str, temperature: float = 0.6, max_tokens: int = 300) -> str:
    """Try providers in configured order until one returns a response."""
    global _LAST_PROVIDER_USED
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

    cache_key = _compute_cache_key(prompt, image_base64, temperature, max_tokens)
    cached = _get_cached_response(cache_key)
    if cached:
        print("Using vision response from cache")
        _LAST_PROVIDER_USED = 'cache'
        logger.info(
            "[VLM] cache hit; no provider executed cache_key=%s output_chars=%s preview=%r",
            cache_key[:12],
            len(cached),
            cached[:160],
        )
        return cached

    for provider in VISION_PROVIDER_ORDER:
        logger.info("[VLM] trying provider=%s", provider)
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
            _LAST_PROVIDER_USED = provider
            _set_cached_response(cache_key, output)
            logger.info("[VLM] provider=%s succeeded output_chars=%s", provider, len(output))
            return output

    logger.warning("[VLM] all configured providers failed; returning user-facing provider failure message")
    return _build_user_facing_failure_message()


def _normalize_caption_text(caption: str) -> str:
    """Remove model meta sections and return a concise natural-language caption."""
    if not caption:
        return ''

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
    for ln in lines:
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
    text = re.sub(
        r"(?is)^here(?:[â€™']s|\s+is)\s+(?:a\s+)?description\s+"
        r"(?:of\s+the\s+image\s+)?(?:based\s+(?:solely\s+)?on\s+[^:]{0,120})?:\s*",
        "",
        text,
    ).strip()
    return text


def _try_parse_local_caption_json(raw_text: str):
    """Parse Ollama local caption JSON payloads, including fenced code blocks."""
    if not raw_text:
        return None

    text = str(raw_text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None

    candidate = text[start:end + 1]
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None

    return parsed if isinstance(parsed, dict) else None


def _render_local_caption_from_json(payload: dict) -> str:
    """Render a deterministic prose caption from structured local-model output."""
    if not isinstance(payload, dict):
        return ""

    scene = str(payload.get("scene") or "").strip().rstrip(".")
    people_count = payload.get("people_count")
    visible_people = payload.get("visible_people")
    major_objects = payload.get("major_objects")
    ppe_visible = payload.get("ppe_visible")
    activity_context = payload.get("activity_context")

    if not isinstance(visible_people, list):
        visible_people = [visible_people] if visible_people else []
    if not isinstance(major_objects, list):
        major_objects = [major_objects] if major_objects else []
    if isinstance(ppe_visible, str):
        ppe_visible = [ppe_visible] if ppe_visible.strip() else []
    elif not isinstance(ppe_visible, list):
        ppe_visible = []
    if not isinstance(activity_context, list):
        activity_context = [activity_context] if activity_context else []

    visible_people = [str(item).strip().strip(".") for item in visible_people if str(item).strip()]
    major_objects = [str(item).strip().strip(".") for item in major_objects if str(item).strip()]
    ppe_visible = [str(item).strip().strip(".") for item in ppe_visible if str(item).strip()]
    activity_context = [str(item).strip().strip(".").lower() for item in activity_context if str(item).strip()]

    activity_map = {
        "restricted_area": "restricted area or cordoned zone",
        "restricted area": "restricted area or cordoned zone",
        "unsafe_posture": "unsafe posture or awkward body position",
        "unsafe posture": "unsafe posture or awkward body position",
        "machinery": "machinery or mobile plant nearby",
        "traffic_interface": "traffic interface with street, road, bus, or vehicle context",
        "traffic interface": "traffic interface with street, road, bus, or vehicle context",
        "work_at_height": "work at height or elevated edge",
        "work at height": "work at height or elevated edge",
        "material_stability": "stacked or unstable materials",
        "material stability": "stacked or unstable materials",
    }
    activity_items = []
    seen_activity = set()
    for item in activity_context:
        normalized = item.replace("-", "_").replace(" ", "_")
        mapped = activity_map.get(normalized) or activity_map.get(item)
        if not mapped or mapped in seen_activity:
            continue
        seen_activity.add(mapped)
        activity_items.append(mapped)

    try:
        people_count = max(0, int(people_count))
    except (TypeError, ValueError):
        people_count = len(visible_people)

    if people_count <= 0 and not scene and not visible_people and not major_objects:
        return ""

    scene_lower = scene.lower()
    if scene_lower in ("indoor", "outdoor"):
        scene = f"{scene_lower} setting"
        scene_lower = scene

    def _with_article(text: str) -> str:
        cleaned = str(text or "").strip().lower()
        if not cleaned:
            return ""
        if cleaned.startswith(("a ", "an ", "the ")):
            return cleaned
        article = "an" if cleaned[0] in "aeiou" else "a"
        return f"{article} {cleaned}"

    if scene:
        first_sentence = (
            f"This is {_with_article(scene)} with "
            f"{people_count} visible {'person' if people_count == 1 else 'people'}."
        )
    else:
        first_sentence = f"There {'is' if people_count == 1 else 'are'} {people_count} visible {'person' if people_count == 1 else 'people'} in the scene."

    sentences = [first_sentence]

    if visible_people:
        people_text = "; ".join(visible_people[:3])
        sentences.append(f"Visible people include {people_text}.")

    if major_objects:
        objects_text = ", ".join(major_objects[:4])
        sentences.append(f"Major visible objects include {objects_text}.")

    if activity_items:
        sentences.append(f"Visible activity context includes {', '.join(activity_items[:4])}.")

    if ppe_visible:
        sentences.append(f"Visible PPE includes {', '.join(ppe_visible[:4])}.")
    else:
        sentences.append("No PPE is visible.")

    return " ".join(sentences).strip()


def _caption_needs_expansion(caption: str) -> bool:
    """Heuristic to trigger a richer-caption retry when output is too short/generic."""
    if not caption:
        return True
    lowered = caption.lower()
    if len(caption) < 120:
        return True
    generic_markers = (
        'person is visible',
        'outdoor setting',
        'a person is visible',
        'people are visible',
    )
    if any(marker in lowered for marker in generic_markers):
        return True
    if 'indoor setting' in lowered and len(caption) < 180:
        return True
    return False

def check_ollama_running():
    """Check if Ollama is running."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def check_model_available(model_name):
    """Check if the specified model is available in Ollama."""
    target = str(model_name or '').strip()
    if not target:
        return False

    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            for model in models:
                if not isinstance(model, dict):
                    continue
                name = str(model.get('name') or model.get('model') or '').strip()
                if not name:
                    continue
                if name == target or name.startswith(f"{target}:") or name.split(':', 1)[0] == target:
                    return True
    except Exception:
        pass
    return False

def caption_image_llava(image_path, prompt=None):
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

    strict_local_profile = (
        str(os.getenv('STRICT_PROVIDER_MODE_SPLIT', 'true')).strip().lower() in ('1', 'true', 'yes', 'on')
        and str(os.getenv('CASM_ROUTING_PROFILE', '')).strip().lower() == 'local'
    )

    # Local Gemma/Ollama reacts better to a shorter, stricter grounding prompt
    # than to the longer shared cloud prompt.
    if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER:
        structured_prompt = """Return strict JSON only with keys scene, people_count, visible_people, major_objects, ppe_visible, activity_context.

Rules:
- Use only visible evidence from the image.
- scene: short factual setting phrase such as outdoor street scene, indoor room, office area, warehouse interior, or construction area.
- people_count must count only clearly visible people.
- visible_people: short list, one person per item, each starting with "person" and mentioning position or clothing.
- major_objects: specific visible objects/structures; include large vehicles when clear.
- ppe_visible: [] when no PPE is clearly visible.
- activity_context: list using only exact tokens restricted_area, unsafe_posture, machinery, traffic_interface, work_at_height, material_stability; [] when none are clear.
- traffic_interface = road/street/sidewalk/lane/bus/truck/vehicle near people. machinery = heavy equipment/mobile plant only, such as excavator/crane/forklift/loader/industrial machine. unsafe_posture = awkward bending/leaning/kneeling/climbing/twisting/overreaching. restricted_area = cones/barriers/warning signs/tape/cordon.
- Do not guess jobs, hazards, or hidden objects.
"""
        default_prompt = """Describe only what is clearly visible in this image in one factual paragraph of 4-6 complete sentences.

Requirements:
- Start with whether the scene is indoor or outdoor and the total visible people count, including partially visible people at the image edges.
- Mention the main people, clothing, eyewear, vehicles, buildings, trees, posts, tools, or machinery only when clearly visible.
- Mention PPE only when clearly visible; if none is visible, explicitly say no PPE is visible.

Strict grounding rules:
- Do not use intro phrases like "Here is a description" or "Based on the image".
- Do not guess hidden actions, occupations, hazards, traffic context, worksite context, or unseen objects.
- If something is unclear, say it is unclear instead of inventing detail.
"""
        expansion_prompt = """Rewrite the caption with slightly richer factual detail from the image only.

Requirements:
- Keep one paragraph with 4-6 complete sentences.
- Start with indoor/outdoor and total visible people count, including edge-cropped people.
- Describe the most visible people, then major visible background objects such as vehicles or buildings.
- End by stating whether any PPE is visible.
- No intro phrase, no bullet points, no guessing.
"""
    else:
        # Build prompt for higher quality people/action/situation captions (works across model_api/gemini/ollama).
        default_prompt = """You are a workplace visual analyst. Write one factual caption from this image only.

Output requirements:
- Single paragraph, 5-7 complete factual sentences.
- Do not answer with only one sentence.
- Start with the actual scene type and total visible people count (for example indoor office/study, residential room, warehouse, roadside, construction site) based only on visible evidence.
- Describe visible body region, posture, gaze direction, clothing, eyewear, and nearby room or site features such as shelves, cabinets, windows, walls, desks, vehicles, tools, or machinery when they are clearly visible.
- Mention PPE only when clearly visible; if none is visible, say no PPE is visible.

Strict grounding rules:
- Do not begin with meta wording such as "Here is a description" or "Based on the image".
- Do not invent objects, actions, hazards, phones, tablets, vehicles, roads, machinery, tools, or construction activity.
- Do not infer a worksite or traffic context unless those objects are clearly visible.
- If visibility is unclear, say it is unclear instead of guessing.
- Natural professional English, no bullet points, no markdown, no preamble.
"""
        expansion_prompt = """The previous caption was too short or generic. Rewrite it with richer factual detail from the image only.

Requirements:
- Single paragraph, 5-7 complete sentences.
- Do not answer with only one sentence.
- State environment type and people count first.
- For each visible person: visible body region, posture, gaze direction, clothing, and context near objects.
- Mention nearby objects or hazards only if visible.
- Mention PPE only when clearly visible; if not visible, state not visible.
- No bullet points, no markdown, no meta commentary, no "Here is a description" preamble.
"""
    caption_prompt = str(prompt or '').strip() or default_prompt

    # Encode image to base64
    try:
        image_base64 = encode_image_to_base64(image_path)
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None

    # Generate caption using provider routing
    try:
        print("Generating caption...")
        if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER and not str(prompt or '').strip():
            structured_caption = _generate_vision_response(
                prompt=structured_prompt,
                image_base64=image_base64,
                temperature=0.05,
                max_tokens=300
            )
            if structured_caption and not structured_caption.startswith('ALERT_'):
                parsed_structured_caption = _try_parse_local_caption_json(structured_caption)
                rendered_structured_caption = _render_local_caption_from_json(parsed_structured_caption or {})
                if rendered_structured_caption:
                    print("Caption generation complete!")
                    return rendered_structured_caption
            elif structured_caption:
                return structured_caption

        caption = _generate_vision_response(
            prompt=caption_prompt,
            image_base64=image_base64,
            temperature=0.6,
            max_tokens=650
        )

        if caption:
            caption = _normalize_caption_text(caption)

            should_expand = _caption_needs_expansion(caption) and not caption.startswith('ALERT_')
            if strict_local_profile and 'ollama' in VISION_PROVIDER_ORDER:
                should_expand = False

            if should_expand:
                expanded = _generate_vision_response(
                    prompt=expansion_prompt,
                    image_base64=image_base64,
                    temperature=0.4,
                    max_tokens=750
                )
                expanded = _normalize_caption_text(expanded)
                if expanded and not expanded.startswith('ALERT_'):
                    caption = expanded

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

    A) CONSTRUCTION/INDUSTRIAL  is_valid=TRUE, confidence=HIGH
       - Construction sites, factories, warehouses, workshops
       - Manufacturing plants, work zones, industrial areas
       - Any place where PPE is typically required

    B) OFFICE/COMMERCIAL  is_valid=TRUE, confidence=MEDIUM
       - Office buildings, retail stores, meeting rooms
       - These environments MAY require PPE in certain areas
       - Still processed (not skipped)

    C) RESIDENTIAL/CASUAL  is_valid=FALSE, confidence=HIGH
       - Homes, living rooms, bedrooms, kitchens
       - Parks, beaches, restaurants, casual settings
       - These are SKIPPED (no report generated)

    D) OTHER/UNCLEAR  is_valid=TRUE, confidence=LOW
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
    Scaffolding, concrete, lumber, construction equipment
    Factory machinery, assembly lines, warehouses with industrial shelving
    Visible construction materials, work site barriers, heavy machinery
    People wearing multiple PPE items in an active work zone
    Choose A ONLY if you see CLEAR industrial/construction indicators

B) OFFICE/COMMERCIAL:
    Office desks, computers, cubicles, meeting rooms
    Retail displays, store shelves, checkout counters
    Professional indoor setting with business furniture

C) RESIDENTIAL/CASUAL:
    Home furniture: sofas, TV stands, beds, dining tables, home decor
    Residential kitchen, living room, bedroom, home interior
    Parks, beaches, restaurants, cafes, casual outdoor settings
    Person at home (even if wearing safety gear for testing purposes)
    Choose C if this looks like someone's HOME or casual setting

D) OTHER:
    Vehicle interior, outdoor road/street, unclear background
    Cannot determine the setting

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
            print("\nSkipping caption. Not a valid work environment")

    except ImportError as e:
        print(f"\nImportError: {e}")
        print("Please ensure you have installed required packages:")
        print("pip install requests")
        print("\nAlso ensure Ollama is installed and the model is pulled:")
        print(f"ollama pull {OLLAMA_MODEL_NAME}")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
