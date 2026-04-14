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

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is missing. Launching Python 3.11 installer...
    winget install --id Python.Python.3.11 -e
    if %errorlevel% neq 0 (
        echo Failed to install Python using winget.
        echo Please manually install Python from python.org and rerun this script.
        pause
        exit /b 1
    )
    echo Python installed successfully. Needs PATH refresh.
) else (
    echo Python is already installed.
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
    echo Ollama is already installed.
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

echo ALLOW_OFFLINE_LOCAL_MODE=true >> .env

echo.
echo [4/5] Setting up Virtual Environment...
echo.
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
    if !errorlevel! neq 0 (
        echo "Failed to create python environment. Please reopen this terminal to refresh PATH and run start.bat manually."
        explorer .
        pause
        exit /b 1
    )
)

echo.
echo [5/5] Launching LUNA Background Server...
echo.
echo ========================================================
echo SETUP COMPLETE!  
echo The backend is now starting. Wait a moment for models
echo to load, then open your browser link again!
echo ========================================================
echo.

start cmd /k "start.bat"

exit /b 0
