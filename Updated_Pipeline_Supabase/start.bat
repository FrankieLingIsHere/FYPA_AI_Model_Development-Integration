@echo off
setlocal EnableExtensions EnableDelayedExpansion
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
set "OLLAMA_CMD="

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

REM Normalize .env local defaults so stale cloud settings do not override local BAT startup.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$envPath='.env'; $lines=@(Get-Content -Path $envPath -ErrorAction SilentlyContinue); if($null -eq $lines){$lines=@()}; " ^
    "$updates=[ordered]@{ 'ALLOW_OFFLINE_LOCAL_MODE'='true'; 'GEMINI_ENABLED'='false'; 'MODEL_API_ENABLED'='false'; 'STARTUP_AUTO_PREPARE_LOCAL_MODE'='true'; 'STARTUP_AUTO_PULL_LOCAL_MODEL'='true'; 'STARTUP_AUTO_PROVISION_LOCAL_MODE'='true'; 'STARTUP_AUTO_PROVISION_POLL_INTERVAL_SECONDS'='15'; 'STARTUP_AUTO_PROVISION_MAX_ATTEMPTS'='0'; 'LOCAL_OLLAMA_UNIFIED_MODEL'='gemma4'; 'OLLAMA_MODEL'='gemma4'; 'NLP_PROVIDER_ORDER'='ollama,local'; 'VISION_PROVIDER_ORDER'='ollama'; 'EMBEDDING_PROVIDER_ORDER'='ollama'; 'OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL'='true'; 'LUNA_STATE_DIR'='C:\LUNA_System\LUNA_LocalState'; 'SUPABASE_OFFLINE_LOG_LEVEL'='info' }; " ^
    "foreach($entry in $updates.GetEnumerator()){ $key=$entry.Key; $value=$entry.Value; $pattern='^\s*'+[regex]::Escape($key)+'\s*='; $updated=$false; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $pattern){ if(-not $updated){ $lines[$i]=($key + '=' + $value); $updated=$true } else { $lines[$i]='' } } }; if(-not $updated){ $lines += ($key + '=' + $value) } }; " ^
    "$placeholder='your-project-id|your-service-role-key|your-db-password|example\.supabase\.co'; foreach($key in @('SUPABASE_URL','SUPABASE_DB_URL','SUPABASE_SERVICE_ROLE_KEY')){ $pattern='^\s*'+[regex]::Escape($key)+'\s*=\s*(.*)$'; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $pattern){ $value=($Matches[1] -as [string]); if($value -match $placeholder){ $lines[$i]=($key + '=') }; break } } }; " ^
    "$lines = $lines | Where-Object { $_ -ne '' }; Set-Content -Path $envPath -Value $lines -Encoding UTF8"
if %errorlevel% neq 0 (
        echo Warning: Could not normalize .env local defaults. Continuing with existing file values.
)

REM Local-first runtime profile (avoid cloud-only provider checks in local BAT flow)
set "ALLOW_OFFLINE_LOCAL_MODE=true"
set "GEMINI_ENABLED=false"
set "MODEL_API_ENABLED=false"
set "STARTUP_AUTO_PREPARE_LOCAL_MODE=true"
set "STARTUP_AUTO_PULL_LOCAL_MODEL=true"
set "STARTUP_AUTO_PROVISION_LOCAL_MODE=true"
set "STARTUP_AUTO_PROVISION_POLL_INTERVAL_SECONDS=15"
set "STARTUP_AUTO_PROVISION_MAX_ATTEMPTS=0"
set "SUPABASE_OFFLINE_LOG_LEVEL=info"

REM Read model preference from .env when present so startup checks and model pull stay aligned
for /f "tokens=2 delims==" %%A in ('findstr /B /I "OLLAMA_MODEL=" .env 2^>nul') do set "OLLAMA_MODEL=%%~A"
for /f "tokens=2 delims==" %%A in ('findstr /B /I "LOCAL_OLLAMA_UNIFIED_MODEL=" .env 2^>nul') do set "LOCAL_OLLAMA_UNIFIED_MODEL=%%~A"
for /f "tokens=2 delims==" %%A in ('findstr /B /I "OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL=" .env 2^>nul') do set "OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL=%%~A"

if "%LOCAL_OLLAMA_UNIFIED_MODEL%"=="" set "LOCAL_OLLAMA_UNIFIED_MODEL=gemma4"
if "%OLLAMA_MODEL%"=="" set "OLLAMA_MODEL=%LOCAL_OLLAMA_UNIFIED_MODEL%"
if "%OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL%"=="" set "OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL=true"

set "OLLAMA_MODEL=%OLLAMA_MODEL:\"=%"
set "LOCAL_OLLAMA_UNIFIED_MODEL=%LOCAL_OLLAMA_UNIFIED_MODEL:\"=%"
set "OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL=%OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL:\"=%"
set "NLP_PROVIDER_ORDER=ollama,local"
set "VISION_PROVIDER_ORDER=ollama"
set "EMBEDDING_PROVIDER_ORDER=ollama"

echo Local mode profile: GEMINI_ENABLED=%GEMINI_ENABLED%, MODEL_API_ENABLED=%MODEL_API_ENABLED%
echo Ollama model for startup checks: %OLLAMA_MODEL%
echo Ollama auto-upgrade on pull fail: %OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL%
echo.

if not exist "pipeline\backend\integration\safety_knowledge.txt" (
    if exist "NLP_Luna\Trim1.csv" (
        copy /Y "NLP_Luna\Trim1.csv" "pipeline\backend\integration\safety_knowledge.txt" >nul
        if errorlevel 1 (
            echo Warning: Failed to restore safety knowledge file from NLP_Luna\Trim1.csv.
        ) else (
            echo Restored missing safety knowledge file from NLP_Luna\Trim1.csv.
        )
    ) else (
        echo Warning: Could not find NLP_Luna\Trim1.csv to restore safety knowledge file.
    )
)
echo.

REM Check if venv exists and activate it
if not exist venv\Scripts\activate.bat (
    echo Virtual environment not found. Creating...
    py -3 -m venv venv
    if errorlevel 1 (
        python -m venv venv
    )
    if errorlevel 1 (
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

REM Keep dependencies synced with latest source updates.
echo Synchronizing Python dependencies...
"%VENV_PIP%" install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo Failed to synchronize dependencies!
    pause
    exit /b 1
)
echo Dependencies synchronized.
echo.

echo.
echo ==========================================
echo Checking Ollama Installation...
echo ==========================================
echo.

REM Resolve Ollama executable from PATH or known install locations.
call :resolve_ollama_cmd
if errorlevel 1 (
    echo Error: Ollama executable not found.
    echo Please install Ollama from: https://ollama.com/download
    echo.
    pause
    exit /b 1
)

echo Ollama found at: %OLLAMA_CMD%
echo Starting server in background...
call :safe_start_ollama_and_wait_ready 30
if errorlevel 1 (
    echo Error: Ollama server did not become ready within 30 seconds.
    echo Please open Ollama once, then rerun this script.
    pause
    exit /b 1
)
echo Ollama server is ready
echo.

echo ==========================================
echo Checking Ollama Model (%OLLAMA_MODEL%)...
echo ==========================================
echo.

REM Check if configured model is installed
"%OLLAMA_CMD%" list | findstr /I /C:"%OLLAMA_MODEL%" >nul 2>&1
if errorlevel 1 (
    echo Model '%OLLAMA_MODEL%' not found. Pulling from Ollama...
    echo This is a one-time download and may take a few minutes.
    echo.
    call :pull_ollama_model_with_upgrade "%OLLAMA_MODEL%"
    if errorlevel 1 (
        echo Warning: Failed to pull model '%OLLAMA_MODEL%'!
        echo You can pull it manually later: ollama pull %OLLAMA_MODEL%
        timeout /t 5 >nul
    ) else (
        echo Model pulled successfully!
    )
) else (
    echo Model '%OLLAMA_MODEL%' is already installed.
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

goto :eof

:resolve_ollama_cmd
set "OLLAMA_CMD="

where ollama >nul 2>&1
if not errorlevel 1 (
    set "OLLAMA_CMD=ollama"
    exit /b 0
)

if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_CMD=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    exit /b 0
)

if exist "%ProgramFiles%\Ollama\ollama.exe" (
    set "OLLAMA_CMD=%ProgramFiles%\Ollama\ollama.exe"
    exit /b 0
)

if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\Ollama\ollama.exe" (
    set "OLLAMA_CMD=%ProgramFiles(x86)%\Ollama\ollama.exe"
    exit /b 0
)

exit /b 1

:pull_ollama_model_with_upgrade
set "MODEL_TO_PULL=%~1"
set "PULL_LOG=%TEMP%\luna_ollama_pull_%RANDOM%.log"
set "PULL_STATUS=1"

"%OLLAMA_CMD%" pull "%MODEL_TO_PULL%" > "%PULL_LOG%" 2>&1
set "PULL_STATUS=!errorlevel!"
type "%PULL_LOG%"

if "!PULL_STATUS!"=="0" (
    del "%PULL_LOG%" >nul 2>&1
    exit /b 0
)

set "UPGRADE_REASON="
findstr /I /C:"requires a newer version of Ollama" /C:"please download the latest version" /C:"pull model manifest: 412" "%PULL_LOG%" >nul 2>&1
if "!errorlevel!"=="0" set "UPGRADE_REASON=model manifest requires a newer Ollama runtime"

if "!UPGRADE_REASON!"=="" (
    if /I "!OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL!"=="true" (
        set "UPGRADE_REASON=model pull failed and auto-upgrade fallback is enabled"
    )
)

if not "!UPGRADE_REASON!"=="" (
    echo.
    echo Pull failed because !UPGRADE_REASON!.
    echo Attempting automatic Ollama upgrade...
    call :upgrade_ollama_runtime
    if "!errorlevel!"=="0" (
        echo Retry pulling '%MODEL_TO_PULL%' after Ollama upgrade...
        call :resolve_ollama_cmd
        if errorlevel 1 (
            set "PULL_STATUS=1"
        ) else (
            "%OLLAMA_CMD%" pull "%MODEL_TO_PULL%"
            set "PULL_STATUS=!errorlevel!"
        )
    ) else (
        echo Ollama upgrade attempt failed.
    )
)

del "%PULL_LOG%" >nul 2>&1
exit /b !PULL_STATUS!

:upgrade_ollama_runtime
set "UPGRADE_STATUS=1"

echo Stopping running Ollama processes...
taskkill /IM ollama.exe /F >nul 2>&1

where winget >nul 2>&1
if not errorlevel 1 (
    winget upgrade --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    if !errorlevel! equ 0 (
        set "UPGRADE_STATUS=0"
        goto :upgrade_ollama_runtime_restart
    )

    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    if !errorlevel! equ 0 (
        set "UPGRADE_STATUS=0"
        goto :upgrade_ollama_runtime_restart
    )
)

echo Falling back to direct Ollama installer download...
curl -L "https://ollama.com/download/OllamaSetup.exe" -o "%TEMP%\OllamaSetup.exe"
if !errorlevel! neq 0 goto :upgrade_ollama_runtime_done

start /wait "" "%TEMP%\OllamaSetup.exe" /S
set "INSTALL_STATUS=!errorlevel!"
del "%TEMP%\OllamaSetup.exe" >nul 2>&1
if !INSTALL_STATUS! neq 0 goto :upgrade_ollama_runtime_done

set "UPGRADE_STATUS=0"

:upgrade_ollama_runtime_restart

echo Restarting Ollama service after upgrade...
taskkill /IM ollama.exe /F >nul 2>&1
call :safe_start_ollama_and_wait_ready 30
if errorlevel 1 (
    echo Warning: Ollama service did not become ready after upgrade.
    set "UPGRADE_STATUS=1"
)

:upgrade_ollama_runtime_done
exit /b !UPGRADE_STATUS!

:safe_start_ollama_and_wait_ready
set "OLLAMA_WAIT_SECONDS=%~1"
if "%OLLAMA_WAIT_SECONDS%"=="" set "OLLAMA_WAIT_SECONDS=30"

findstr /R /I /C:"^:start_ollama_and_wait_ready$" "%~f0" >nul 2>&1
if errorlevel 1 (
    echo Warning: startup helper label missing; using inline Ollama readiness fallback.
    call :resolve_ollama_cmd
    if errorlevel 1 exit /b 1
    start "Ollama Server" /min cmd /c "\"%OLLAMA_CMD%\" serve"
    for /L %%I in (1,1,%OLLAMA_WAIT_SECONDS%) do (
        "%OLLAMA_CMD%" list >nul 2>&1
        if !errorlevel! equ 0 (
            exit /b 0
        )
        timeout /t 1 /nobreak >nul
    )
    exit /b 1
)

call :start_ollama_and_wait_ready %OLLAMA_WAIT_SECONDS%
if !errorlevel! equ 0 exit /b 0

call :resolve_ollama_cmd
if errorlevel 1 exit /b 1
start "Ollama Server" /min cmd /c "\"%OLLAMA_CMD%\" serve"
for /L %%I in (1,1,%OLLAMA_WAIT_SECONDS%) do (
    "%OLLAMA_CMD%" list >nul 2>&1
    if !errorlevel! equ 0 (
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)
exit /b 1

:start_ollama_and_wait_ready
set "OLLAMA_WAIT_SECONDS=%~1"
if "%OLLAMA_WAIT_SECONDS%"=="" set "OLLAMA_WAIT_SECONDS=30"

call :resolve_ollama_cmd
if errorlevel 1 exit /b 1

start "Ollama Server" /min cmd /c "\"%OLLAMA_CMD%\" serve"

for /L %%I in (1,1,%OLLAMA_WAIT_SECONDS%) do (
    "%OLLAMA_CMD%" list >nul 2>&1
    if !errorlevel! equ 0 (
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)

exit /b 1
