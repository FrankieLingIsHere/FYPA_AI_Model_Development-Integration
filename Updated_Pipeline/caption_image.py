"""
Image Captioning with LLaVA 1.5

This script loads the llava-1.5-7b-hf model in 4-bit precision
and generates a caption for a given image.

Usage:
    python caption_image.py path/to/image.jpg
"""
import sys
import torch
from PIL import Image
from transformers import LlavaForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
import os

# --- MODEL SELECTION ---
model_id = "llava-hf/llava-1.5-7b-hf"
# ------------------------

def caption_image_llava(image_path):
    
    print(f"Loading model: {model_id}")
    
    # Configure 4-bit quantization with CPU offload for limited RAM
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        llm_int8_enable_fp32_cpu_offload=True  # Allow CPU offloading when RAM is low
    )
    
    # 1. Load the model and processor
    model = LlavaForConditionalGeneration.from_pretrained(
        model_id,
        quantization_config=quantization_config,
        device_map="auto",
        low_cpu_mem_usage=True
    )
    processor = AutoProcessor.from_pretrained(model_id)
    
    # model.device will show 'cuda:0' if 4-bit loading was successful
    print(f"Model loaded onto device: {model.device}")

    # Load image
    try:
        image = Image.open(image_path).convert("RGB")
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}")
        return None

    # 2. Define the LLaVA prompt
    # The <image> token is a placeholder that the processor will handle.
    prompt = "USER: <image>\nDescribe this workplace safety scene in detail, focusing on workers and safety equipment."

    # 3. Process the image and prompt
    print("Processing image and prompt...")
    inputs = processor(
        text=prompt, 
        images=image, 
        return_tensors="pt"
    ).to(model.device, dtype=torch.float16) # Ensure inputs are also float16

    # 4. Generate the caption
    print("Generating caption (this may take 10-20 minutes on CPU)...")
    print("Please wait - model is generating tokens silently...")
    output = model.generate(
        **inputs, 
        max_new_tokens=50,  # Reduced from 150 to speed up generation
        do_sample=False  # Deterministic output, faster
    )
    print("Caption generation complete!")

    # 5. Decode the output
    # We must decode the *entire* output, including the prompt
    full_text = processor.decode(output[0], skip_special_tokens=True)
    
    # 6. Clean the output
    # The output will be "USER: <image>\nDescribe this image. ASSISTANT: <caption_text>"
    # We just want the <caption_text>
    try:
        caption = full_text.split("ASSISTANT:")[1].strip()
    except IndexError:
        print("Error: Could not parse model output.")
        print(f"Full output: {full_text}")
        # Return the full text if parsing fails
        caption = full_text
    
    return caption

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python caption_image.py path/to/image.jpg")
        sys.exit(1)
        
    image_path = sys.argv[1]

    try:
        caption = caption_image_llava(image_path)
        if caption:
            print("Caption:", caption)
            
    except ImportError as e:
        print(f"\nImportError: {e}")
        print("Please ensure you have installed all required libraries:")
        print("pip install --upgrade transformers accelerate bitsandbytes torch pillow")
    except Exception as e:
        print(f"\nAn error occurred: {e}")