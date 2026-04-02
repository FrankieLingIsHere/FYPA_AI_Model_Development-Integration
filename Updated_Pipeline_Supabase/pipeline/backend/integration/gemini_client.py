"""
Gemini Client — Unified AI provider for captioning and report generation
=========================================================================

Replaces Ollama (LLaVA + Llama3 + nomic-embed-text) with Google Gemini API.
Provides:
  1. Image captioning (multimodal — Gemini sees images directly)
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
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)

# Try to import the Google GenAI SDK
GEMINI_AVAILABLE = False
GEMINI_ERROR = None
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
    logger.info("✓ Google GenAI SDK loaded successfully")
except ImportError as e:
    GEMINI_ERROR = f"google-genai not installed: {e}"
    logger.error(f"❌ Google GenAI import failed: {e}")
    logger.error("   Install with: pip install google-genai")


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

        self.api_key = _clean_key(gemini_config.get('api_key')) or _clean_key(os.getenv('GEMINI_API_KEY', ''))
        self.model_name = gemini_config.get('model', 'gemini-2.0-flash')
        candidate_text = str(
            gemini_config.get(
                'model_candidates',
                os.getenv('GEMINI_MODEL_CANDIDATES', f"{self.model_name},gemini-2.5-flash-lite,gemini-1.5-flash")
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
        self.last_error = None
        
        # Rate limiter state
        self._last_call_time = 0
        self._min_interval = gemini_config.get('min_interval', 4.0)  # seconds between calls (15 RPM free tier)
        
        # Initialize the client
        self.client = None
        self._initialized = False
        
        if not GEMINI_AVAILABLE:
            logger.error(f"Gemini SDK not available: {GEMINI_ERROR}")
            self.last_error = GEMINI_ERROR
            return
            
        if not self.api_key:
            logger.error("GEMINI_API_KEY not set. Add it to .env file.")
            self.last_error = "GEMINI_API_KEY not set"
            return
        
        try:
            self.client = genai.Client(api_key=self.api_key)
            self._initialized = True
            logger.info(f"✓ Gemini client initialized (model: {self.model_name})")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
            self.last_error = str(e)
    
    @property
    def is_available(self) -> bool:
        """Check if Gemini client is ready."""
        return self._initialized and self.client is not None
    
    def _rate_limit(self):
        """Simple rate limiter to stay within free tier (15 RPM)."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            time.sleep(wait)
        self._last_call_time = time.time()

    def _try_switch_to_next_model(self, reason: str) -> bool:
        """Switch to next configured Gemini model candidate when current one is exhausted."""
        if not self.model_candidates:
            return False

        try:
            current_index = self.model_candidates.index(self.model_name)
        except ValueError:
            current_index = -1

        next_index = current_index + 1
        if next_index >= len(self.model_candidates):
            return False

        previous = self.model_name
        self.model_name = self.model_candidates[next_index]
        self.last_model_switch_reason = reason
        logger.warning(f"Switching Gemini model from {previous} to {self.model_name} due to: {reason}")
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

    def _parse_json_from_response_text(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse model output into JSON dict using progressive recovery strategies."""
        # 1) Strict JSON response
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
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
                    return parsed
            except json.JSONDecodeError:
                pass

        generic_fence = re.search(r"```\s*(.*?)\s*```", raw_text, flags=re.DOTALL)
        if generic_fence:
            candidate = generic_fence.group(1).strip()
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
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
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

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
            return "Image captioning not available — Gemini API not configured"
        
        # Default safety-focused prompt with stronger people/action/situation structure.
        prompt = custom_prompt or (
            "You are a workplace visual analyst. Write a factual caption from this image only.\n\n"
            "Output rules (single paragraph, 6-9 sentences):\n"
            "1. Start with total visible people count and scene type.\n"
            "2. For each visible person, describe their action, visible body region, and immediate situation/context.\n"
            "3. Describe nearby safety-relevant context (machines, vehicles, stacked materials, barriers, wet/slippery surfaces, tools) only if visible.\n"
            "4. Mention PPE only when clearly visible and certain.\n"
            "5. If PPE region is not visible, explicitly state it is not visible.\n"
            "6. End with concise safety context grounded in visible facts.\n\n"
            "Strict grounding:\n"
            "- Do not invent hazards, tools, or PPE.\n"
            "- Do not assume construction/worksite unless visual evidence supports it.\n"
            "- Hardhat must be a rigid safety helmet (hair/cap/hood is not hardhat).\n"
            "- Safety vest must be fluorescent and reflective.\n\n"
            "Style: professional natural English, no markdown, no bullet points, avoid 'In the image'."
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
                
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[prompt, image_part],
                    config=types.GenerateContentConfig(
                        temperature=0.3,  # Lower temp for factual description
                        max_output_tokens=700,
                    )
                )
                
                if response and response.text:
                    caption = response.text.strip()
                    logger.info(f"✓ Caption generated ({len(caption)} chars): {caption[:100]}...")
                    return caption
                else:
                    logger.warning(f"Empty response from Gemini (attempt {attempt + 1})")
                    
            except Exception as e:
                logger.error(f"Gemini captioning error (attempt {attempt + 1}): {e}")
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
        image_path: Optional[str] = None
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
            return None

        self.last_model_switch_reason = None
        
        # Build content parts
        contents = [prompt]
        
        # Optionally include the image for multimodal analysis
        if image_path:
            image_part = self._load_image_as_part(image_path)
            if image_part:
                contents.insert(0, image_part)  # Image first, then prompt
        
        # Call Gemini with retry
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                logger.info(f"Generating NLP report JSON (attempt {attempt + 1}/{self.max_retries})...")
                
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens,
                        response_mime_type="application/json",
                    )
                )
                
                if response and response.text:
                    raw_text = response.text.strip()
                    result = self._parse_json_from_response_text(raw_text)
                    if result is not None:
                        logger.info("✓ NLP report JSON generated successfully")
                        self.last_error = None
                        return result

                    repaired = self._repair_json_with_gemini(raw_text)
                    if repaired is not None:
                        logger.info("✓ NLP report JSON repaired successfully")
                        self.last_error = None
                        return repaired

                    self.last_error = f"Could not parse JSON from Gemini response: {raw_text[:200]}..."
                    logger.error(self.last_error)
                else:
                            self.last_error = f"Empty response from Gemini (attempt {attempt + 1})"
                            logger.warning(self.last_error)
                    
            except json.JSONDecodeError as e:
                self.last_error = f"JSON parse error (attempt {attempt + 1}): {e}"
                logger.error(self.last_error)
                if attempt < self.max_retries - 1:
                    time.sleep(2)
            except Exception as e:
                err_text = str(e)
                self.last_error = f"Gemini report generation error (attempt {attempt + 1}): {err_text}"
                logger.error(self.last_error)

                # Fail fast on quota/resource exhaustion to avoid long stuck generation windows.
                upper = err_text.upper()
                if 'RESOURCE_EXHAUSTED' in upper or 'QUOTA' in upper or '429' in upper:
                    switched = self._try_switch_to_next_model('quota/resource exhaustion')
                    if switched:
                        continue
                    break

                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)
        
        logger.error("Failed to generate NLP report after all retries")
        if not self.last_error:
            self.last_error = "Failed to generate NLP report after all retries"
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get Gemini client status."""
        return {
            'available': self.is_available,
            'sdk_installed': GEMINI_AVAILABLE,
            'api_key_set': bool(self.api_key),
            'model': self.model_name,
            'model_candidates': self.model_candidates,
            'last_model_switch_reason': self.last_model_switch_reason,
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
        logger.info(f"✓ Loaded {len(data.get('regulations', {}))} regulation entries from {regulations_path.name}")
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
            sections.append(f"  • {req}")
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
