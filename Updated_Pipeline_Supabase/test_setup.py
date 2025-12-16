"""
Setup Validation Script
========================

Tests all components of the Supabase-backed LUNA system.

Usage:
    python test_setup.py
"""

import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def test_env_variables():
    """Test that required environment variables are set."""
    import os
    
    logger.info("Testing environment variables...")
    
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_SERVICE_ROLE_KEY',
        'SUPABASE_DB_URL'
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error("Please set these in your .env file")
        return False
    
    logger.info("✓ All required environment variables are set")
    return True


def test_supabase_db():
    """Test Supabase database connection."""
    logger.info("Testing Supabase database connection...")
    
    try:
        from pipeline.backend.core.supabase_db import create_db_manager_from_env
        
        db = create_db_manager_from_env()
        
        # Try to query logs
        logs = db.get_recent_logs(limit=1)
        
        logger.info("✓ Supabase database connection successful")
        db.close()
        return True
        
    except Exception as e:
        logger.error(f"✗ Supabase database connection failed: {e}")
        return False


def test_supabase_storage():
    """Test Supabase storage connection."""
    logger.info("Testing Supabase storage connection...")
    
    try:
        from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
        
        storage = create_storage_manager_from_env()
        
        logger.info("✓ Supabase storage connection successful")
        logger.info(f"  - Images bucket: {storage.images_bucket}")
        logger.info(f"  - Reports bucket: {storage.reports_bucket}")
        return True
        
    except Exception as e:
        logger.error(f"✗ Supabase storage connection failed: {e}")
        return False


def test_ollama():
    """Test Ollama availability."""
    logger.info("Testing Ollama installation...")
    
    import subprocess
    
    try:
        result = subprocess.run(
            ['ollama', 'list'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logger.info("✓ Ollama is installed and running")
            
            # Check for required models
            output = result.stdout
            required_models = ['llava', 'llama3', 'nomic-embed-text']
            found_models = []
            
            for model in required_models:
                if model in output.lower():
                    found_models.append(model)
            
            if len(found_models) == len(required_models):
                logger.info("✓ All required Ollama models are installed")
                return True
            else:
                missing = set(required_models) - set(found_models)
                logger.warning(f"⚠ Missing Ollama models: {', '.join(missing)}")
                logger.warning("  Run: ollama pull <model_name> for each missing model")
                return False
        else:
            logger.error("✗ Ollama command failed")
            return False
            
    except FileNotFoundError:
        logger.error("✗ Ollama is not installed")
        logger.error("  Download from: https://ollama.ai")
        return False
    except Exception as e:
        logger.error(f"✗ Ollama test failed: {e}")
        return False


def test_yolo_model():
    """Test YOLO model availability."""
    logger.info("Testing YOLO model...")
    
    model_path = Path('Results/ppe_yolov86/weights/best.pt')
    
    if not model_path.exists():
        logger.error(f"✗ YOLO model not found at: {model_path}")
        logger.error("  Copy from Updated_Pipeline/Results/ or retrain the model")
        return False
    
    try:
        from ultralytics import YOLO
        
        model = YOLO(str(model_path))
        logger.info("✓ YOLO model loaded successfully")
        return True
        
    except Exception as e:
        logger.error(f"✗ YOLO model loading failed: {e}")
        return False


def test_gpu():
    """Test GPU availability."""
    logger.info("Testing GPU availability...")
    
    try:
        import torch
        
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"✓ GPU available: {gpu_name}")
            return True
        else:
            logger.warning("⚠ No GPU available - will use CPU (slower)")
            logger.warning("  Consider using a machine with NVIDIA GPU for better performance")
            return False
            
    except Exception as e:
        logger.error(f"✗ GPU test failed: {e}")
        return False


def test_dependencies():
    """Test Python dependencies."""
    logger.info("Testing Python dependencies...")
    
    required_packages = [
        'flask',
        'opencv-python',
        'ultralytics',
        'torch',
        'supabase',
        'psycopg2',
        'chromadb',
        'pillow'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.error(f"✗ Missing required packages: {', '.join(missing)}")
        logger.error("  Run: pip install -r requirements.txt")
        return False
    
    logger.info("✓ All required Python packages are installed")
    return True


def main():
    """Run all tests."""
    print("=" * 70)
    print("LUNA Supabase Edition - Setup Validation")
    print("=" * 70)
    print()
    
    tests = [
        ("Environment Variables", test_env_variables),
        ("Python Dependencies", test_dependencies),
        ("Supabase Database", test_supabase_db),
        ("Supabase Storage", test_supabase_storage),
        ("Ollama", test_ollama),
        ("YOLO Model", test_yolo_model),
        ("GPU", test_gpu)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print()
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"✗ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} - {test_name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print()
        print("🎉 All tests passed! Your system is ready to use.")
        print()
        print("Next steps:")
        print("  1. Run: python view_reports.py")
        print("  2. Open: http://localhost:5001")
        print()
        return 0
    else:
        print()
        print("⚠ Some tests failed. Please fix the issues above before proceeding.")
        print()
        print("For help, see:")
        print("  - INSTALL.md for detailed setup instructions")
        print("  - README.md for configuration details")
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
