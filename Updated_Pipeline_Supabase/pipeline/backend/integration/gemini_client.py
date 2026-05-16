"""
Gemini Client  Unified AI provider for captioning and report generation
=========================================================================

Replaces Ollama (LLaVA + Llama3 + nomic-embed-text) with Google Gemini API.
Provides:
  1. Image captioning (multimodal  Gemini sees images directly)
  2. NLP report generation (structured JSON output)

No GPU, no Ollama, no local model files needed.

Usage:
    client = GeminiClient(config)
    caption = client.caption_image("path/to/image.jpg")
    report_json = client.generate_report_json(prompt)
"""

import logging
import json
import base64
import time
import re
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union, List

logger = logging.getLogger(__name__)
GEMINI_REQUIRED_BY_DEFAULT = str(os.getenv('GEMINI_REQUIRED', 'false')).strip().lower() in ('1', 'true', 'yes', 'on')
DEFAULT_GEMINI_MODEL_CANDIDATES = (
    "gemini-2.5-flash,"
    "gemini-2.5-flash-lite,"
    "gemini-flash-latest,"
    "gemini-flash-lite-latest"
)

# Try to import the Google GenAI SDK
GEMINI_AVAILABLE = False
GEMINI_ERROR = None
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
    logger.info(" Google GenAI SDK loaded successfully")
except Exception as e:
    GEMINI_ERROR = f"google-genai unavailable: {type(e).__name__}: {e}"
    _import_log = logger.error if GEMINI_REQUIRED_BY_DEFAULT else logger.warning
    _import_log(f"Google GenAI import failed: {e}")
    _import_log("Install with: pip install google-genai")


class GeminiClient:
    """
    Unified Gemini API client for image captioning and NLP report generation.

    Replaces:
      - caption_image_llava() (LLaVA/Qwen2.5-VL via Ollama)
      - _call_ollama_api() (Llama3 via Ollama)
      - _get_ollama_embeddings() (nomic-embed-text via Ollama)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Gemini client.

        Args:
            config: Configuration dictionary. Expected keys:
                - GEMINI_CONFIG: {api_key, model, temperature, max_tokens, ...}
        """
        gemini_config = config.get('GEMINI_CONFIG', {})

        def _clean_key(value: Any) -> str:
            if value is None:
                return ''
            key = str(value).strip()
            if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
                key = key[1:-1].strip()
            return key

        def _parse_key_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                raw_items = list(value)
            else:
                raw_items = str(value).split(',')
            cleaned = []
            for raw in raw_items:
                key = _clean_key(raw)
                if key and key not in cleaned:
                    cleaned.append(key)
            return cleaned

        self.api_keys = []
        self.api_key_index = 0
        key_candidates = []
        key_candidates.extend(_parse_key_list(gemini_config.get('api_keys')))
        key_candidates.extend(_parse_key_list(gemini_config.get('api_key')))
        key_candidates.extend(_parse_key_list(os.getenv('GEMINI_API_KEYS', '')))
        key_candidates.extend(_parse_key_list(os.getenv('GOOGLE_API_KEYS', '')))
        key_candidates.extend(_parse_key_list(os.getenv('GEMINI_API_KEY', '')))
        key_candidates.extend(_parse_key_list(os.getenv('GOOGLE_API_KEY', '')))
        for key in key_candidates:
            if key not in self.api_keys:
                self.api_keys.append(key)
        self.api_key = self.api_keys[0] if self.api_keys else ''

        self.model_name = gemini_config.get('model', 'gemini-2.0-flash')
        self.report_model_name = gemini_config.get('report_model', os.getenv('GEMINI_REPORT_MODEL', self.model_name))
        self.vision_model_name = gemini_config.get('vision_model', os.getenv('GEMINI_VISION_MODEL', self.model_name))
        self.model_name = self.report_model_name
        candidate_text = str(
            gemini_config.get(
                'model_candidates',
                os.getenv('GEMINI_MODEL_CANDIDATES', f"{self.model_name},{DEFAULT_GEMINI_MODEL_CANDIDATES}")
            )
        )
        parsed_candidates = [item.strip() for item in candidate_text.split(',') if item.strip()]
        deduped_candidates = []
        for candidate in [self.model_name, *parsed_candidates]:
            if candidate and candidate not in deduped_candidates:
                deduped_candidates.append(candidate)
        self.model_candidates = deduped_candidates
        self.last_model_switch_reason = None
        self.temperature = gemini_config.get('temperature', 0.4)
        self.max_tokens = gemini_config.get('max_tokens', 2000)
        self.timeout = gemini_config.get('timeout', 120)
        self.max_retries = gemini_config.get('max_retries', 3)
        self.paid_plan = bool(gemini_config.get('paid_plan', False))
        self.required = bool(gemini_config.get('required', GEMINI_REQUIRED_BY_DEFAULT))
        try:
            self.vision_thinking_budget = int(os.getenv('GEMINI_VISION_THINKING_BUDGET', '0') or 0)
        except (TypeError, ValueError):
            self.vision_thinking_budget = 0
        try:
            self.vision_max_output_tokens = int(os.getenv('GEMINI_VISION_MAX_OUTPUT_TOKENS', '900') or 900)
        except (TypeError, ValueError):
            self.vision_max_output_tokens = 900
        self.vision_max_output_tokens = max(300, min(self.vision_max_output_tokens, 2000))
        self.last_error = None
        self.last_parse_strategy = None
        self.raw_capture_enabled = str(os.getenv('GEMINI_RAW_CAPTURE_ENABLED', 'true')).strip().lower() in ('1', 'true', 'yes', 'on')
        self.raw_capture_max_chars = max(200, int(os.getenv('GEMINI_RAW_CAPTURE_MAX_CHARS', '4000')))
        capture_file = os.getenv('GEMINI_RAW_CAPTURE_FILE', 'reports/debug/gemini_raw_capture.jsonl').strip()
        self.raw_capture_file = Path(capture_file)

        prompt_budget = os.getenv('GEMINI_REPORT_PROMPT_MAX_CHARS', '').strip()
        self.report_prompt_max_chars = int(prompt_budget) if prompt_budget.isdigit() else 22000
        output_budget = os.getenv('GEMINI_REPORT_MAX_OUTPUT_TOKENS', '').strip()
        self.report_output_max_tokens = int(output_budget) if output_budget.isdigit() else 8192
        try:
            self.report_timeout_ms = int(os.getenv('GEMINI_REPORT_TIMEOUT_MS', '16000') or 16000)
        except (TypeError, ValueError):
            self.report_timeout_ms = 16000
        self.report_timeout_ms = max(5000, min(self.report_timeout_ms, 60000))
        try:
            self.report_max_retries = int(os.getenv('GEMINI_REPORT_MAX_RETRIES', '1') or 1)
        except (TypeError, ValueError):
            self.report_max_retries = 1
        self.report_max_retries = max(1, min(self.report_max_retries, max(1, self.max_retries)))
        try:
            self.report_thinking_budget = int(os.getenv('GEMINI_REPORT_THINKING_BUDGET', '0') or 0)
        except (TypeError, ValueError):
            self.report_thinking_budget = 0
        self.report_thinking_budget = max(0, min(self.report_thinking_budget, 4096))
        temp_cap = os.getenv('GEMINI_REPORT_TEMPERATURE_CAP', '').strip()
        try:
            self.report_temperature_cap = float(temp_cap) if temp_cap else 0.2
        except ValueError:
            self.report_temperature_cap = 0.2

        # Rate limiter state
        self._last_call_time = 0
        self._min_interval = gemini_config.get('min_interval', 0.35 if self.paid_plan else 4.0)

        # Initialize the client
        self.client = None
        self._initialized = False

        unavailable_log = logger.error if self.required else logger.warning

        if not GEMINI_AVAILABLE:
            unavailable_log(f"Gemini SDK not available: {GEMINI_ERROR}")
            self.last_error = GEMINI_ERROR
            return

        if not self.api_key:
            if self.required:
                logger.error("GEMINI_API_KEY not set. Add it to .env file.")
            else:
                logger.info("GEMINI_API_KEY not set; Gemini disabled and fallback providers will be used")
            self.last_error = "GEMINI_API_KEY not set"
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
            self._initialized = True
            logger.info(
                f" Gemini client initialized (report_model: {self.model_name}, vision_model: {self.vision_model_name}, keys: {len(self.api_keys)})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.last_error = str(e)

    def _switch_to_next_api_key(self, reason: str) -> bool:
        """Rotate to next configured Gemini API key when current key is throttled/exhausted."""
        if len(self.api_keys) <= 1:
            return False

        for offset in range(1, len(self.api_keys)):
            next_index = (self.api_key_index + offset) % len(self.api_keys)
            next_key = self.api_keys[next_index]
            try:
                candidate_client = genai.Client(api_key=next_key)
                self.api_key_index = next_index
                self.api_key = next_key
                self.client = candidate_client
                self._initialized = True
                logger.warning(
                    f"Switched Gemini API key to slot {next_index + 1}/{len(self.api_keys)} due to: {reason}"
                )
                return True
            except Exception as e:
                logger.warning(f"Failed to activate Gemini API key at slot {next_index + 1}: {e}")

        return False

    @property
    def is_available(self) -> bool:
        """Check if Gemini client is ready."""
        return self._initialized and self.client is not None

    def _rate_limit(self):
        """Simple rate limiter; interval is configurable and can be lower for paid plans."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            time.sleep(wait)
        self._last_call_time = time.time()

    def _try_switch_to_next_model(self, reason: str, *, target: str = 'report') -> bool:
        """Switch to next configured Gemini model candidate for report or vision generation."""
        if not self.model_candidates:
            return False

        current_model = self.vision_model_name if target == 'vision' else self.model_name
        try:
            current_index = self.model_candidates.index(current_model)
        except ValueError:
            current_index = -1

        next_index = current_index + 1
        if next_index >= len(self.model_candidates):
            return False

        previous = current_model
        next_model = self.model_candidates[next_index]
        if target == 'vision':
            self.vision_model_name = next_model
        else:
            self.model_name = next_model
        self.last_model_switch_reason = reason
        logger.warning(f"Switching Gemini {target} model from {previous} to {next_model} due to: {reason}")
        return True

    def _load_image_as_part(self, image_path: str) -> Optional[Any]:
        """
        Load an image file and return it as a Gemini-compatible part.

        Args:
            image_path: Path to the image file

        Returns:
            Image part for Gemini API, or None if failed
        """
        try:
            path = Path(image_path)
            if not path.exists():
                logger.error(f"Image not found: {image_path}")
                return None

            # Determine MIME type
            suffix = path.suffix.lower()
            mime_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.webp': 'image/webp',
                '.gif': 'image/gif',
            }
            mime_type = mime_map.get(suffix, 'image/jpeg')

            # Read image data
            image_data = path.read_bytes()

            return types.Part.from_bytes(
                data=image_data,
                mime_type=mime_type
            )

        except Exception as e:
            logger.error(f"Failed to load image {image_path}: {e}")
            return None

    def _extract_balanced_json_object(self, text: str) -> Optional[str]:
        """Extract the first balanced JSON object from text, ignoring braces inside strings."""
        start = text.find('{')
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for i in range(start, len(text)):
            ch = text[i]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

        return None

    def _extract_json_string_field(self, text: str, key: str) -> Optional[str]:
        """Extract a top-level JSON string value, tolerating a truncated closing quote."""
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"', str(text or ''))
        if not match:
            return None

        raw_chars: List[str] = []
        escaped = False
        closed = False
        for ch in str(text or '')[match.end():]:
            if escaped:
                raw_chars.append('\\' + ch)
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == '"':
                closed = True
                break
            raw_chars.append(ch)

        raw_value = ''.join(raw_chars).strip()
        if not raw_value:
            return None
        if closed:
            try:
                decoded = json.loads('"' + raw_value + '"')
                return str(decoded).strip() or None
            except Exception:
                pass
        return re.sub(r'\s+', ' ', raw_value).strip() or None

    def _extract_partial_top_level_json_fields(self, text: str) -> Optional[Dict[str, Any]]:
        """Recover useful leading fields from malformed/truncated Gemini JSON."""
        partial: Dict[str, Any] = {}
        for key in ('environment_type', 'visual_evidence', 'summary'):
            value = self._extract_json_string_field(text, key)
            if value:
                partial[key] = value
        return partial or None

    def _sanitize_debug_text(self, value: Any, max_chars: Optional[int] = None) -> str:
        """Sanitize debug text to keep logs safe and bounded."""
        limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else self.raw_capture_max_chars
        text = str(value or "").replace('\r', '')
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        if len(text) > limit:
            return f"{text[:limit]} ...[truncated {len(text) - limit} chars]"
        return text

    def _capture_nlp_debug(
        self,
        *,
        report_id: Optional[str],
        attempt: int,
        phase: str,
        prompt_text: str,
        raw_response: Optional[str] = None,
        parse_strategy: Optional[str] = None,
        success: bool = False,
        error: Optional[str] = None,
        repaired: bool = False,
    ) -> None:
        """Persist sanitized Gemini NLP attempt telemetry for postmortem analysis."""
        if not self.raw_capture_enabled:
            return

        try:
            resolved_path = self.raw_capture_file
            if not resolved_path.is_absolute():
                resolved_path = Path.cwd() / resolved_path
            resolved_path.parent.mkdir(parents=True, exist_ok=True)

            required_keys = ['environment_type', 'visual_evidence', 'persons', 'summary', 'dosh_regulations_cited']
            key_presence = {}
            payload = None
            if raw_response:
                payload = self._parse_json_from_response_text(raw_response)
            if isinstance(payload, dict):
                key_presence = {key: key in payload for key in required_keys}

            record = {
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'report_id': report_id or 'unknown',
                'model': self.model_name,
                'attempt': attempt,
                'phase': phase,
                'success': bool(success),
                'repaired': bool(repaired),
                'parse_strategy': parse_strategy,
                'prompt_chars': len(prompt_text or ''),
                'response_chars': len(raw_response or ''),
                'required_key_presence': key_presence,
                'error': self._sanitize_debug_text(error or '', 1000),
                'prompt_preview': self._sanitize_debug_text(prompt_text),
                'response_preview': self._sanitize_debug_text(raw_response or ''),
            }

            with resolved_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + '\n')
        except Exception as capture_error:
            logger.warning(f"Failed to capture Gemini debug payload: {capture_error}")

    def _tighten_prompt_for_json(self, prompt: str) -> str:
        """Reduce prompt bloat while preserving required JSON-output instructions."""
        compact = str(prompt or '').strip()
        if not compact:
            return compact

        compact = re.sub(
            r"=== HISTORICAL INCIDENTS \(For Reference\) ===.*?=== END HISTORICAL INCIDENTS ===\\s*",
            "",
            compact,
            flags=re.DOTALL,
        )

        max_chars = max(4000, self.report_prompt_max_chars)
        if len(compact) > max_chars:
            truncation_marker = "\n\n...[middle prompt content truncated; output schema preserved below]...\n\n"
            contract_markers = (
                "Return exactly one valid JSON object",
                '"environment_type"',
                '"persons"',
                '"dosh_regulations_cited"',
            )
            contract_positions = [compact.rfind(marker) for marker in contract_markers]
            contract_positions = [pos for pos in contract_positions if pos >= 0]
            contract_start = min(contract_positions) if contract_positions else -1

            if contract_start >= 0 and len(compact) - contract_start <= max_chars:
                contract = compact[contract_start:]
                head_budget = max(1000, max_chars - len(contract) - len(truncation_marker))
                compact = compact[:head_budget].rstrip() + truncation_marker + contract.lstrip()
            else:
                tail_budget = min(7000, max_chars // 2)
                head_budget = max(1000, max_chars - tail_budget - len(truncation_marker))
                compact = compact[:head_budget].rstrip() + truncation_marker + compact[-tail_budget:].lstrip()

        compact += (
            "\n\nFINAL RESPONSE RULES:\n"
            "- Return exactly one valid JSON object and no markdown fences.\n"
            "- The object must include non-empty keys: environment_type, visual_evidence, persons, summary, dosh_regulations_cited.\n"
            "- If a detail is uncertain, still include the key with a conservative evidence-based value instead of omitting it.\n"
            "- Keep each description concise while preserving factual grounding.\n"
        )
        return compact

    def _mark_schema_incomplete_payload(self, payload: Dict[str, Any], missing_keys: List[str]) -> Dict[str, Any]:
        """Annotate a usable but incomplete Gemini payload for downstream deterministic completion."""
        marked = dict(payload)
        marked['_schema_incomplete'] = True
        marked['_missing_required_report_keys'] = list(missing_keys or [])
        return marked

    def _is_usable_schema_incomplete_payload(self, payload: Optional[Dict[str, Any]]) -> bool:
        """Return True when partial model output has enough grounding to finish locally."""
        if not isinstance(payload, dict) or not payload:
            return False
        grounding_fields = (
            payload.get('environment_type'),
            payload.get('visual_evidence'),
            payload.get('summary'),
        )
        return any(str(value or '').strip() for value in grounding_fields)

    def _parse_json_from_response_text(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse model output into JSON dict using progressive recovery strategies."""
        self.last_parse_strategy = None
        # 1) Strict JSON response
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                self.last_parse_strategy = 'strict_json'
                return parsed
        except json.JSONDecodeError:
            pass

        # 2) Markdown fenced payloads
        fenced_match = re.search(r"```json\s*(.*?)\s*```", raw_text, flags=re.IGNORECASE | re.DOTALL)
        if fenced_match:
            candidate = fenced_match.group(1).strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    self.last_parse_strategy = 'fenced_json'
                    return parsed
            except json.JSONDecodeError:
                pass

        generic_fence = re.search(r"```\s*(.*?)\s*```", raw_text, flags=re.DOTALL)
        if generic_fence:
            candidate = generic_fence.group(1).strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    self.last_parse_strategy = 'generic_fence_json'
                    return parsed
            except json.JSONDecodeError:
                pass

        # 3) Balanced object extraction from mixed text
        candidate = self._extract_balanced_json_object(raw_text)
        if candidate:
            cleaned = candidate
            cleaned = re.sub(r"^\ufeff", "", cleaned)
            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
            cleaned = cleaned.strip()
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    self.last_parse_strategy = 'balanced_object_json'
                    return parsed
            except json.JSONDecodeError:
                pass

        # 4) Truncated JSON recovery. Gemini may return the start of a useful
        # object but stop mid-string before the final brace. Keep the grounded
        # top-level fields and let downstream schema completion fill the rest.
        partial = self._extract_partial_top_level_json_fields(raw_text)
        if partial:
            self.last_parse_strategy = 'partial_top_level_fields'
            return partial

        return None

    def _missing_required_report_keys(self, payload: Optional[Dict[str, Any]]) -> List[str]:
        """Return required report keys absent from a parsed Gemini NLP payload."""
        if not isinstance(payload, dict):
            return ['environment_type', 'visual_evidence', 'persons', 'summary', 'dosh_regulations_cited']

        missing = []
        if not str(payload.get('environment_type') or '').strip():
            missing.append('environment_type')
        if not str(payload.get('visual_evidence') or '').strip():
            missing.append('visual_evidence')
        if not isinstance(payload.get('persons'), list) or len(payload.get('persons') or []) == 0:
            missing.append('persons')
        if not str(payload.get('summary') or '').strip():
            missing.append('summary')
        if not isinstance(payload.get('dosh_regulations_cited'), list) or len(payload.get('dosh_regulations_cited') or []) == 0:
            missing.append('dosh_regulations_cited')
        return missing

    def _repair_json_with_gemini(self, malformed_text: str) -> Optional[Dict[str, Any]]:
        """Ask Gemini to repair malformed JSON into strict JSON object output."""
        try:
            repair_prompt = (
                "You are a JSON repair tool.\n"
                "Return exactly one valid JSON object and nothing else.\n"
                "Rules:\n"
                "- Preserve keys and values where possible.\n"
                "- If fields are truncated/missing, infer safe placeholder values.\n"
                "- Do not include markdown fences.\n\n"
                "Malformed input:\n"
                f"{malformed_text}"
            )

            repair_response = self.client.models.generate_content(
                model=self.model_name,
                contents=[repair_prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=min(self.max_tokens, 1600),
                    response_mime_type="application/json",
                )
            )

            if not repair_response or not repair_response.text:
                return None

            return self._parse_json_from_response_text(repair_response.text.strip())
        except Exception as e:
            logger.warning(f"Gemini JSON repair attempt failed: {e}")
            return None

    # =========================================================================
    # IMAGE CAPTIONING
    # =========================================================================

    def _build_vision_generation_config(self, *, temperature: float = 0.3, max_output_tokens: Optional[int] = None):
        """Build Gemini Vision config with thinking disabled by default for complete captions."""
        config_kwargs = {
            'temperature': temperature,
            'max_output_tokens': max_output_tokens or self.vision_max_output_tokens,
        }
        if self.vision_thinking_budget >= 0 and hasattr(types, 'ThinkingConfig'):
            config_kwargs['thinking_config'] = types.ThinkingConfig(
                thinking_budget=self.vision_thinking_budget
            )
        return types.GenerateContentConfig(**config_kwargs)

    def _extract_finish_reason(self, response: Any) -> str:
        try:
            return str(response.candidates[0].finish_reason or '')
        except Exception:
            return ''

    def _normalize_caption_text(self, caption: str) -> str:
        """Remove model boilerplate and normalize caption whitespace."""
        text = re.sub(r'\s+', ' ', str(caption or '')).strip()
        if not text:
            return ''

        text = re.sub(r'^(?:[-*]\s*)+', '', text).strip()
        prefixes = (
            "Here is a description of the image:",
            "Here is a description:",
            "Based on the image,",
            "In the image,",
            "In the image",
            "In this image,",
            "In this image",
        )
        for prefix in prefixes:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip(" ,:")
                break

        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        return text

    def _strip_caption_inference_sentences(self, caption: str) -> str:
        """Remove evaluative caption sentences while preserving visible facts."""
        sentences = re.split(r'(?<=[.!?])\s+', str(caption or '').strip())
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
        for sentence in sentences:
            cleaned = sentence.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if any(pattern in lowered for pattern in blocked_patterns):
                continue
            kept.append(cleaned)
        return ' '.join(kept).strip()

    def _caption_needs_expansion(self, caption: str, finish_reason: str = '') -> bool:
        """Detect captions that are too short, generic, or visibly truncated."""
        text = self._normalize_caption_text(caption)
        if not text:
            return True

        finish_upper = str(finish_reason or '').upper()
        if 'MAX_TOKENS' in finish_upper:
            return True

        lowered = text.lower()
        words = re.findall(r"[a-z0-9']+", lowered)
        sentence_count = len(re.findall(r'[.!?](?:\s|$)', text))
        if len(text) < 220 or len(words) < 35 or sentence_count < 3:
            return True

        generic_markers = (
            'person is visible',
            'people are visible',
            'unable to determine',
            'cannot determine',
            'indoor environment',
            'outdoor environment',
        )
        if any(marker in lowered for marker in generic_markers) and len(words) < 55:
            return True

        last_word_match = re.search(r"([a-z']+)[.!?]?$", lowered)
        last_word = last_word_match.group(1) if last_word_match else ''
        dangling_last_words = {
            'a', 'an', 'and', 'at', 'beside', 'by', 'for', 'from', 'in',
            'including', 'near', 'of', 'on', 'or', 'partially', 'the',
            'to', 'toward', 'under', 'with', 'wearing',
        }
        if last_word in dangling_last_words:
            return True
        if re.search(r'\b(is|are|was|were|appears|seems|looks)\s+(?:partially|likely)?\.?$', lowered):
            return True

        return False

    def _call_gemini_caption_once(
        self,
        prompt: str,
        image_part: Any,
        *,
        temperature: float = 0.3,
        max_output_tokens: Optional[int] = None,
    ) -> tuple:
        response = self.client.models.generate_content(
            model=self.vision_model_name,
            contents=[prompt, image_part],
            config=self._build_vision_generation_config(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        )
        text = self._normalize_caption_text(response.text if response and response.text else '')
        text = self._strip_caption_inference_sentences(text)
        return text, self._extract_finish_reason(response)

    def caption_image(
        self,
        image_path: str,
        custom_prompt: Optional[str] = None
    ) -> str:
        """
        Generate a safety-focused caption for an image using Gemini Vision.

        Replaces: caption_image_llava() from caption_image.py

        Args:
            image_path: Path to the image file
            custom_prompt: Optional custom prompt override

        Returns:
            Generated caption string
        """
        if not self.is_available:
            return "Image captioning not available. Gemini API is not configured"

        # Default safety-focused prompt with stronger people/action/situation structure.
        # Aligned with Local Mode's descriptive paragraph style.
        prompt = custom_prompt or (
            "You are a workplace visual analyst. Write one descriptive visual caption from this image only.\n\n"
            "Output requirements:\n"
            "- Single paragraph, 5-8 complete narrative sentences, similar to a safety observer's visual note.\n"
            "- Start in the style \"The scene depicts...\" or \"The image depicts...\" and name the actual setting plus total visible people count.\n"
            "- Describe visible body region, posture, gaze direction, clothing, eyewear, held objects, and nearby room or site features.\n"
            "- Mention PPE only when clearly visible; if none is visible, say no PPE is clearly visible.\n"
            "- Do not stop mid-sentence; every sentence must be complete.\n\n"
            "Strict grounding rules:\n"
            "- Do not begin with meta wording such as \"Here is a description\" or \"Based on the image\".\n"
            "- Do not invent objects, actions, hazards, phones, tablets, vehicles, roads, machinery, tools, or construction activity.\n"
            "- Do not infer a worksite or traffic context unless those objects are clearly visible.\n"
            "- Do not state that the scene is safe/unsafe, typical, likely, or suggestive of a condition.\n"
            "- Do not state that hazards, unusual elements, machinery, or traffic interactions are absent; only describe visible objects and PPE absence.\n"
            "- If visibility is unclear, say it is unclear instead of guessing.\n"
            "- Natural professional English, no bullet points, no markdown, no preamble."
        )

        # Load image
        image_part = self._load_image_as_part(image_path)
        if not image_part:
            return f"Error: Could not load image from {image_path}"

        # Call Gemini with retry
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()

                logger.info(f"Generating caption (attempt {attempt + 1}/{self.max_retries})...")

                caption, finish_reason = self._call_gemini_caption_once(
                    prompt,
                    image_part,
                    temperature=0.3,
                    max_output_tokens=self.vision_max_output_tokens,
                )

                if caption:
                    if self._caption_needs_expansion(caption, finish_reason):
                        logger.warning(
                            "Gemini caption was short/incomplete "
                            f"(finish_reason={finish_reason or 'unknown'}, chars={len(caption)}); retrying"
                        )
                        expansion_prompt = (
                            "The previous caption was too short or incomplete. Rewrite it with richer factual detail "
                            "from the image only.\n\n"
                            "Requirements:\n"
                            "- Single paragraph, 5-8 complete narrative sentences.\n"
                            "- Start in the style \"The scene depicts...\" or \"The image depicts...\" and state environment type and visible people count first.\n"
                            "- For each visible person: visible body region, posture, gaze direction, clothing, eyewear, held objects, and nearby objects.\n"
                            "- Mention nearby objects only if visible.\n"
                            "- Mention PPE only when clearly visible; if not visible, say no PPE is clearly visible.\n"
                            "- Do not write safety conclusions such as safe, unsafe, typical, likely, no hazards, or no interaction with traffic/machinery.\n"
                            "- Do not stop mid-sentence. No bullet points, markdown, or meta commentary.\n\n"
                            f"Previous incomplete caption: {caption}"
                        )
                        expanded, expanded_finish_reason = self._call_gemini_caption_once(
                            expansion_prompt,
                            image_part,
                            temperature=0.2,
                            max_output_tokens=max(self.vision_max_output_tokens, 1000),
                        )
                        if expanded and (
                            len(expanded) > len(caption)
                            or not self._caption_needs_expansion(expanded, expanded_finish_reason)
                        ):
                            caption = expanded
                            finish_reason = expanded_finish_reason

                    logger.info(
                        f" Caption generated ({len(caption)} chars, finish_reason={finish_reason or 'unknown'}): "
                        f"{caption[:100]}..."
                    )
                    return caption
                else:
                    logger.warning(f"Empty response from Gemini (attempt {attempt + 1})")

            except Exception as e:
                err_text = str(e)
                logger.error(f"Gemini captioning error (attempt {attempt + 1}): {err_text}")
                upper = err_text.upper()
                quota_or_exhausted = ('RESOURCE_EXHAUSTED' in upper or 'QUOTA' in upper or '429' in upper)
                service_unavailable = ('UNAVAILABLE' in upper or '503' in upper or 'HIGH DEMAND' in upper)
                if quota_or_exhausted or service_unavailable:
                    reason = (
                        'quota/resource exhaustion (caption)'
                        if quota_or_exhausted
                        else 'service temporarily unavailable (caption)'
                    )
                    if self._switch_to_next_api_key(reason):
                        continue
                    if self._try_switch_to_next_model(reason, target='vision'):
                        continue
                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)

        return "Failed to generate caption after multiple attempts"

    # =========================================================================
    # NLP REPORT GENERATION
    # =========================================================================

    def generate_report_json(
        self,
        prompt: str,
        image_path: Optional[str] = None,
        report_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate structured NLP report analysis as JSON.

        Replaces: _call_ollama_api() in report_generator.py

        Args:
            prompt: The full NLP prompt with context and instructions
            image_path: Optional image to include for multimodal analysis

        Returns:
            Parsed JSON dict, or None if failed
        """
        if not self.is_available:
            logger.error("Gemini not available for report generation")
            self.last_error = "Gemini client not available for report generation"
            self._capture_nlp_debug(
                report_id=report_id,
                attempt=0,
                phase='client-unavailable',
                prompt_text=prompt,
                success=False,
                error=self.last_error,
            )
            return None

        self.last_model_switch_reason = None

        tight_prompt = self._tighten_prompt_for_json(prompt)
        best_effort_result: Optional[Dict[str, Any]] = None
        best_effort_missing: List[str] = []

        # Build content parts
        contents = [tight_prompt]

        # Optionally include the image for multimodal analysis
        if image_path:
            image_part = self._load_image_as_part(image_path)
            if image_part:
                contents.insert(0, image_part)  # Image first, then prompt

        # Call Gemini with retry
        for attempt in range(self.report_max_retries):
            try:
                self._rate_limit()

                logger.info(
                    "Generating NLP report JSON (attempt %s/%s, timeout_ms=%s, thinking_budget=%s)...",
                    attempt + 1,
                    self.report_max_retries,
                    self.report_timeout_ms,
                    self.report_thinking_budget,
                )

                generation_config = types.GenerateContentConfig(
                    temperature=min(self.temperature, self.report_temperature_cap),
                    max_output_tokens=min(self.max_tokens, self.report_output_max_tokens),
                    response_mime_type="application/json",
                    http_options=types.HttpOptions(timeout=self.report_timeout_ms),
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=self.report_thinking_budget,
                        include_thoughts=False,
                    ),
                )

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=generation_config,
                )

                if response and response.text:
                    raw_text = response.text.strip()
                    result = self._parse_json_from_response_text(raw_text)
                    if result is not None:
                        missing_keys = self._missing_required_report_keys(result)
                        if missing_keys:
                            self.last_error = (
                                "Gemini JSON missing required report keys: "
                                + ", ".join(missing_keys)
                            )
                            logger.warning(self.last_error)
                            if self._is_usable_schema_incomplete_payload(result):
                                if (
                                    best_effort_result is None
                                    or len(missing_keys) < len(best_effort_missing)
                                ):
                                    best_effort_result = result
                                    best_effort_missing = list(missing_keys)
                            self._capture_nlp_debug(
                                report_id=report_id,
                                attempt=attempt + 1,
                                phase='primary-schema-incomplete',
                                prompt_text=tight_prompt,
                                raw_response=raw_text,
                                parse_strategy=self.last_parse_strategy,
                                success=False,
                                error=self.last_error,
                            )
                            if best_effort_result is not None:
                                logger.warning(
                                    "Proceeding with best-effort Gemini JSON for report %s; "
                                    "downstream sanitizer will fill missing keys: %s",
                                    report_id or 'unknown',
                                    ", ".join(best_effort_missing),
                                )
                                return self._mark_schema_incomplete_payload(
                                    best_effort_result,
                                    best_effort_missing,
                                )
                            break

                        logger.info(" NLP report JSON generated successfully")
                        self.last_error = None
                        self._capture_nlp_debug(
                            report_id=report_id,
                            attempt=attempt + 1,
                            phase='primary-parse',
                            prompt_text=tight_prompt,
                            raw_response=raw_text,
                            parse_strategy=self.last_parse_strategy,
                            success=True,
                        )
                        return result

                    repaired = self._repair_json_with_gemini(raw_text)
                    if repaired is not None:
                        missing_keys = self._missing_required_report_keys(repaired)
                        if missing_keys:
                            self.last_error = (
                                "Gemini repaired JSON missing required report keys: "
                                + ", ".join(missing_keys)
                            )
                            logger.warning(self.last_error)
                            if self._is_usable_schema_incomplete_payload(repaired):
                                if (
                                    best_effort_result is None
                                    or len(missing_keys) < len(best_effort_missing)
                                ):
                                    best_effort_result = repaired
                                    best_effort_missing = list(missing_keys)
                            self._capture_nlp_debug(
                                report_id=report_id,
                                attempt=attempt + 1,
                                phase='repair-schema-incomplete',
                                prompt_text=tight_prompt,
                                raw_response=raw_text,
                                parse_strategy='gemini_repair_json',
                                success=False,
                                error=self.last_error,
                                repaired=True,
                            )
                            if best_effort_result is not None:
                                logger.warning(
                                    "Proceeding with best-effort repaired Gemini JSON for report %s; "
                                    "downstream sanitizer will fill missing keys: %s",
                                    report_id or 'unknown',
                                    ", ".join(best_effort_missing),
                                )
                                return self._mark_schema_incomplete_payload(
                                    best_effort_result,
                                    best_effort_missing,
                                )
                            break

                        logger.info(" NLP report JSON repaired successfully")
                        self.last_error = None
                        self._capture_nlp_debug(
                            report_id=report_id,
                            attempt=attempt + 1,
                            phase='repair-parse',
                            prompt_text=tight_prompt,
                            raw_response=raw_text,
                            parse_strategy='gemini_repair_json',
                            success=True,
                            repaired=True,
                        )
                        return repaired

                    self.last_error = f"Could not parse JSON from Gemini response: {raw_text[:200]}..."
                    logger.error(self.last_error)
                    self._capture_nlp_debug(
                        report_id=report_id,
                        attempt=attempt + 1,
                        phase='parse-failed',
                        prompt_text=tight_prompt,
                        raw_response=raw_text,
                        parse_strategy=self.last_parse_strategy,
                        success=False,
                        error=self.last_error,
                    )
                else:
                    self.last_error = f"Empty response from Gemini (attempt {attempt + 1})"
                    logger.warning(self.last_error)
                    self._capture_nlp_debug(
                        report_id=report_id,
                        attempt=attempt + 1,
                        phase='empty-response',
                        prompt_text=tight_prompt,
                        success=False,
                        error=self.last_error,
                    )

            except json.JSONDecodeError as e:
                self.last_error = f"JSON parse error (attempt {attempt + 1}): {e}"
                logger.error(self.last_error)
                if attempt < self.max_retries - 1:
                    time.sleep(2)
            except Exception as e:
                err_text = str(e)
                self.last_error = f"Gemini report generation error (attempt {attempt + 1}): {err_text}"
                logger.error(self.last_error)
                self._capture_nlp_debug(
                    report_id=report_id,
                    attempt=attempt + 1,
                    phase='exception',
                    prompt_text=tight_prompt,
                    success=False,
                    error=self.last_error,
                )

                # Fail fast on hard quota/resource exhaustion. Service-unavailable (503/high demand)
                # is treated as transient and can rotate keys/models before normal retry backoff.
                upper = err_text.upper()
                quota_or_exhausted = ('RESOURCE_EXHAUSTED' in upper or 'QUOTA' in upper or '429' in upper)
                service_unavailable = ('UNAVAILABLE' in upper or '503' in upper or 'HIGH DEMAND' in upper)
                model_not_found = (
                    'NOT_FOUND' in upper
                    or '404' in upper
                    or 'NOT SUPPORTED FOR GENERATECONTENT' in upper
                )
                if quota_or_exhausted or service_unavailable or model_not_found:
                    if quota_or_exhausted:
                        reason = 'quota/resource exhaustion'
                    elif model_not_found:
                        reason = 'configured Gemini model unavailable'
                    else:
                        reason = 'service temporarily unavailable'
                    switched_key = self._switch_to_next_api_key(reason)
                    if switched_key:
                        continue
                    switched = self._try_switch_to_next_model(reason, target='report')
                    if switched:
                        continue
                    if quota_or_exhausted:
                        break

                if attempt < self.report_max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)

        logger.error("Failed to generate NLP report after all retries")
        if best_effort_result is not None:
            logger.warning(
                "Using best-effort Gemini JSON after retries for report %s; missing keys: %s",
                report_id or 'unknown',
                ", ".join(best_effort_missing),
            )
            return self._mark_schema_incomplete_payload(best_effort_result, best_effort_missing)
        if not self.last_error:
            self.last_error = "Failed to generate NLP report after all retries"
        return None

    def get_status(self) -> Dict[str, Any]:
        """Get Gemini client status."""
        return {
            'available': self.is_available,
            'sdk_installed': GEMINI_AVAILABLE,
            'api_key_set': bool(self.api_key),
            'api_key_slots': len(self.api_keys),
            'active_api_key_slot': self.api_key_index + 1 if self.api_keys else 0,
            'model': self.model_name,
            'report_model': self.model_name,
            'vision_model': self.vision_model_name,
            'model_candidates': self.model_candidates,
            'last_model_switch_reason': self.last_model_switch_reason,
            'paid_plan': self.paid_plan,
            'min_interval_seconds': self._min_interval,
            'backend': 'Google Gemini API',
            'error': GEMINI_ERROR if not GEMINI_AVAILABLE else None
        }


# =============================================================================
# REGULATION LOADER
# =============================================================================

def load_regulations(regulations_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load Malaysian safety regulations from JSON file.

    Args:
        regulations_path: Path to the regulations JSON file.
                         Defaults to pipeline/backend/data/malaysian_regulations.json

    Returns:
        Regulations dictionary
    """
    if regulations_path is None:
        regulations_path = Path(__file__).parent.parent / 'data' / 'malaysian_regulations.json'
    else:
        regulations_path = Path(regulations_path)

    try:
        with open(regulations_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f" Loaded {len(data.get('regulations', {}))} regulation entries from {regulations_path.name}")
        return data
    except FileNotFoundError:
        logger.error(f"Regulations file not found: {regulations_path}")
        return {}
    except Exception as e:
        logger.error(f"Error loading regulations: {e}")
        return {}


def build_regulation_context(regulations_data: Dict[str, Any], detected_violations: list = None, environment_type: str = None) -> str:
    """
    Build regulation context text for injection into the NLP prompt.

    Instead of RAG/ChromaDB vector search, this feeds the actual regulation text
    directly into the prompt (leveraging Gemini's large context window).

    Args:
        regulations_data: Full regulations dict from load_regulations()
        detected_violations: List of violation class names (e.g., ['NO-Hardhat', 'NO-Safety Vest'])
        environment_type: Detected environment type (e.g., 'Construction Site')

    Returns:
        Formatted regulation context string for prompt injection
    """
    if not regulations_data:
        return ""

    sections = []
    sections.append("=== MALAYSIAN PPE SAFETY REGULATIONS (Authoritative Legal Source) ===\n")

    # Add acronym definitions
    acronyms = regulations_data.get('acronyms', {})
    if acronyms:
        sections.append("REGULATION ACRONYMS:")
        for abbrev, full_name in acronyms.items():
            sections.append(f"  {abbrev} = {full_name}")
        sections.append("")

    # Add relevant PPE regulations
    regs = regulations_data.get('regulations', {})

    # If we know the violations, only include relevant regulations
    relevant_keys = set()
    if detected_violations:
        violation_map = {
            'NO-Hardhat': 'hardhat',
            'NO-Safety Vest': 'safety_vest',
            'NO-Mask': 'mask',
            'NO-Gloves': 'gloves',
            'NO-Safety Shoes': 'footwear',
        }
        for v in detected_violations:
            key = violation_map.get(v)
            if key:
                relevant_keys.add(key)
        # Always include harness for height work
        if environment_type and 'height' in environment_type.lower():
            relevant_keys.add('harness')
    else:
        # Include all if we don't know the violations
        relevant_keys = set(regs.keys())

    if relevant_keys:
        sections.append("APPLICABLE PPE REGULATIONS:")
        for key in relevant_keys:
            reg = regs.get(key, {})
            if reg:
                sections.append(f"\n[{reg.get('ppe_item', key.upper())}]")
                sections.append(f"  Regulation: {reg.get('regulation_ref', 'N/A')}")
                sections.append(f"  Legal Citation: {reg.get('legal_citation', 'N/A')}")
                sections.append(f"  Technical Standard: {reg.get('technical_standard', 'N/A')}")
                sections.append(f"  Requirement: {reg.get('requirement', 'N/A')}")
                sections.append(f"  Hazard: {reg.get('hazard', 'N/A')}")
                sections.append(f"  Risk: {reg.get('risk', 'N/A')}")
                sections.append(f"  Corrective Action: {reg.get('corrective_action', 'N/A')}")
                sections.append(f"  Penalty: {reg.get('penalty', 'N/A')}")

    # Add environment-specific rules
    env_rules = regulations_data.get('environment_rules', {})
    if environment_type and environment_type in env_rules:
        rule = env_rules[environment_type]
        sections.append(f"\nENVIRONMENT-SPECIFIC RULES ({environment_type}):")
        sections.append(f"  Primary Regulation: {rule.get('primary_regulation', 'N/A')}")
        for req in rule.get('requirements', []):
            sections.append(f"   {req}")
        sections.append(f"  Penalty: {rule.get('penalty', 'N/A')}")

    sections.append("\n=== END REGULATIONS ===\n")
    sections.append("IMPORTANT: You MUST cite the specific regulation references above in your report. "
                    "Do NOT make up regulation numbers. Use only the citations provided.\n")

    return "\n".join(sections)


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import os
    from dotenv import load_dotenv

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    load_dotenv()

    print("=" * 70)
    print("GEMINI CLIENT TEST")
    print("=" * 70)

    config = {
        'GEMINI_CONFIG': {
            'api_key': os.getenv('GEMINI_API_KEY', ''),
            'model': 'gemini-2.0-flash',
            'temperature': 0.4,
        }
    }

    client = GeminiClient(config)
    status = client.get_status()

    print(f"\nStatus:")
    for key, value in status.items():
        print(f"  {key}: {value}")

    # Test regulation loading
    print("\n--- Testing Regulation Loader ---")
    regs = load_regulations()
    if regs:
        print(f"Loaded {len(regs.get('regulations', {}))} regulations")
        context = build_regulation_context(
            regs,
            detected_violations=['NO-Hardhat', 'NO-Safety Vest'],
            environment_type='Construction Site'
        )
        print(f"Regulation context ({len(context)} chars):")
        print(context[:500])

    print("\n" + "=" * 70)
