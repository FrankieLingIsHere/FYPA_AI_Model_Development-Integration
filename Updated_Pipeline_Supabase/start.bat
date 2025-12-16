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

REM Check if venv exists
if not exist venv (
    echo Warning: Virtual environment not found.
    echo.
    echo Creating virtual environment...
    python -m venv venv
    echo Virtual environment created
    echo.
    echo Installing dependencies...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    echo Dependencies installed
) else (
    echo Virtual environment found
    call venv\Scripts\activate.bat
)

echo.
echo Starting LUNA application...
echo.
echo Once started, open your browser to:
echo   http://localhost:5000
echo.
echo Press Ctrl+C to stop the server.
echo.
echo ==========================================
echo.

REM Start the application
python luna_app.py
