@echo off
REM Reprocess All Reports with Latest Pipeline
REM ============================================

cd /d "%~dp0"

echo.
echo ========================================
echo  Reprocess All Reports Utility
echo ========================================
echo.
echo This will reprocess ALL existing reports
echo with the latest pipeline configuration.
echo.
echo Press Ctrl+C to cancel, or
pause

echo.
echo Starting reprocessing...
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run setup first or create venv.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

echo Virtual environment activated.
echo.

REM Check if .env file exists
if not exist ".env" (
    echo ERROR: .env file not found!
    echo Please create .env file with Supabase credentials.
    pause
    exit /b 1
)

REM Run reprocessing script
echo Running reprocess_reports.py --all
echo.
python reprocess_reports.py --all

if errorlevel 1 (
    echo.
    echo ERROR: Reprocessing failed!
    echo Check the error messages above.
) else (
    echo.
    echo ========================================
    echo  Reprocessing Complete Successfully!
    echo ========================================
)

echo.
pause
