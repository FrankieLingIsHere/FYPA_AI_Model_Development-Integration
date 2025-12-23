@echo off
REM LUNA Supabase Edition - Startup Script
REM ========================================
REM 
REM Quick start script for the LUNA PPE Safety Monitor with Supabase backend.
REM 
REM Usage:
REM   start.bat

echo ==========================================
echo LUNA Supabase Edition - Starting...
echo ==========================================
echo.

REM Change to script directory
cd /d "%~dp0"
echo Working directory: %CD%
echo.

REM Check if .env file exists
if not exist .env (
    echo Error: .env file not found!
    echo.
    echo Please create .env file from .env.example:
    echo   copy .env.example .env
    echo.
    echo Then edit .env with your Supabase credentials.
    pause
    exit /b 1
)

REM Check if venv exists and activate it
if not exist venv\Scripts\activate.bat (
    echo Virtual environment not found. Creating...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo Virtual environment created.
    echo.
)

echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Failed to activate virtual environment!
    pause
    exit /b 1
)
echo Virtual environment activated: %VIRTUAL_ENV%
echo.

REM Check if requirements need to be installed
pip show flask >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo Failed to install dependencies!
        pause
        exit /b 1
    )
    echo Dependencies installed.
    echo.
)

echo.
echo ==========================================
echo Starting Ollama Server...
echo ==========================================
echo.

REM Check if Ollama is installed
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo Warning: Ollama not found in PATH!
    echo Please install Ollama from: https://ollama.ai
    echo.
    echo The app will start but AI reports won't be generated.
    timeout /t 5
) else (
    echo Ollama found. Starting server in background...
    start "Ollama Server" /min cmd /c "ollama serve"
    timeout /t 3
    echo Ollama server started
)

echo.
echo ==========================================
echo Starting LUNA Application...
echo ==========================================
echo.
echo Once started, open your browser to:
echo   http://localhost:5000
echo.
echo To stop: Close this window or press Ctrl+C
echo ==========================================
echo.

REM Start the application
python luna_app.py
