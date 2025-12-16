"""
Local Llama Integration - Use local Llama 3 8B model
====================================================

This module provides NLP generation using the local Llama model
instead of Ollama API, for offline operation and better control.
"""

import logging
import json
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalLlamaGenerator:
    """
    Local Llama 3 8B model wrapper for report generation.
    """
    
    def __init__(self, model_path: str):
        """
        Initialize local Llama model.
        
        Args:
            model_path: Path to local Llama model directory
        """
        self.model_path = Path(model_path)
        self.model = None
        self.tokenizer = None
        
        # GPU configuration for RTX 5070
        if torch.cuda.is_available():
            self.device = "cuda:0"
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.info(f"GPU detected: {gpu_name} ({gpu_memory:.1f} GB)")
        else:
            self.device = "cpu"
            logger.warning("No GPU detected, using CPU (will be slower)")
        
        logger.info(f"Initializing Local Llama Generator from: {self.model_path}")
        logger.info(f"Using device: {self.device}")
    
    def load_model(self):
        """Load model and tokenizer."""
        if self.model is not None:
            logger.info("Model already loaded")
            return
        
        try:
            logger.info("Loading tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_path),
                trust_remote_code=True
            )
            
            logger.info("Loading model (this may take a minute)...")
            
            # GPU configuration
            if self.device.startswith("cuda"):
                logger.info("Configuring for GPU acceleration with 4-bit quantization (NF4)...")
                
                # 4-bit quantization config for RTX 5070 (8GB VRAM)
                # This uses ~4-5GB instead of 16GB
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"  # NormalFloat4 quantization
                )
                
                self.model = AutoModelForCausalLM.from_pretrained(
                    str(self.model_path),
                    quantization_config=quantization_config,
                    device_map="auto",
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                    attn_implementation="eager"  # Use eager attention for compatibility
                )
                
                # Set to evaluation mode
                self.model.eval()
                
                # Log GPU memory usage
                allocated = torch.cuda.memory_allocated(0) / (1024**3)
                reserved = torch.cuda.memory_reserved(0) / (1024**3)
                logger.info(f"GPU Memory - Allocated: {allocated:.2f} GB, Reserved: {reserved:.2f} GB")
                logger.info(f"✅ Model fits in {allocated:.2f}GB VRAM with 4-bit quantization!")
                
            else:
                # CPU fallback
                logger.info("Loading model to CPU...")
                self.model = AutoModelForCausalLM.from_pretrained(
                    str(self.model_path),
                    torch_dtype=torch.float32,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                )
                self.model = self.model.to(self.device)
            
            logger.info(f"[OK] Model loaded successfully on {self.device}")
            
        except Exception as e:
            logger.error(f"Error loading model: {e}", exc_info=True)
            raise
    
    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 800,
        temperature: float = 0.7,
        top_p: float = 0.9
    ) -> str:
        """
        Generate text using Llama model.
        
        Args:
            prompt: Input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
        
        Returns:
            Generated text
        """
        if self.model is None:
            self.load_model()
        
        try:
            # Tokenize input
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            
            # Generate
            logger.info(f"Generating response (max {max_new_tokens} tokens)...")
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=True,
                    num_beams=1,  # Disable beam search for speed
                    pad_token_id=self.tokenizer.eos_token_id,
                    use_cache=True  # Use KV cache
                )
            
            # Decode
            generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Extract only the new generated part (remove prompt)
            response = generated_text[len(prompt):].strip()
            
            logger.info(f"[OK] Generated {len(response)} characters")
            return response
            
        except Exception as e:
            logger.error(f"Error during generation: {e}", exc_info=True)
            return ""
    
    def generate_json(
        self,
        prompt: str,
        max_new_tokens: int = 800,
        temperature: float = 0.7
    ) -> Optional[Dict[str, Any]]:
        """
        Generate JSON response.
        
        Args:
            prompt: Input prompt (should request JSON format)
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
        
        Returns:
            Parsed JSON dict or None if parsing failed
        """
        response = self.generate(prompt, max_new_tokens, temperature)
        
        try:
            # Try to find JSON in response
            # Look for {...} pattern
            start = response.find('{')
            end = response.rfind('}')
            
            if start != -1 and end != -1:
                json_str = response[start:end+1]
                return json.loads(json_str)
            else:
                logger.warning("No JSON object found in response")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response: {response[:500]}...")
            return None
    
    def unload_model(self):
        """Free up memory by unloading model."""
        if self.model is not None:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
            
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            logger.info("Model unloaded from memory")


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("LOCAL LLAMA GENERATOR TEST")
    print("=" * 70)
    
    # Test with local model
    model_path = r"C:\Users\maste\Downloads\FYP Combined\Meta-Llama-3-8B-Instruct"
    
    print(f"\nModel path: {model_path}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    
    generator = LocalLlamaGenerator(model_path)
    
    print("\n--- Testing Simple Generation ---")
    test_prompt = "Hello! Please introduce yourself in one sentence."
    print(f"Prompt: {test_prompt}")
    
    response = generator.generate(test_prompt, max_new_tokens=100)
    print(f"\nResponse:\n{response}")
    
    print("\n--- Testing JSON Generation ---")
    json_prompt = """You are a safety inspector. Analyze this workplace scene and respond in JSON format with this structure:
    {
      "summary": "Brief summary of the scene",
      "hazards": ["list", "of", "hazards"],
      "recommendations": ["list", "of", "recommendations"]
    }
    
    Scene: A construction worker is working without wearing a hard hat.
    
    Respond ONLY with the JSON object, no other text:"""
    
    print(f"Prompt: {json_prompt}")
    
    json_response = generator.generate_json(json_prompt, max_new_tokens=300)
    if json_response:
        print(f"\nJSON Response:")
        print(json.dumps(json_response, indent=2))
    else:
        print("\n[!] Failed to get valid JSON response")
    
    print("\n[OK] Test completed!")
    print("=" * 70)
