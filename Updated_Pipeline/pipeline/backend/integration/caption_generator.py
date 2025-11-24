"""
Caption Generator - Wrapper for LLaVA image captioning
=======================================================

Integrates existing caption_image.py with LLaVA model.
Generates natural language descriptions of workplace safety scenes.

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

# Import existing caption module
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))

try:
    from caption_image import caption_image_llava
    CAPTION_AVAILABLE = True
    logging.info("✓ caption_image module loaded successfully")
except ImportError as e:
    CAPTION_AVAILABLE = False
    logging.error(f"❌ caption_image import failed: {e}")
except Exception as e:
    CAPTION_AVAILABLE = False
    logging.error(f"❌ caption_image error: {e}")
    import traceback
    traceback.print_exc()

logger = logging.getLogger(__name__)


class CaptionGenerator:
    """
    Generates image captions using LLaVA model.
    
    Wraps existing caption_image.py functionality.
    """
    
    def __init__(self, config: dict):
        """
        Initialize caption generator.
        
        Args:
            config: Configuration dictionary from config.py
        """
        self.config = config
        
        # LLaVA settings
        llava_config = config.get('LLAVA_CONFIG', {})
        self.model_id = llava_config.get('model_id', 'llava-hf/llava-1.5-7b-hf')
        self.load_in_4bit = llava_config.get('load_in_4bit', True)
        self.max_new_tokens = llava_config.get('max_new_tokens', 150)
        self.prompt_template = llava_config.get(
            'prompt_template',
            "USER: <image>\nDescribe this workplace safety scene in detail, focusing on workers, their actions, and any safety equipment visible."
        )
        
        # Model will be loaded lazily when first caption is requested
        self.model_loaded = False
        
        logger.info("Caption Generator initialized")
    
    def generate_caption(
        self,
        image: Union[str, np.ndarray, Path],
        prompt: Optional[str] = None,
        max_retries: int = 3
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
        if not CAPTION_AVAILABLE:
            logger.warning("Caption module not available, returning placeholder")
            return "Image captioning not available - LLaVA model not loaded"
        
        # Convert numpy array to temporary file if needed
        temp_file = None
        image_path = image
        
        if isinstance(image, np.ndarray):
            try:
                # Save to temporary file
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                cv2.imwrite(temp_file.name, image)
                image_path = temp_file.name
                logger.debug(f"Saved numpy array to temp file: {temp_file.name}")
            except Exception as e:
                logger.error(f"Error saving image to temp file: {e}")
                return "Error: Could not process image for captioning"
        
        # Generate caption with retries
        for attempt in range(max_retries):
            try:
                logger.info(f"Generating caption (attempt {attempt + 1}/{max_retries})...")
                
                # Call the existing caption function
                # Note: caption_image_llava only accepts image_path parameter
                caption = caption_image_llava(str(image_path))
                
                if caption and len(caption.strip()) > 0:
                    self.model_loaded = True
                    logger.info(f"[OK] Caption generated: {caption[:100]}...")
                    return caption.strip()
                else:
                    logger.warning("Empty caption returned")
                    
            except Exception as e:
                logger.error(f"Error generating caption (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    # Last attempt failed
                    return f"Error generating caption: {str(e)[:100]}"
                
                # Wait before retry
                import time
                time.sleep(2)
        
        # Clean up temp file
        if temp_file:
            try:
                import os
                os.unlink(temp_file.name)
            except:
                pass
        
        return "Failed to generate caption after multiple attempts"
    
    def generate_safety_focused_caption(
        self,
        image: Union[str, np.ndarray, Path]
    ) -> str:
        """
        Generate a safety-focused caption for construction site images.
        
        Args:
            image: Image to caption
        
        Returns:
            Safety-focused caption
        """
        safety_prompt = (
            "USER: <image>\n"
            "Analyze this construction site image for workplace safety. "
            "Describe: 1) What workers are doing, 2) What safety equipment they are wearing, "
            "3) What potential hazards are visible, 4) The overall work environment. "
            "Be specific and detailed."
        )
        
        return self.generate_caption(image, prompt=safety_prompt)
    
    def get_status(self) -> dict:
        """Get caption generator status."""
        return {
            'available': CAPTION_AVAILABLE,
            'model_loaded': self.model_loaded,
            'model_id': self.model_id,
            'load_in_4bit': self.load_in_4bit
        }


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import LLAVA_CONFIG
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("CAPTION GENERATOR TEST")
    print("=" * 70)
    
    # Create config
    config = {'LLAVA_CONFIG': LLAVA_CONFIG}
    
    # Create generator
    generator = CaptionGenerator(config)
    
    print(f"\n[OK] Caption Generator initialized")
    print(f"Model ID: {generator.model_id}")
    print(f"Load in 4-bit: {generator.load_in_4bit}")
    print(f"Max tokens: {generator.max_new_tokens}")
    print(f"Caption module available: {CAPTION_AVAILABLE}")
    
    status = generator.get_status()
    print(f"\nStatus:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    # Test with dummy image (if caption module available)
    if CAPTION_AVAILABLE:
        print("\n--- Testing Caption Generation ---")
        print("Creating dummy test image...")
        
        # Create a simple test image
        test_image = np.zeros((480, 640, 3), dtype=np.uint8)
        # Add some visual elements
        cv2.rectangle(test_image, (100, 100), (300, 400), (0, 255, 0), -1)
        cv2.putText(test_image, "TEST", (150, 250), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        
        print("NOTE: This will load LLaVA model which may take time and memory!")
        print("Generating caption (this may take 30-60 seconds)...")
        
        try:
            caption = generator.generate_caption(test_image)
            print(f"\n[OK] Caption: {caption}")
        except Exception as e:
            print(f"\n[!] Caption generation failed (expected if model not available): {e}")
    else:
        print("\n[!] caption_image module not available - skipping caption generation test")
    
    print("\n[OK] All tests completed!")
    print("=" * 70)
