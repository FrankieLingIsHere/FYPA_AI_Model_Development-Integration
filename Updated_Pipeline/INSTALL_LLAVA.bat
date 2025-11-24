@echo off
REM ================================================================
REM LUNA - LLaVA Model Installation Script
REM ================================================================
REM This script installs the required packages for LLaVA image
REM captioning model (transformers, accelerate, bitsandbytes)
REM ================================================================

title LUNA - Installing LLaVA Dependencies

echo.
echo ================================================================
echo    LUNA - LLaVA Model Installation
echo ================================================================
echo.
echo This will install the required packages for AI image captioning:
echo   - transformers  (Hugging Face models)
echo   - accelerate    (GPU acceleration)
echo   - bitsandbytes  (4-bit quantization)
echo.
echo NOTE: First-time model download will be ~13GB
echo       This happens automatically when you first generate a caption
echo.
pause

echo.
echo ================================================================
echo [1/3] Installing transformers...
echo ================================================================
pip install transformers
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install transformers
    pause
    exit /b 1
)

echo.
echo ================================================================
echo [2/3] Installing accelerate...
echo ================================================================
pip install accelerate
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install accelerate
    pause
    exit /b 1
)

echo.
echo ================================================================
echo [3/3] Installing bitsandbytes...
echo ================================================================
pip install bitsandbytes
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] bitsandbytes installation failed
    echo This package enables 4-bit model loading (reduces memory usage)
    echo You can still use LLaVA, but it will use more GPU memory
    echo.
)

echo.
echo ================================================================
echo [VERIFY] Checking installation...
echo ================================================================
echo.

echo Checking transformers...
python -c "import transformers; print(f'  transformers: {transformers.__version__}')" 2>nul
if %errorlevel% neq 0 (
    echo   [ERROR] transformers not found
) else (
    echo   [OK] transformers installed
)

echo Checking accelerate...
python -c "import accelerate; print(f'  accelerate: {accelerate.__version__}')" 2>nul
if %errorlevel% neq 0 (
    echo   [ERROR] accelerate not found
) else (
    echo   [OK] accelerate installed
)

echo Checking bitsandbytes...
python -c "import bitsandbytes; print('  bitsandbytes: OK')" 2>nul
if %errorlevel% neq 0 (
    echo   [WARNING] bitsandbytes not found (optional)
) else (
    echo   [OK] bitsandbytes installed
)

echo.
echo Checking CUDA availability...
python -c "import torch; print(f'  CUDA available: {torch.cuda.is_available()}')" 2>nul

echo.
echo ================================================================
echo Installation Complete!
echo ================================================================
echo.
echo NEXT STEPS:
echo   1. Start LUNA: START_LUNA.bat
echo   2. Navigate to Live page
echo   3. Start live stream
echo   4. Trigger a violation
echo   5. Check caption.txt for AI-generated description!
echo.
echo NOTE: First caption generation will download the model (~13GB)
echo       This takes 10-30 minutes but only happens once
echo.
echo TIP: Test caption generation first:
echo      python caption_image.py path\to\image.jpg
echo.
pause
