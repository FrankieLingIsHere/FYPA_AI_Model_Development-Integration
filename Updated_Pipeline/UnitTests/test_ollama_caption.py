"""
Quick test of Ollama LLaVA captioning
"""
import sys
from pathlib import Path

# Test with a dummy image if no argument provided
if len(sys.argv) < 2:
    # Create a simple test image
    from PIL import Image, ImageDraw, ImageFont
    import tempfile
    
    img = Image.new('RGB', (640, 480), color='white')
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 300, 400], fill='green')
    draw.text((150, 250), "TEST", fill='black')
    
    temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
    img.save(temp_file.name)
    image_path = temp_file.name
    print(f"Using test image: {temp_file.name}")
else:
    image_path = sys.argv[1]

# Import and test caption function
from caption_image import caption_image_llava

print("=" * 60)
print("TESTING OLLAMA LLAVA CAPTIONING")
print("=" * 60)
print()

caption = caption_image_llava(image_path)

if caption:
    print()
    print("=" * 60)
    print("SUCCESS! Caption generated:")
    print("=" * 60)
    print(caption)
    print()
else:
    print()
    print("FAILED - No caption generated")
    print()
    print("Troubleshooting:")
    print("1. Make sure Ollama is running: ollama serve")
    print("2. Check if llava model is available: ollama list")
    print("3. Pull model if needed: ollama pull llava:7b")
