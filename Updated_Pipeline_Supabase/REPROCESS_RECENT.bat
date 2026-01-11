@echo off
REM Reprocess Recent Reports (This Week)
REM =====================================

cd /d "%~dp0"

echo.
echo ========================================
echo  Reprocess Recent Reports
echo ========================================
echo.
echo This will reprocess reports from the
echo current week with the latest pipeline.
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

REM Get Monday of current week as YYYY-MM-DD
REM Use Python to calculate Monday date properly
echo Calculating this week's start date...
for /f "delims=" %%i in ('python -c "from datetime import datetime, timedelta; d = datetime.now(); monday = d - timedelta(days=d.weekday()); print(monday.strftime('%%Y-%%m-%%d'))"') do set monday_date=%%i

echo Reprocessing reports since: %monday_date%
echo.

REM Run reprocessing script for this week
python reprocess_reports.py --since %monday_date%

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
