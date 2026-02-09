
import requests

def debug_models():
    url = "http://localhost:11434/api/tags"
    try:
        resp = requests.get(url, timeout=5)
        print(f"Status: {resp.status_code}")
        print(f"Content: {resp.text}")
        
        data = resp.json()
        models = [m.get('name') for m in data.get('models', [])]
        print(f"Parsed models: {models}")
        
        # Check logic from caption_image.py
        OLLAMA_MODELS = [
            {"name": "moondream:1.8b"},
            {"name": "llava-phi3:3.8b"},
        ]
        
        for model in OLLAMA_MODELS:
            model_name = model["name"]
            # Logic from caption_image.py:71
            if any(model_name.split(':')[0] in m for m in models):
                print(f"MATCH FOUND for {model_name}")
            else:
                print(f"NO MATCH for {model_name}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_models()
