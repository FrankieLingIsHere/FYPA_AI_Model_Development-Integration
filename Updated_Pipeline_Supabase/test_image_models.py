
import sys
import os
import requests
import json
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

OLLAMA_API_URL = "http://localhost:11434/api/generate"

def caption_image(image_path, model):
    print(f"\\n--- Testing Model: {model} ---")
    try:
        import base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        payload = {
            "model": model,
            "prompt": "Describe this image in detail. What do you see?",
            "stream": False,
            "images": [base64_image]
        }
        
        response = requests.post(OLLAMA_API_URL, json=payload)
        if response.status_code == 200:
            result = response.json().get("response", "").strip()
            print(f"Default Prompt Result: {result}")
        else:
            print(f"Error: {response.status_code} - {response.text}")
            
        # Try specific prompt if Moondream
        if 'moondream' in model:
             payload['prompt'] = (
                "Analyze this construction site image. "
                "Describe the lighting (day/night), any heavy machinery (excavators, trucks), "
                "the workers (number, actions), and their safety gear. "
                "Be factual and detailed."
            )
             response = requests.post(OLLAMA_API_URL, json=payload)
             if response.status_code == 200:
                result = response.json().get("response", "").strip()
                print(f"Specific Prompt Result: {result}")

    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    image_path = r"c:\Users\User\Documents\Degree Y3 S2\COS40006 Computing Technology Project B\FYPA_AI_Model_Development-Integration\Updated_Pipeline_Supabase\pipeline\violations\20260209_121437\original.jpg"
    
    print(f"Testing Image: {image_path}")
    if not os.path.exists(image_path):
        print("File not found!")
        sys.exit(1)
        
    caption_image(image_path, "moondream:1.8b")
    caption_image(image_path, "llava-phi3:3.8b")
