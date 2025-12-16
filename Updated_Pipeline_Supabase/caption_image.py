"""
Image Captioning with LLaVA via Ollama

Fast image captioning using Ollama's llava model.
Generates captions in seconds instead of minutes.

Usage:
    python caption_image.py path/to/image.jpg
"""
import sys
import requests
import base64
from pathlib import Path

# --- OLLAMA CONFIGURATION ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llava:7b"  # or "llava:13b" for better quality
TIMEOUT = 120  # 2 minutes timeout
# ---------------------------

def caption_image_llava(image_path):
    """
    Generate caption using Ollama's LLaVA model.
    
    Args:
        image_path: Path to image file
    
    Returns:
        Caption string or None if failed
    """
    print(f"Using Ollama LLaVA model: {OLLAMA_MODEL}")
    
    # Load and encode image to base64
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        print(f"Image loaded: {Path(image_path).name}")
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}")
        return None
    except Exception as e:
        print(f"Error loading image: {e}")
        return None
    
    # Build prompt for construction site safety analysis
    prompt = """You are a construction site safety inspector. Describe what you observe at this construction site in a natural narrative style.

Start directly describing the worker(s) and scene. DO NOT use phrases like "In the image" or "The image shows".

Describe in order:
- Worker(s): What are they doing? Where are they positioned?
- PPE Status: Be EXPLICIT and SPECIFIC:
  * State clearly what PPE items ARE visible/worn 
  * State clearly what PPE items are NOT visible/missing
  * Check each item: hardhat, safety vest, gloves, safety boots, goggles, mask
  * DO NOT use vague terms like "casual attire" or "no visible safety gear" - list each PPE item specifically
- Work Environment: Construction area details, equipment, materials
- Safety Concerns: Any visible hazards or unsafe conditions


Treat this as a construction site even if it appears to be indoors or an office area. Write a flowing paragraph, not a numbered list."""
    
    # Call Ollama API
    try:
        print("Generating caption with Ollama...")
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': OLLAMA_MODEL,
                'prompt': prompt,
                'images': [image_base64],
                'stream': False,
                'options': {
                    'temperature': 0.6,
                    'num_predict': 250,  # Increased for complete sentences
                    'stop': ['\n\n\n']  # Stop at triple newlines to avoid mid-sentence cuts
                }
            },
            timeout=TIMEOUT
        )
        
        if not response.ok:
            print(f"Error: Ollama API returned {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        data = response.json()
        caption = data.get('response', '').strip()
        
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
            print("Error: Empty response from Ollama")
            return None
            
    except requests.exceptions.Timeout:
        print(f"Error: Request timed out after {TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to Ollama. Make sure Ollama is running.")
        print("Start Ollama with: ollama serve")
        return None
    except Exception as e:
        print(f"Error calling Ollama API: {e}")
        return None

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