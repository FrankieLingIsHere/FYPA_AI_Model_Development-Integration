"""
Caption Generator - Wrapper for image captioning
=======================================================

Uses Gemini API (primary) or LLaVA/Qwen2.5-VL via llama.cpp (fallback)
for generating natural language descriptions of workplace safety scenes.

Usage:
    generator = CaptionGenerator(config)
    caption = generator.generate_caption(image)
"""

import logging
import numpy as np
import cv2
from typing import Union, Optional
from pathlib import Path
import sys
import tempfile

logger = logging.getLogger(__name__)

# =========================================================================
# GEMINI BACKEND (Primary)
# =========================================================================

GEMINI_CAPTION_AVAILABLE = False
gemini_client_instance = None

try:
    from pipeline.backend.integration.gemini_client import GeminiClient
    GEMINI_CAPTION_AVAILABLE = True
    logger.info("✓ Gemini caption backend available")
except ImportError as e:
    logger.info(f"Gemini backend not available: {e}")

# =========================================================================
# LEGACY BACKEND (Fallback — Qwen2.5-VL via llama.cpp)
# =========================================================================

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))

CAPTION_ERROR = None
LEGACY_CAPTION_AVAILABLE = False
try:
    from caption_image import caption_image_llava
    LEGACY_CAPTION_AVAILABLE = True
    logging.info("✓ Legacy caption_image module loaded (Qwen2.5-VL-3B)")
except ImportError as e:
    CAPTION_ERROR = f"Import error: {str(e)}"
    logging.debug(f"Legacy caption_image not available: {e}")
except Exception as e:
    CAPTION_ERROR = f"Error: {str(e)}"
    logging.debug(f"Legacy caption_image error: {e}")


class CaptionGenerator:
    """
    Generates image captions using Gemini API (primary) or Qwen2.5-VL (fallback).
    """
    
    def __init__(self, config: dict):
        """
        Initialize caption generator.
        
        Args:
            config: Configuration dictionary from config.py
        """
        self.config = config
        self.model_loaded = False
        self._gemini_client = None
        
        # Determine backend
        gemini_config = config.get('GEMINI_CONFIG', {})
        use_gemini = gemini_config.get('enabled', True) and GEMINI_CAPTION_AVAILABLE
        
        if use_gemini:
            try:
                self._gemini_client = GeminiClient(config)
                if self._gemini_client.is_available:
                    self.backend = 'gemini'
                    self.model_loaded = True
                    logger.info("✓ Caption Generator initialized (Gemini API backend)")
                else:
                    logger.warning("Gemini client not available, trying legacy backend")
                    self._gemini_client = None
                    self.backend = 'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'
            except Exception as e:
                logger.error(f"Failed to initialize Gemini for captioning: {e}")
                self._gemini_client = None
                self.backend = 'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'
        else:
            self.backend = 'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'
        
        if self.backend == 'legacy':
            logger.info("Caption Generator initialized (Legacy Qwen2.5-VL backend)")
        elif self.backend == 'none':
            logger.warning("⚠️ No caption backend available (Gemini API key not set + legacy model not found)")
    
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
        temp_file = None
        image_path = image
        
        if isinstance(image, np.ndarray):
            try:
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                cv2.imwrite(temp_file.name, image)
                image_path = temp_file.name
                logger.debug(f"Saved numpy array to temp file: {temp_file.name}")
            except Exception as e:
                logger.error(f"Error saving image to temp file: {e}")
                return "Error: Could not process image for captioning"
        
        image_path = str(image_path)
        
        try:
            # Try Gemini first
            if self._gemini_client and self._gemini_client.is_available:
                caption = self._gemini_client.caption_image(image_path, custom_prompt=prompt)
                if caption and not caption.startswith("Error") and not caption.startswith("Failed"):
                    self.model_loaded = True
                    return caption
                else:
                    logger.warning(f"Gemini captioning failed, trying legacy: {caption}")
            
            # Fallback to legacy (Qwen2.5-VL via llama.cpp)
            if LEGACY_CAPTION_AVAILABLE:
                logger.info("Using legacy caption backend (Qwen2.5-VL)...")
                for attempt in range(max_retries):
                    try:
                        caption = caption_image_llava(image_path)
                        if caption and len(caption.strip()) > 0:
                            self.model_loaded = True
                            logger.info(f"✓ Legacy caption generated: {caption[:100]}...")
                            return caption.strip()
                    except Exception as e:
                        logger.error(f"Legacy captioning error (attempt {attempt + 1}): {e}")
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(2)
            
            # All backends failed
            error_msg = "Image captioning not available"
            if not self._gemini_client or not self._gemini_client.is_available:
                error_msg += " — Gemini API key not configured"
            if not LEGACY_CAPTION_AVAILABLE:
                error_msg += " — Legacy model not found"
            if CAPTION_ERROR:
                error_msg += f": {CAPTION_ERROR}"
            return error_msg
            
        finally:
            # Clean up temp file
            if temp_file:
                try:
                    import os
                    os.unlink(temp_file.name)
                except:
                    pass
    
    def generate_safety_focused_caption(
        self,
        image: Union[str, np.ndarray, Path]
    ) -> str:
        """
        Generate a safety-focused caption for construction site images.
        """
        safety_prompt = (
            "You are a workplace safety inspector. Analyze this image and describe:\n"
            "1) What workers are doing\n"
            "2) What safety equipment they are wearing\n"
            "3) What safety equipment is missing or not worn\n"
            "4) Any visible hazards in the work environment\n"
            "Be specific and factual. Output a single paragraph, 3-5 sentences."
        )
        
        return self.generate_caption(image, prompt=safety_prompt)
    
    def get_status(self) -> dict:
        """Get caption generator status."""
        status = {
            'available': self.backend != 'none',
            'model_loaded': self.model_loaded,
            'backend': self.backend,
        }
        
        if self.backend == 'gemini':
            status['model'] = 'Gemini 2.0 Flash (Google AI)'
        elif self.backend == 'legacy':
            status['model'] = 'Qwen2.5-VL-3B-Instruct (Q4_K_M GGUF)'
        else:
            status['model'] = 'None'
            
        if CAPTION_ERROR:
            status['legacy_error'] = CAPTION_ERROR
            
        if self._gemini_client:
            status['gemini_status'] = self._gemini_client.get_status()
            
        return status


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
    print("CAPTION GENERATOR TEST")
    print("=" * 70)
    
    # Import config
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import LLAVA_CONFIG, GEMINI_CONFIG
    
    config = {
        'LLAVA_CONFIG': LLAVA_CONFIG,
        'GEMINI_CONFIG': GEMINI_CONFIG,
    }
    
    generator = CaptionGenerator(config)
    
    print(f"\nBackend: {generator.backend}")
    status = generator.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 70)
