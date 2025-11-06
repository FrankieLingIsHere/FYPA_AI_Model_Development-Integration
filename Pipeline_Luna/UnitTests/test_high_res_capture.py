"""
Test High-Resolution Image Capture
==================================

This script verifies that the system now captures high-resolution images.

Usage:
    python test_high_res_capture.py
"""

import cv2
from pathlib import Path

print("=" * 60)
print("Testing High-Resolution Image Capture")
print("=" * 60)
print()

# Check violations directory
violations_dir = Path('pipeline/violations')

if not violations_dir.exists():
    print("[!] No violations directory found")
    print("    Run the live demo first to generate violations")
    exit(1)

# Get most recent violation
violation_dirs = sorted(violations_dir.iterdir(), reverse=True)
violation_dirs = [d for d in violation_dirs if d.is_dir()]

if not violation_dirs:
    print("[!] No violations found")
    print("    Run the live demo first to generate violations")
    exit(1)

latest_violation = violation_dirs[0]
print(f"Latest violation: {latest_violation.name}")
print()

# Check both images
for image_name in ['original.jpg', 'annotated.jpg']:
    image_path = latest_violation / image_name
    
    if not image_path.exists():
        print(f"[X] {image_name} not found")
        continue
    
    # Load image
    img = cv2.imread(str(image_path))
    
    if img is None:
        print(f"[X] Failed to load {image_name}")
        continue
    
    # Get dimensions
    height, width, channels = img.shape
    megapixels = (width * height) / 1_000_000
    
    # File size
    file_size_kb = image_path.stat().st_size / 1024
    
    print(f"[OK] {image_name}:")
    print(f"     Resolution: {width}x{height} ({megapixels:.1f} MP)")
    print(f"     File size: {file_size_kb:.1f} KB")
    
    # Quality check
    if width >= 1920 and height >= 1080:
        print(f"     Quality: [EXCELLENT] Full HD or higher!")
    elif width >= 1280 and height >= 720:
        print(f"     Quality: [GOOD] HD quality")
    else:
        print(f"     Quality: [LOW] Below HD")
    
    print()

print("=" * 60)
print("Summary:")
print("=" * 60)
print()
print("Expected after update: 1920x1080 (~2 MP)")
print("If you see 1280x720, run the live demo again to capture")
print("new high-resolution images.")
print()
print("The high-res images will provide better quality for:")
print("  1. AI image captioning (LLaVA)")
print("  2. Human review of violations")
print("  3. Evidence documentation")
print()
