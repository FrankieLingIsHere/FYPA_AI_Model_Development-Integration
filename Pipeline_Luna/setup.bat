@echo off
REM ============================================================================
REM PPE Safety Monitor - All-in-One Setup Script
REM ============================================================================
REM This script will set up the entire project automatically
REM ============================================================================

echo.
echo ============================================================================
echo    PPE SAFETY MONITOR - AUTOMATED SETUP
echo ============================================================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Running with administrator privileges
) else (
    echo [!] Not running as administrator - some features may not work
)

echo.
echo [1/9] Checking Python installation...
echo ----------------------------------------------------------------------------
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.10 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation!
    pause
    exit /b 1
)

python --version
for /f "tokens=2" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [OK] Python found: %PYTHON_VERSION%

REM Check Python version is 3.10+
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python 3.10 or higher is required!
    echo Your version: %PYTHON_VERSION%
    pause
    exit /b 1
)

echo.
echo [2/9] Checking NVIDIA GPU and CUDA...
echo ----------------------------------------------------------------------------
nvidia-smi >nul 2>&1
if %errorLevel% neq 0 (
    echo [WARNING] NVIDIA driver not found!
    echo This project requires an NVIDIA GPU with CUDA support.
    echo.
    echo Please install NVIDIA drivers from:
    echo https://www.nvidia.com/download/index.aspx
    echo.
    choice /C YN /M "Continue anyway (CPU mode - very slow)"
    if errorlevel 2 exit /b 1
) else (
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    echo [OK] NVIDIA GPU detected
)

echo.
echo [3/9] Creating virtual environment...
echo ----------------------------------------------------------------------------
if exist ".venv" (
    echo [!] Virtual environment already exists
    choice /C YN /M "Delete and recreate"
    if errorlevel 1 (
        echo Deleting existing .venv...
        rmdir /s /q .venv
    ) else (
        echo Using existing virtual environment
        goto :skip_venv
    )
)

python -m venv .venv
if %errorLevel% neq 0 (
    echo [ERROR] Failed to create virtual environment!
    pause
    exit /b 1
)
echo [OK] Virtual environment created

:skip_venv
echo.
echo [4/9] Activating virtual environment...
echo ----------------------------------------------------------------------------
call .venv\Scripts\activate.bat
if %errorLevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment!
    pause
    exit /b 1
)
echo [OK] Virtual environment activated

echo.
echo [5/9] Upgrading pip...
echo ----------------------------------------------------------------------------
python -m pip install --upgrade pip setuptools wheel
echo [OK] pip upgraded

echo.
echo [6/9] Installing PyTorch with CUDA 12.8 support...
echo ----------------------------------------------------------------------------
echo This may take 5-10 minutes depending on your internet speed...
echo.
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
if %errorLevel% neq 0 (
    echo [WARNING] Failed to install CUDA 12.8 version
    echo Trying CUDA 11.8...
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
)
echo [OK] PyTorch installed

echo.
echo [7/9] Installing project dependencies...
echo ----------------------------------------------------------------------------
echo This may take 10-15 minutes...
echo.
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install dependencies!
    pause
    exit /b 1
)
echo [OK] Dependencies installed

echo.
echo [8/9] Downloading LLaVA model...
echo ----------------------------------------------------------------------------
echo This will download ~14GB. Please be patient...
echo.
python -c "from transformers import AutoProcessor, LlavaForConditionalGeneration; print('Downloading LLaVA model...'); model = LlavaForConditionalGeneration.from_pretrained('llava-hf/llava-1.5-7b-hf', load_in_4bit=True, device_map='auto'); print('[OK] LLaVA model downloaded')"
if %errorLevel% neq 0 (
    echo [WARNING] Failed to download LLaVA model automatically
    echo The model will be downloaded on first use
)

echo.
echo [9/9] Setting up project directories...
echo ----------------------------------------------------------------------------
if not exist "data" mkdir data
if not exist "pipeline\backend\reports" mkdir pipeline\backend\reports
if not exist "pipeline\violations" mkdir pipeline\violations
if not exist "Meta-Llama-3-8B-Instruct" mkdir Meta-Llama-3-8B-Instruct
echo [OK] Directories created

echo.
echo ============================================================================
echo    MANUAL SETUP REQUIRED
echo ============================================================================
echo.
echo [!] DATASET SETUP (Required for training):
echo     1. Download PPE dataset from:
echo        https://www.kaggle.com/datasets/shlokraval/ppe-dataset-yolov8
echo     2. Extract to: data/
echo     3. Structure should be:
echo        data/
echo          ├── data.yaml
echo          ├── train/
echo          ├── valid/
echo          └── test/
echo.
echo [!] LLAMA 3 MODEL SETUP (Required for NLP analysis):
echo     1. Visit: https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct
echo     2. Click "Request Access" and wait for approval
echo     3. Install HuggingFace CLI:
echo        pip install huggingface_hub
echo     4. Login:
echo        huggingface-cli login
echo     5. Download model:
echo        python download_llama3.py
echo        (Or manually download to: Meta-Llama-3-8B-Instruct/)
echo.
echo     ALTERNATIVE: Use Ollama instead
echo        1. Install from: https://ollama.ai
echo        2. Run: ollama pull llama3
echo        3. System will auto-fallback to Ollama
echo.
echo ============================================================================

echo.
echo [10/10] Verifying installation...
echo ----------------------------------------------------------------------------
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA Available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"
python -c "import transformers; print(f'Transformers: {transformers.__version__}')"
python -c "import cv2; print(f'OpenCV: {cv2.__version__}')"
echo.
echo [OK] Core dependencies verified

echo.
echo ============================================================================
echo    SETUP COMPLETE!
echo ============================================================================
echo.
echo Next steps:
echo   1. Set up Llama 3 model (see instructions above)
echo   2. Optionally download dataset for training
echo   3. Test the system:
echo      • Live demo: run_live_ppe.bat
echo      • View reports: run_report_viewer.bat
echo   4. Read README.md for full documentation
echo.
echo The virtual environment is now active!
echo To activate it later: .venv\Scripts\activate.bat
echo.
echo ============================================================================

choice /C YN /M "Would you like to test the installation now"
if errorlevel 2 goto :end

echo.
echo Testing GPU and model loading...
python test_gpu_optimized.py

:end
echo.
echo Press any key to exit...
pause >nul
