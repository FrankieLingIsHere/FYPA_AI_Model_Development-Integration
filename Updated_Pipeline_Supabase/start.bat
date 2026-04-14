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

set "VENV_PYTHON=%CD%\venv\Scripts\python.exe"
set "VENV_PIP=%CD%\venv\Scripts\pip.exe"

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
if exist venv\Scripts\activate.bat goto ActivateVenv

echo Virtual environment not found. Creating...
py -3 -m venv venv
if %errorlevel% equ 0 goto VenvCreated

python -m venv venv
if %errorlevel% neq 0 (
    echo Failed to create virtual environment!
    pause
    exit /b 1
)

:VenvCreated
echo Virtual environment created.
echo.

:ActivateVenv
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Failed to activate virtual environment!
    pause
    exit /b 1
)
echo Virtual environment activated: %VIRTUAL_ENV%
echo.

if not exist "%VENV_PYTHON%" (
    echo Error: venv Python not found at:
    echo   %VENV_PYTHON%
    pause
    exit /b 1
)

if not exist "%VENV_PIP%" (
    echo Error: venv pip not found at:
    echo   %VENV_PIP%
    pause
    exit /b 1
)

REM Check if requirements need to be installed
"%VENV_PIP%" show flask >nul 2>&1
if %errorlevel% equ 0 goto SkipInstall

echo Installing dependencies...
"%VENV_PIP%" install -r requirements.txt
if %errorlevel% neq 0 (
    echo Failed to install dependencies!
    pause
    exit /b 1
)
echo Dependencies installed.
echo.

:SkipInstall

echo.
echo ==========================================
echo Checking Ollama Installation...
echo ==========================================
echo.

REM Check if Ollama is installed
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Ollama not found in PATH!
    echo Please install Ollama from: https://ollama.ai
    echo.
    pause
    exit /b 1
)

echo Ollama found. Starting server in background...
start "Ollama Server" /min cmd /c "ollama serve"
timeout /t 3
echo Ollama server started
echo.

echo ==========================================
echo Checking Unified Local Model (Gemma)...
echo ==========================================
echo.

REM Check if gemma4 unified model is installed
ollama list | findstr /I "gemma4" >nul 2>&1
if %errorlevel% neq 0 (
    echo Model 'gemma4' not found. Pulling from Ollama...
    echo This is a one-time download and may take a few minutes.
    echo.
    ollama pull gemma4
    if %errorlevel% neq 0 (
        echo Warning: Failed to pull gemma4 model!
        echo You can pull it manually later: ollama pull gemma4
        timeout /t 5
    ) else (
        echo Model pulled successfully!
    )
) else (
    echo Model 'gemma4' is already installed.
)
echo.

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
"%VENV_PYTHON%" luna_app.py
