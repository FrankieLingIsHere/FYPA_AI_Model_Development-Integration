@echo off
REM Readability: Utility script: keep operational maintenance steps visible and repeatable.
setlocal EnableExtensions

REM Section: perform this operational step before continuing.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%"

echo ==========================================
echo CASM Edge RealSense Relay
echo ==========================================

if not exist "venv\Scripts\activate.bat" (
  echo [ERROR] Virtual environment not found: venv\Scripts\activate.bat
REM Section: perform this operational step before continuing.
  echo Run setup first.
  pause
  exit /b 1
)

call "venv\Scripts\activate.bat"

python -c "import pyrealsense2" >nul 2>&1
if errorlevel 1 (
  echo RealSense Python SDK missing in this venv. Installing pyrealsense2...
REM Section: perform this operational step before continuing.
  python -m pip install --disable-pip-version-check pyrealsense2
  if errorlevel 1 (
    echo [ERROR] Could not install pyrealsense2 automatically.
    echo Install Intel RealSense SDK / pyrealsense2 manually, then rerun this relay.
    pause
    exit /b 1
  )
)

set "BACKEND_URL=%~1"
REM Section: perform this operational step before continuing.
if /I "%BACKEND_URL%"=="local" set "BACKEND_URL=http://127.0.0.1:5000"
if /I "%BACKEND_URL%"=="localhost" set "BACKEND_URL=http://127.0.0.1:5000"
if /I "%BACKEND_URL%"=="cloud" set "BACKEND_URL="

if "%BACKEND_URL%"=="" if not "%EDGE_REALSENSE_BACKEND_URL%"=="" set "BACKEND_URL=%EDGE_REALSENSE_BACKEND_URL%"
if "%BACKEND_URL%"=="" if not "%CASM_EDGE_REALSENSE_BACKEND_URL%"=="" set "BACKEND_URL=%CASM_EDGE_REALSENSE_BACKEND_URL%"
if "%BACKEND_URL%"=="" if exist ".env" (
  for /f "tokens=1,* delims==" %%A in ('findstr /B /I "CLOUD_URL=" ".env" 2^>nul') do (
    if /I "%%A"=="CLOUD_URL" if not "%%B"=="" set "BACKEND_URL=%%B"
  )
)
REM Section: perform this operational step before continuing.
if "%BACKEND_URL%"=="" set "BACKEND_URL=https://fypaaimodeldevelopment-integration-production.up.railway.app"

set "TOKEN_ARG="
if not "%EDGE_INGEST_TOKEN%"=="" set "TOKEN_ARG=--token %EDGE_INGEST_TOKEN%"

echo Backend URL: %BACKEND_URL%
echo App directory: %CD%
if not "%EDGE_INGEST_TOKEN%"=="" (
  echo Using EDGE_INGEST_TOKEN from environment.
)

REM Section: perform this operational step before continuing.
echo.
python edge_realsense_streamer.py --backend-url "%BACKEND_URL%" %TOKEN_ARG%

echo.
echo Relay stopped.
pause
