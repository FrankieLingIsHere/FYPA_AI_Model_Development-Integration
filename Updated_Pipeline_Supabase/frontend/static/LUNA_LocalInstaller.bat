@echo off
setlocal EnableDelayedExpansion

echo ========================================================
echo LUNA PPE SAFETY MONITOR - ZERO-TOUCH LOCAL INSTALLER
echo ========================================================
echo.
echo This script will automatically download and set up the 
echo LUNA Local Backend on this machine so it can run 
echo completely offline.
echo.
echo Please ensure you are running this as Administrator if 
echo Python or Ollama need to be installed.
echo.
pause

set "INSTALL_DIR=C:\LUNA_System"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
cd /d "%INSTALL_DIR%"

echo [1/5] Checking System Dependencies...
echo.

set "PYTHON_EXE="
echo Checking for compatible Python installation...
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py -3"
) else (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    )
)

if "!PYTHON_EXE!"=="" (
    echo Python is completely missing. Launching Python 3.11 installer...
    winget install --id Python.Python.3.11 -e
    if !errorlevel! neq 0 (
        echo Failed to install Python using winget.
        echo Please manually install Python 3.11 from python.org and rerun this script.
        pause
        exit /b 1
    )
    echo Python installed successfully.
    set "PYTHON_EXE=python"
) else (
    !PYTHON_EXE! -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Outdated Python detected! 
        echo LUNA requires Python 3.10 or higher ^(You have an older version like 2.7 or 3.9^).
        echo Launching Python 3.11 installer natively...
        winget install --id Python.Python.3.11 -e
        set "PYTHON_EXE=py -3.11"
    ) else (
        echo Python 3.10+ is already installed and compatible.
    )
)

where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo Ollama is missing. Launching Ollama installer...
    winget install --id Ollama.Ollama -e
    if %errorlevel% neq 0 (
        echo.
        echo Falling back to direct download for Ollama...
        curl -L https://ollama.com/download/OllamaSetup.exe -o OllamaSetup.exe
        start /wait OllamaSetup.exe /S
        del OllamaSetup.exe
    )
    echo Ollama installed successfully.
) else (
    echo.
    echo Ollama is already installed.
    echo Waking up Ollama background service if it is asleep...
    start /b ollama serve >nul 2>&1
)

echo.
echo [2/5] Downloading LUNA Source Code...
echo.
if exist "FYPA_AI_Model_Development-Integration-main" (
    echo Source code folder already exists. Skipping download.
) else (
    echo Downloading from GitHub...
    curl -L https://github.com/FrankieLingIsHere/FYPA_AI_Model_Development-Integration/archive/refs/heads/main.zip -o luna.zip
    echo Extracting files...
    powershell -command "Expand-Archive -Force luna.zip ."
    del luna.zip
)

cd FYPA_AI_Model_Development-Integration-main\Updated_Pipeline_Supabase

echo.
echo [3/5] Configuring Environment...
echo.
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo Created default .env configuration.
    ) else (
        echo Warning: .env.example not found!
    )
)

findstr /B /I "ALLOW_OFFLINE_LOCAL_MODE=" .env >nul 2>&1 || echo ALLOW_OFFLINE_LOCAL_MODE=true>> .env
findstr /B /I "GEMINI_ENABLED=" .env >nul 2>&1 || echo GEMINI_ENABLED=false>> .env
findstr /B /I "MODEL_API_ENABLED=" .env >nul 2>&1 || echo MODEL_API_ENABLED=false>> .env
findstr /B /I "STARTUP_AUTO_PREPARE_LOCAL_MODE=" .env >nul 2>&1 || echo STARTUP_AUTO_PREPARE_LOCAL_MODE=true>> .env
findstr /B /I "STARTUP_AUTO_PULL_LOCAL_MODEL=" .env >nul 2>&1 || echo STARTUP_AUTO_PULL_LOCAL_MODEL=true>> .env
findstr /B /I "LOCAL_OLLAMA_UNIFIED_MODEL=" .env >nul 2>&1 || echo LOCAL_OLLAMA_UNIFIED_MODEL=gemma4>> .env
findstr /B /I "OLLAMA_MODEL=" .env >nul 2>&1 || echo OLLAMA_MODEL=gemma4>> .env
findstr /B /I "NLP_PROVIDER_ORDER=" .env >nul 2>&1 || echo NLP_PROVIDER_ORDER=ollama,local,gemini,model_api>> .env

echo Local mode defaults ensured in .env ^(offline enabled, Gemini disabled, Ollama model aligned^)

echo.
echo [4/5] Setting up Virtual Environment...
echo.
if not exist "venv\Scripts\activate.bat" (
    !PYTHON_EXE! -m venv venv
    if !errorlevel! neq 0 (
        echo "Failed to create python environment. Please reopen this terminal to refresh PATH and run start.bat manually."
        explorer .
        pause
        exit /b 1
    )
)

echo.
echo [5/6] Launching LUNA Background Server...
echo.
echo ========================================================
echo SETUP COMPLETE!  
echo The backend is now starting in a new window. 
echo The first boot may take 2-5 minutes to download AI 
echo dependencies in that new black window.
echo ========================================================
echo.

start cmd /k "start.bat"

echo [6/6] Creating Desktop Shortcut for Future Use...
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Start LUNA Local Mode.lnk"
set "TARGET_PATH=%CD%\start.bat"
set "WORKING_DIR=%CD%"

powershell -Command "$wshell = New-Object -ComObject WScript.Shell; $shortcut = $wshell.CreateShortcut('%SHORTCUT_PATH%'); $shortcut.TargetPath = '%TARGET_PATH%'; $shortcut.WorkingDirectory = '%WORKING_DIR%'; $shortcut.Description = 'Launch LUNA Offline Mode'; $shortcut.Save()"

echo.
echo --------------------------------------------------------
echo A shortcut "Start LUNA Local Mode" has been placed on 
echo your Desktop. YOU NO LONGER NEED THIS INSTALLER FILE!
echo Double-click that shortcut anytime you want to launch.
echo --------------------------------------------------------
echo You can safely close this installer window now.
pause
exit /b 0
