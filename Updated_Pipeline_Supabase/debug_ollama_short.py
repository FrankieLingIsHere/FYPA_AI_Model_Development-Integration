
import requests
resp = requests.get("http://localhost:11434/api/tags")
models = [m.get('name') for m in resp.json().get('models', [])]
print(f"Models: {models}")
