
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from caption_image import caption_image_llava

test_image = Path("pipeline/violations/20260210_155220/original.jpg")

if not test_image.exists():
    print(f"Error: {test_image} not found!")
    sys.exit(1)

print("Before caption call")
try:
    caption = caption_image_llava(str(test_image))
    print(f"After caption call. Caption len: {len(caption) if caption else 'None'}")
    print(f"Caption type: {type(caption)}")
    print(f"Caption content: '{caption}'")
except Exception as e:
    print(f"CRASH: {e}")
print("End of script")
