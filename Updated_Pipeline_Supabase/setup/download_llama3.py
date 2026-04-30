"""
Download Llama 3 8B Instruct Model from HuggingFace
====================================================

This script downloads the Meta Llama 3 8B Instruct model.

REQUIREMENTS:
1. HuggingFace account with Llama 3 access
2. Login: huggingface-cli login

If you don't have access:
1. Visit: https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct
2. Click "Request Access"
3. Wait for approval (usually instant)
"""

import os
from pathlib import Path
from huggingface_hub import snapshot_download
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

MODEL_ID = "meta-llama/Meta-Llama-3-8B-Instruct"
LOCAL_DIR = Path(__file__).parent / "Meta-Llama-3-8B-Instruct"

def download_llama3():
    """Download Llama 3 8B model to local directory."""
    
    print("=" * 80)
    print("LLAMA 3 8B INSTRUCT - MODEL DOWNLOAD")
    print("=" * 80)
    print()
    
    # Check if already downloaded
    if LOCAL_DIR.exists() and len(list(LOCAL_DIR.glob("*.safetensors"))) > 0:
        print(f"⚠️  Model already exists at: {LOCAL_DIR}")
        response = input("\nRe-download? This will overwrite existing files (y/n): ")
        if response.lower() != 'y':
            print("Skipping download.")
            return
    
    # Create directory
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Download location: {LOCAL_DIR}")
    print(f"🔗 HuggingFace model: {MODEL_ID}")
    print()
    print("⚠️  IMPORTANT:")
    print("   1. You must have access to Meta Llama 3 models")
    print("   2. Login with: huggingface-cli login")
    print("   3. This will download ~15GB of data")
    print()
    
    response = input("Continue with download? (y/n): ")
    if response.lower() != 'y':
        print("Download cancelled.")
        return
    
    try:
        print("\n📥 Downloading model... This may take 15-30 minutes...")
        print("=" * 80)
        
        snapshot_download(
            repo_id=MODEL_ID,
            local_dir=str(LOCAL_DIR),
            local_dir_use_symlinks=False,
            resume_download=True
        )
        
        print()
        print("=" * 80)
        print("✅ DOWNLOAD COMPLETE!")
        print("=" * 80)
        print()
        print(f"Model saved to: {LOCAL_DIR}")
        print()
        print("Files downloaded:")
        for file in sorted(LOCAL_DIR.iterdir()):
            size_mb = file.stat().st_size / (1024 * 1024)
            print(f"  • {file.name} ({size_mb:.1f} MB)")
        
        print()
        print("Next steps:")
        print("  1. Update pipeline/config.py with model path (if different)")
        print("  2. Run: python test_gpu_optimized.py")
        print("  3. Start using: python run_live_demo.py")
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ DOWNLOAD FAILED!")
        print("=" * 80)
        print()
        print(f"Error: {e}")
        print()
        print("Common issues:")
        print("  1. Not logged in to HuggingFace:")
        print("     Run: huggingface-cli login")
        print()
        print("  2. No access to Llama 3:")
        print("     Visit: https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct")
        print("     Click 'Request Access'")
        print()
        print("  3. Network/connection issues:")
        print("     Check internet connection and try again")
        print()
        print("Alternative: Use Ollama")
        print("  1. Install from: https://ollama.ai")
        print("  2. Run: ollama pull llama3")
        print("  3. System will auto-fallback to Ollama")

if __name__ == '__main__':
    download_llama3()
