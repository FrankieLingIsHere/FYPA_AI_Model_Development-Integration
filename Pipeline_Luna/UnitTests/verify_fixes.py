"""
Quick System Verification After Fixes
======================================
Verifies all fixes were applied correctly.
"""

import sys
from pathlib import Path

print("="*70)
print("SYSTEM VERIFICATION AFTER FIXES")
print("="*70)
print()

# Add pipeline to path
sys.path.append(str(Path(__file__).parent))

from pipeline.config import YOLO_CONFIG, PPE_CLASSES, ROOT_DIR

# Check 1: Model Path
print("1. YOLO Model Configuration")
print("-" * 70)
model_path = YOLO_CONFIG['model_path']
print(f"   Configured path: {model_path}")

model_file = Path(model_path)
if model_file.exists():
    print(f"   [OK] Model file exists")
    print(f"   Size: {model_file.stat().st_size / 1024 / 1024:.1f} MB")
else:
    print(f"   [X] WARNING: Model file not found!")
print()

# Check 2: PPE Classes
print("2. PPE Classes (Custom Model)")
print("-" * 70)
print(f"   Total classes: {len(PPE_CLASSES)}")
print(f"   Classes: {', '.join(PPE_CLASSES.values())}")
print()

# Check 3: Emoji Removal
print("3. Emoji Character Check")
print("-" * 70)

files_to_check = [
    'pipeline/backend/core/yolo_stream.py',
    'pipeline/backend/core/pipeline_orchestrator.py',
    'pipeline/backend/core/report_generator.py',
    'run_live_demo.py'
]

emoji_chars = ['✅', '⚠️', '⏸️', '▶️', '→', '❌']
total_emoji_found = 0

for file_path in files_to_check:
    full_path = Path(__file__).parent / file_path
    if full_path.exists():
        content = full_path.read_text(encoding='utf-8')
        emoji_in_file = sum(content.count(emoji) for emoji in emoji_chars)
        if emoji_in_file > 0:
            print(f"   [!] {file_path}: {emoji_in_file} emoji found")
            total_emoji_found += emoji_in_file
        else:
            print(f"   [OK] {file_path}: No emoji")

if total_emoji_found == 0:
    print(f"\n   [OK] All emoji removed successfully!")
else:
    print(f"\n   [!] WARNING: {total_emoji_found} emoji characters still present")
print()

# Check 4: Caption Image Fix
print("4. Caption Image Parser")
print("-" * 70)
caption_file = Path(__file__).parent / 'caption_image.py'
if caption_file.exists():
    content = caption_file.read_text(encoding='utf-8')
    # Check if fallback is present
    if 'caption = full_text' in content:
        print("   [OK] Parse error fallback implemented")
    else:
        print("   [!] WARNING: Fallback may be missing")
else:
    print("   [!] caption_image.py not found")
print()

# Summary
print("="*70)
print("VERIFICATION SUMMARY")
print("="*70)
checks_passed = 0
checks_total = 4

if model_file.exists():
    checks_passed += 1
    print("[OK] Model path configured correctly")
else:
    print("[X] Model path issue")

if len(PPE_CLASSES) == 14:
    checks_passed += 1
    print("[OK] PPE classes configured (14 classes)")
else:
    print(f"[!] PPE classes: {len(PPE_CLASSES)} (expected 14)")

if total_emoji_found == 0:
    checks_passed += 1
    print("[OK] Emoji characters removed")
else:
    print(f"[!] Emoji still present: {total_emoji_found}")

if caption_file.exists() and 'caption = full_text' in caption_file.read_text(encoding='utf-8'):
    checks_passed += 1
    print("[OK] Caption parser fixed")
else:
    print("[!] Caption parser issue")

print()
print(f"Checks Passed: {checks_passed}/{checks_total}")
print("="*70)

if checks_passed == checks_total:
    print()
    print("[OK] All fixes verified! System ready to run.")
    print()
    print("Run: python run_live_demo.py")
    print()
else:
    print()
    print(f"[!] {checks_total - checks_passed} issue(s) need attention")
    print()
