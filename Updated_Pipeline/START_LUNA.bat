@echo off
REM ============================================================================
REM LUNA PPE Safety Monitor - Quick Start
REM ============================================================================
REM This launches the complete LUNA system with one click!
REM ============================================================================

cd /d "%~dp0"

REM Check for virtual environment
SET VENV_PYTHON="%~dp0venv\Scripts\python.exe"

if exist %VENV_PYTHON% (
    SET PYTHON_CMD=%VENV_PYTHON%
) else (
    SET PYTHON_CMD=python
)

cls
echo.
echo ================================================================================
echo                       LUNA PPE SAFETY MONITOR
echo                          Quick Start Launcher
echo ================================================================================
echo.
echo Starting the unified LUNA system...
echo.
echo This will launch:
echo   [*] Backend API Server
echo   [*] Live Monitoring System
echo   [*] Web Interface
echo   [*] Reports Dashboard
echo.
echo ================================================================================
echo.

REM Wait a moment for user to read
timeout /t 3 /nobreak >nul

echo Opening web interface in browser...
timeout /t 2 /nobreak >nul
start http://localhost:5000

echo.
echo Starting LUNA server...
echo.
echo ================================================================================
echo.
echo  Web Interface: http://localhost:5000
echo.
echo  Features:
echo    - Dashboard (Home)
echo    - Live Monitoring (Click "Live" in menu)
echo    - Reports ^& Analytics
echo    - Image Upload Inference
echo.
echo  To START live monitoring:
echo    1. Click "Live" in the navigation
echo    2. Click the "Start" button
echo    3. Your webcam will activate with real-time PPE detection
echo.
echo  Press Ctrl+C here to stop the server
echo.
echo ================================================================================
echo.

%PYTHON_CMD% luna_app.py

pause
