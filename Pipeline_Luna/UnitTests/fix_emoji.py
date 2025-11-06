"""
Fix Emoji Characters in Logging
================================
Replaces all emoji characters with ASCII equivalents for Windows console compatibility.
"""

import re
from pathlib import Path

# Emoji replacements
REPLACEMENTS = {
    '✅': '[OK]',
    '⚠️': '[!]',
    '⏸️': '[PAUSED]',
    '▶️': '[RESUMED]',
    '→': '->',
    '❌': '[X]',
    '🚨': '[ALERT]',
    '📝': '[NOTE]',
}

def fix_file(filepath):
    """Remove emoji characters from a file."""
    print(f"Processing: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    changes = 0
    
    # Replace each emoji
    for emoji, replacement in REPLACEMENTS.items():
        if emoji in content:
            count = content.count(emoji)
            content = content.replace(emoji, replacement)
            changes += count
            print(f"  - Replaced {count}x '{emoji}' with '{replacement}'")
    
    # Write back if changed
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✓ Saved {changes} changes\n")
        return changes
    else:
        print(f"  - No changes needed\n")
        return 0

def main():
    """Fix all Python files in pipeline directory."""
    print("="*70)
    print("Fixing Emoji Characters for Windows Console Compatibility")
    print("="*70)
    print()
    
    pipeline_dir = Path(__file__).parent / 'pipeline'
    
    # Find all Python files
    py_files = list(pipeline_dir.rglob('*.py'))
    
    print(f"Found {len(py_files)} Python files in pipeline/\n")
    
    total_changes = 0
    files_changed = 0
    
    for py_file in py_files:
        changes = fix_file(py_file)
        if changes > 0:
            total_changes += changes
            files_changed += 1
    
    # Also fix run_live_demo.py
    demo_file = Path(__file__).parent / 'run_live_demo.py'
    if demo_file.exists():
        changes = fix_file(demo_file)
        if changes > 0:
            total_changes += changes
            files_changed += 1
    
    print("="*70)
    print("Complete!")
    print("="*70)
    print(f"Files changed: {files_changed}")
    print(f"Total replacements: {total_changes}")
    print("="*70)
    print()
    print("You can now run: python run_live_demo.py")
    print()

if __name__ == "__main__":
    main()
