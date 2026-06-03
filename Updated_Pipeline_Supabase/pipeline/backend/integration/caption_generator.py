"""
Caption Generator - Wrapper for image captioning
=======================================================

Uses Gemini API (primary) or LLaVA/Qwen2.5-VL via llama.cpp (fallback)
for generating natural language descriptions of workplace safety scenes.

Usage:
    generator = CaptionGenerator(config)
    caption = generator.generate_caption(image)
"""
# Readability: Integration module: isolate external model/provider calls behind stable helpers.

import logging
import numpy as np
import cv2
import os
from typing import Union, Optional
from pathlib import Path
import sys
import tempfile

# Prepare logger for the next step.
logger = logging.getLogger(__name__)

# =========================================================================
# GEMINI BACKEND (Primary)
# =========================================================================

GEMINI_CAPTION_AVAILABLE = False
gemini_client_instance = None

# Protect this step so expected failures can fall back cleanly.
try:
    from pipeline.backend.integration.gemini_client import GeminiClient
    # Prepare gemini caption available for the next step.
    GEMINI_CAPTION_AVAILABLE = True
    logger.info("Gemini caption backend available")
except ImportError as e:
    logger.info(f"Gemini backend not available: {e}")

# =========================================================================
# LEGACY BACKEND (Fallback  Qwen2.5-VL via llama.cpp)
# =========================================================================

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))

CAPTION_ERROR = None
LEGACY_CAPTION_AVAILABLE = False
try:
    from caption_image import caption_image_llava
    # Prepare legacy caption available for the next step.
    LEGACY_CAPTION_AVAILABLE = True
    logging.info("Legacy caption_image module loaded (Qwen2.5-VL-3B)")
except ImportError as e:
    CAPTION_ERROR = f"Import error: {str(e)}"
    logging.debug(f"Legacy caption_image not available: {e}")
except Exception as e:
    CAPTION_ERROR = f"Error: {str(e)}"
    logging.debug(f"Legacy caption_image error: {e}")


# Section: group caption generator state and behaviour in one readable unit.
class CaptionGenerator:
    """
    Generates image captions using Gemini API (primary) or Qwen2.5-VL (fallback).
    """

    # Section: run the init workflow with clear inputs and outputs.
    def __init__(self, config: dict):
        """
        Initialize caption generator.

        Args:
            config: Configuration dictionary from config.py
        """
        # Prepare config for the next step.
        self.config = config
        self.model_loaded = False
        self._gemini_client = None

        # Determine backend. Strict local profile must keep captions on the
        # local Ollama/Gemma path even when a Gemini key exists.
        gemini_config = config.get('GEMINI_CONFIG', {})
        strict_local_profile = (
            str(os.getenv('STRICT_PROVIDER_MODE_SPLIT', 'true')).strip().lower() in ('1', 'true', 'yes', 'on')
            and str(os.getenv('CASM_ROUTING_PROFILE', '')).strip().lower() == 'local'
        )
        # Prepare use gemini for the next step.
        use_gemini = (
            gemini_config.get('enabled', True)
            and GEMINI_CAPTION_AVAILABLE
            and not strict_local_profile
        )

        if use_gemini:
            # Protect this step so expected failures can fall back cleanly.
            try:
                # Prepare gemini client for the next step.
                self._gemini_client = GeminiClient(config)
                if self._gemini_client.is_available:
                    # Prepare backend for the next step.
                    self.backend = 'gemini'
                    self.model_loaded = True
                    logger.info("Caption Generator initialized (Gemini API backend)")
                else:
                    logger.warning("Gemini client not available, trying legacy backend")
                    self._gemini_client = None
                    self.backend = 'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'
            except Exception as e:
                # Trigger the side effect required for this stage.
                logger.error(f"Failed to initialize Gemini for captioning: {e}")
                self._gemini_client = None
                self.backend = 'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'
        else:
            # Prepare backend for the next step.
            self.backend = 'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'

        # Choose the correct branch before the workflow continues.
        if self.backend == 'legacy':
            logger.info("Caption Generator initialized (Legacy Qwen2.5-VL backend)")
        elif self.backend == 'none':
            logger.warning("No caption backend available. Gemini API key is not set and the legacy model was not found")

    # Section: run the ensure gemini client workflow with clear inputs and outputs.
    def _ensure_gemini_client(self) -> bool:
        """Lazily restore Gemini after runtime switches from Local Mode to Cloud Mode."""
        if self._gemini_client is not None and getattr(self._gemini_client, 'is_available', False):
            # Return the prepared result to the caller.
            return True
        # Choose the correct branch before the workflow continues.
        if not GEMINI_CAPTION_AVAILABLE:
            return False

        gemini_config = self.config.get('GEMINI_CONFIG', {}) if isinstance(self.config, dict) else {}
        env_gemini_enabled = str(os.getenv('GEMINI_ENABLED', '')).strip().lower() in ('1', 'true', 'yes', 'on')
        if not gemini_config.get('enabled', True) and not env_gemini_enabled:
            return False
        if isinstance(self.config, dict):
            # Trigger the side effect required for this stage.
            self.config.setdefault('GEMINI_CONFIG', {})
            self.config['GEMINI_CONFIG']['enabled'] = True

        # Protect this step so expected failures can fall back cleanly.
        try:
            self._gemini_client = GeminiClient(self.config)
            if getattr(self._gemini_client, 'is_available', False):
                # Prepare backend for the next step.
                self.backend = 'gemini'
                self.model_loaded = True
                logger.info("Gemini caption client restored for Cloud Mode")
                return True
        except Exception as e:
            # Trigger the side effect required for this stage.
            logger.warning(f"Gemini caption client restore failed: {e}")

        # Prepare gemini client for the next step.
        self._gemini_client = None
        return False

    # Section: run the generate caption workflow with clear inputs and outputs.
    def generate_caption(
        self,
        image: Union[str, np.ndarray, Path],
        prompt: Optional[str] = None,
        max_retries: int = 1
    ) -> str:
        """
        Generate a caption for an image.

        Args:
            image: Image path, numpy array, or Path object
            prompt: Optional custom prompt override
            max_retries: Number of retry attempts

        Returns:
            Generated caption string
        """
        # Convert numpy array to temporary file if needed
        # Prepare temp file for the next step.
        temp_file = None
        image_path = image

        if isinstance(image, np.ndarray):
            # Protect this step so expected failures can fall back cleanly.
            try:
                # Prepare temp file for the next step.
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                cv2.imwrite(temp_file.name, image)
                image_path = temp_file.name
                logger.debug(f"Saved numpy array to temp file: {temp_file.name}")
            except Exception as e:
                logger.error(f"Error saving image to temp file: {e}")
                return "Error: Could not process image for captioning"

        # Prepare image path for the next step.
        image_path = str(image_path)

        try:
            # Prepare strict local profile for the next step.
            strict_local_profile = (
                str(os.getenv('STRICT_PROVIDER_MODE_SPLIT', 'true')).strip().lower() in ('1', 'true', 'yes', 'on')
                and str(os.getenv('CASM_ROUTING_PROFILE', '')).strip().lower() == 'local'
            )

            # Try Gemini first only outside strict local profile.
            if not strict_local_profile and self._ensure_gemini_client():
                caption = self._gemini_client.caption_image(image_path, custom_prompt=prompt)
                if caption and not caption.startswith("Error") and not caption.startswith("Failed"):
                    # Prepare model loaded for the next step.
                    self.model_loaded = True
                    self.backend = 'gemini'
                    return caption
                else:
                    logger.warning(f"Gemini captioning failed, trying legacy: {caption}")

            # Fallback to legacy (Qwen2.5-VL via llama.cpp)
            # Choose the correct branch before the workflow continues.
            if (self.backend == 'legacy' or strict_local_profile) and LEGACY_CAPTION_AVAILABLE:
                logger.info("Using legacy caption backend (Qwen2.5-VL)...")
                for attempt in range(max_retries):
                    # Protect this step so expected failures can fall back cleanly.
                    try:
                        # Prepare caption for the next step.
                        caption = caption_image_llava(image_path, prompt=prompt)
                        if caption and len(caption.strip()) > 0:
                            # Choose the correct branch before the workflow continues.
                            if str(caption).strip().startswith('ALERT_'):
                                # Trigger the side effect required for this stage.
                                logger.warning(f"Legacy caption backend unavailable: {caption[:140]}...")
                                return caption.strip()
                            self.model_loaded = True
                            logger.info(f"Legacy caption generated: {caption[:100]}...")
                            return caption.strip()
                    except Exception as e:
                        # Trigger the side effect required for this stage.
                        logger.error(f"Legacy captioning error (attempt {attempt + 1}): {e}")
                        if attempt < max_retries - 1:
                            import time
                            # Trigger the side effect required for this stage.
                            time.sleep(2)

            # All backends failed
            # Prepare error msg for the next step.
            error_msg = "Image captioning not available"
            if not self._gemini_client or not self._gemini_client.is_available:
                error_msg += ". Gemini API key not configured"
            if not LEGACY_CAPTION_AVAILABLE:
                error_msg += ". Legacy model not found"
            if CAPTION_ERROR:
                error_msg += f": {CAPTION_ERROR}"
            return error_msg

        finally:
            # Clean up temp file
            # Choose the correct branch before the workflow continues.
            if temp_file:
                # Protect this step so expected failures can fall back cleanly.
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    # Section: run the generate safety focused caption workflow with clear inputs and outputs.
    def generate_safety_focused_caption(
        self,
        image: Union[str, np.ndarray, Path]
    ) -> str:
        """
        Generate a safety-focused caption for construction site images.
        """
        # Prepare safety prompt for the next step.
        safety_prompt = (
            "You are a workplace safety inspector. Analyze this image and describe:\n"
            "1) What workers are doing\n"
            "2) What safety equipment they are wearing\n"
            "3) What safety equipment is missing or not worn\n"
            "4) Any visible hazards in the work environment\n"
            "Be specific and factual. Output a single paragraph, 3-5 sentences."
        )

        # Return the prepared result to the caller.
        return self.generate_caption(image, prompt=safety_prompt)

    # Section: run the get status workflow with clear inputs and outputs.
    def get_status(self) -> dict:
        """Get caption generator status."""
        gemini_runtime_status = self._gemini_client.get_status() if self._gemini_client else {}
        status = {
            'available': self.backend != 'none',
            'model_loaded': self.model_loaded,
            'backend': self.backend,
        }

        # Choose the correct branch before the workflow continues.
        if self.backend == 'gemini':
            # Prepare values needed by the next step.
            status['model'] = (
                gemini_runtime_status.get('vision_model')
                or gemini_runtime_status.get('model')
                or 'Google Gemini API'
            )
        elif self.backend == 'legacy':
            status['model'] = os.getenv('OLLAMA_VISION_MODEL', os.getenv('OLLAMA_MODEL', 'gemma3:4b'))
        else:
            status['model'] = 'None'

        # Choose the correct branch before the workflow continues.
        if CAPTION_ERROR:
            # Prepare values needed by the next step.
            status['legacy_error'] = CAPTION_ERROR

        if self._gemini_client:
            status['gemini_status'] = gemini_runtime_status

        return status


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import os
    from dotenv import load_dotenv

    # Trigger the side effect required for this stage.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    load_dotenv()

    print("=" * 70)
    print("CAPTION GENERATOR TEST")
    # Trigger the side effect required for this stage.
    print("=" * 70)

    # Import config
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import LLAVA_CONFIG, GEMINI_CONFIG

    config = {
        'LLAVA_CONFIG': LLAVA_CONFIG,
        'GEMINI_CONFIG': GEMINI_CONFIG,
    }

    # Prepare generator for the next step.
    generator = CaptionGenerator(config)

    print(f"\nBackend: {generator.backend}")
    status = generator.get_status()
    for key, value in status.items():
        # Trigger the side effect required for this stage.
        print(f"  {key}: {value}")

    print("\n" + "=" * 70)
