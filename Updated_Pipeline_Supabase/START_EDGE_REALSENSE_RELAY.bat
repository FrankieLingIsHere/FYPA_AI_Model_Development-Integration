@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo LUNA Edge RealSense Relay
echo ==========================================

if not exist "venv\Scripts\activate.bat" (
  echo [ERROR] Virtual environment not found: venv\Scripts\activate.bat
  echo Run setup first.
  pause
  exit /b 1
)

call "venv\Scripts\activate.bat"

set "BACKEND_URL=%~1"
if "%BACKEND_URL%"=="" set "BACKEND_URL=https://fypaaimodeldevelopment-integration-production.up.railway.app"

set "TOKEN_ARG="
if not "%EDGE_INGEST_TOKEN%"=="" set "TOKEN_ARG=--token %EDGE_INGEST_TOKEN%"

echo Backend URL: %BACKEND_URL%
if not "%EDGE_INGEST_TOKEN%"=="" (
  echo Using EDGE_INGEST_TOKEN from environment.
)

echo.
python edge_realsense_streamer.py --backend-url "%BACKEND_URL%" %TOKEN_ARG%

echo.
echo Relay stopped.
pause
