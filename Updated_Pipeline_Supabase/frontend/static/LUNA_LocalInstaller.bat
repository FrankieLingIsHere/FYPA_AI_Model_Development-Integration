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

set "LUNA_REPO_ZIP_URL=__LUNA_REPO_ZIP_URL__"
set "LUNA_SOURCE_ROOT=__LUNA_SOURCE_ROOT__"
set "LUNA_CLOUD_URL=__LUNA_CLOUD_URL__"
set "LUNA_INSTALLER_VERSION=__LUNA_INSTALLER_VERSION__"
set "LUNA_MACHINE_ID=__LUNA_MACHINE_ID__"
set "LUNA_SUPABASE_URL=__LUNA_SUPABASE_URL__"
set "LUNA_SUPABASE_DB_URL=__LUNA_SUPABASE_DB_URL__"
set "LUNA_SUPABASE_SERVICE_ROLE_KEY=__LUNA_SUPABASE_SERVICE_ROLE_KEY__"
set "LUNA_FORCE_SOURCE_REFRESH=false"
set "LUNA_AUTO_UPDATE_ON_LAUNCH=true"
set "LUNA_PROMPT_UPDATE_ON_LAUNCH=true"
set "LUNA_SELF_UPDATE_LAUNCHER=true"

if /I "!LUNA_CLOUD_URL!"=="__LUNA_CLOUD_URL__" set "LUNA_CLOUD_URL="
if /I "!LUNA_MACHINE_ID!"=="__LUNA_MACHINE_ID__" set "LUNA_MACHINE_ID="
if /I "!LUNA_SUPABASE_URL!"=="__LUNA_SUPABASE_URL__" set "LUNA_SUPABASE_URL="
if /I "!LUNA_SUPABASE_DB_URL!"=="__LUNA_SUPABASE_DB_URL__" set "LUNA_SUPABASE_DB_URL="
if /I "!LUNA_SUPABASE_SERVICE_ROLE_KEY!"=="__LUNA_SUPABASE_SERVICE_ROLE_KEY__" set "LUNA_SUPABASE_SERVICE_ROLE_KEY="

echo Installer version: !LUNA_INSTALLER_VERSION!
echo Installer source archive: !LUNA_REPO_ZIP_URL!
if not "!LUNA_CLOUD_URL!"=="" echo Installer cloud backend URL: !LUNA_CLOUD_URL!

set "INSTALL_DIR=C:\LUNA_System"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
cd /d "%INSTALL_DIR%"
set "LOCAL_LAUNCHER_BAT=%INSTALL_DIR%\Start_LUNA_Local_Mode.bat"
set "LUNA_STATE_DIR_PATH=C:\LUNA_System\LUNA_LocalState"
if not exist "!LUNA_STATE_DIR_PATH!" mkdir "!LUNA_STATE_DIR_PATH!"

copy /Y "%~f0" "!LOCAL_LAUNCHER_BAT!" >nul 2>&1
if errorlevel 1 (
    echo Warning: Could not update local launcher copy at !LOCAL_LAUNCHER_BAT!
)

if not "!LUNA_MACHINE_ID!"=="" (
    >"!LUNA_STATE_DIR_PATH!\machine_id.txt" echo !LUNA_MACHINE_ID!
    if errorlevel 1 (
        echo Warning: Could not seed local machine ID into !LUNA_STATE_DIR_PATH!\machine_id.txt
    ) else (
        echo Seeded local machine ID from approved installer token: !LUNA_MACHINE_ID!
    )
)

set "LUNA_APP_DIR=!LUNA_SOURCE_ROOT!\Updated_Pipeline_Supabase"

if not exist "!LUNA_STATE_DIR_PATH!\machine_id.txt" (
    if exist "!LUNA_APP_DIR!\machine_id.txt" (
        copy /Y "!LUNA_APP_DIR!\machine_id.txt" "!LUNA_STATE_DIR_PATH!\machine_id.txt" >nul 2>&1
        if not errorlevel 1 (
            echo Migrated machine ID from legacy app-directory state file.
        )
    ) else (
        if exist "!LUNA_APP_DIR!\local_mode_provision_state.json" (
            powershell -NoProfile -ExecutionPolicy Bypass -Command ^
              "$statePath='!LUNA_APP_DIR!\local_mode_provision_state.json'; $machinePath='!LUNA_STATE_DIR_PATH!\machine_id.txt'; try { $payload = Get-Content -Raw -Path $statePath -ErrorAction Stop | ConvertFrom-Json; $machineId = [string]$payload.machine_id; if(-not [string]::IsNullOrWhiteSpace($machineId)){ Set-Content -Path $machinePath -Value $machineId -Encoding ASCII } } catch { exit 1 }"
            if not errorlevel 1 (
                if exist "!LUNA_STATE_DIR_PATH!\machine_id.txt" (
                    echo Recovered machine ID from legacy provisioning-state file.
                )
            )
        )
    )
)

if exist "!LUNA_APP_DIR!\.env" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$envPath='!LUNA_APP_DIR!\.env'; $lines=@(Get-Content -Path $envPath -ErrorAction SilentlyContinue); if($null -eq $lines){$lines=@()}; " ^
      "$updates=[ordered]@{ 'LUNA_STATE_DIR'='C:\LUNA_System\LUNA_LocalState' }; if(-not [string]::IsNullOrWhiteSpace($env:LUNA_CLOUD_URL)){ $updates['CLOUD_URL']=$env:LUNA_CLOUD_URL }; " ^
      "if((-not [string]::IsNullOrWhiteSpace($env:LUNA_SUPABASE_URL)) -and (-not [string]::IsNullOrWhiteSpace($env:LUNA_SUPABASE_DB_URL)) -and (-not [string]::IsNullOrWhiteSpace($env:LUNA_SUPABASE_SERVICE_ROLE_KEY))){ $updates['SUPABASE_URL']=$env:LUNA_SUPABASE_URL; $updates['SUPABASE_DB_URL']=$env:LUNA_SUPABASE_DB_URL; $updates['SUPABASE_SERVICE_ROLE_KEY']=$env:LUNA_SUPABASE_SERVICE_ROLE_KEY }; " ^
    "if($updates.Count -gt 0){ $keyPattern='^\s*([A-Za-z_][A-Za-z0-9_]*)\s*='; $seen=@{}; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $keyPattern){ $k=$Matches[1]; if($updates.Contains($k)){ if(-not $seen.ContainsKey($k)){ $lines[$i]=($k + '=' + $updates[$k]); $seen[$k]=$true } else { $lines[$i]='' } } } }; foreach($k in $updates.Keys){ if(-not $seen.ContainsKey($k)){ $lines += ($k + '=' + $updates[$k]) } }; $lines = $lines | Where-Object { $_ -ne '' }; Set-Content -Path $envPath -Value $lines -Encoding UTF8 }"

    if %errorlevel% neq 0 (
        echo Warning: Could not pre-sync existing .env values from installer payload.
    ) else (
        echo Existing .env synchronized from installer payload before launch/reinstall decision.
    )
)

if exist "!LUNA_APP_DIR!\start.bat" (
    echo.
    echo Existing local installation detected:
    echo   !LUNA_APP_DIR!
    echo.
    set "LUNA_SHOULD_CHECK_UPDATES=false"
    if /I "!LUNA_AUTO_UPDATE_ON_LAUNCH!"=="true" set "LUNA_SHOULD_CHECK_UPDATES=true"

    if /I "!LUNA_PROMPT_UPDATE_ON_LAUNCH!"=="true" (
        echo Choose launch mode:
        echo   [1] Launch now ^(skip update check^)
        echo   [2] Check for updates then launch ^(recommended^)
        set "LUNA_LAUNCH_CHOICE="
        set /p "LUNA_LAUNCH_CHOICE=Enter choice [1/2] ^(default 2^): "
        if "!LUNA_LAUNCH_CHOICE!"=="" set "LUNA_LAUNCH_CHOICE=2"
        if "!LUNA_LAUNCH_CHOICE!"=="1" set "LUNA_SHOULD_CHECK_UPDATES=false"
        if "!LUNA_LAUNCH_CHOICE!"=="2" set "LUNA_SHOULD_CHECK_UPDATES=true"
        echo.
    )

    if /I "!LUNA_SHOULD_CHECK_UPDATES!"=="true" (
        echo Checking for source updates before launch...
        call :refresh_existing_source_snapshot
        if errorlevel 1 (
            echo Warning: Auto-update failed or was skipped. Launching existing local files.
            if not "!LUNA_UPDATE_ERROR!"=="" echo   Reason: !LUNA_UPDATE_ERROR!
        ) else (
            echo Local source snapshot updated successfully.
        )
        echo.

        call :safe_refresh_local_launcher
        if errorlevel 1 (
            echo Warning: Could not self-update launcher script from latest template.
            if not "!LUNA_LAUNCHER_UPDATE_ERROR!"=="" echo   Reason: !LUNA_LAUNCHER_UPDATE_ERROR!
        ) else (
            echo Launcher script refreshed to latest installer logic.
        )
        echo.
    ) else (
        echo Skipping source update check for this launch.
        echo.
    )

    echo Launching existing LUNA local backend...
    cd /d "!LUNA_APP_DIR!"
    start cmd /k "start.bat"
    echo.
    echo Existing installation launched.
    echo You can keep using the same launcher BAT:
    echo   !LOCAL_LAUNCHER_BAT!
    pause
    exit /b 0
)

echo.
echo [1/6] Checking System Dependencies...
echo.

set "PYTHON_EXE="
echo Checking for compatible Python installation...
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py -3"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
    )
)

if "!PYTHON_EXE!"=="" (
    echo Python is completely missing. Launching Python 3.11 installer...
    winget install --id Python.Python.3.11 -e
    if !errorlevel! neq 0 (
        echo Failed to install Python using winget.
        echo Please manually install Python 3.11 from python.org and rerun this script.
        pause
        exit /b 1
    )
    echo Python installed successfully.
    set "PYTHON_EXE=python"
) else (
    !PYTHON_EXE! -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Outdated Python detected!
        echo LUNA requires Python 3.10 or higher ^(You have an older version like 2.7 or 3.9^).
        echo Launching Python 3.11 installer natively...
        winget install --id Python.Python.3.11 -e
        set "PYTHON_EXE=py -3.11"
    ) else (
        echo Python 3.10+ is already installed and compatible.
    )
)

where ollama >nul 2>&1
if errorlevel 1 (
    echo.
    echo Ollama is missing. Launching Ollama installer...
    winget install --id Ollama.Ollama -e
    if errorlevel 1 (
        echo.
        echo Falling back to direct download for Ollama...
        curl -L https://ollama.com/download/OllamaSetup.exe -o OllamaSetup.exe
        start /wait OllamaSetup.exe /S
        del OllamaSetup.exe
    )
    echo Ollama installed successfully.
) else (
    echo.
    echo Ollama is already installed.
)

echo Ensuring Ollama service is reachable...
call :ensure_ollama_running 30
if errorlevel 1 (
    echo Warning: Ollama did not become reachable yet. Continuing setup; start.bat will retry with readiness checks.
) else (
    echo Ollama service is reachable.
)

echo.
echo [2/6] Downloading LUNA Source Code...
echo.
if exist "!LUNA_SOURCE_ROOT!" (
    if /I "!LUNA_FORCE_SOURCE_REFRESH!"=="true" (
        echo Existing source folder found. Refreshing to latest snapshot...
        rmdir /s /q "!LUNA_SOURCE_ROOT!"
        if exist "!LUNA_SOURCE_ROOT!" (
            echo Warning: Could not remove existing source folder. Continuing with current snapshot.
        )
    ) else (
        echo Source code folder already exists. Skipping download.
    )
)

if not exist "!LUNA_SOURCE_ROOT!" (
    echo Downloading from GitHub...
    curl -L "!LUNA_REPO_ZIP_URL!" -o luna.zip
    echo Extracting files...
    powershell -command "Expand-Archive -Force luna.zip ."
    del luna.zip
)

cd "!LUNA_SOURCE_ROOT!\Updated_Pipeline_Supabase"

echo.
echo [3/6] Configuring Environment...
echo.
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo Created default .env configuration.
    ) else (
        echo Warning: .env.example not found!
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$envPath='.env'; $lines=@(Get-Content -Path $envPath -ErrorAction SilentlyContinue); if($null -eq $lines){$lines=@()}; " ^
    "$updates=[ordered]@{ 'ALLOW_OFFLINE_LOCAL_MODE'='true'; 'GEMINI_ENABLED'='false'; 'MODEL_API_ENABLED'='false'; 'STARTUP_AUTO_PREPARE_LOCAL_MODE'='true'; 'STARTUP_AUTO_PULL_LOCAL_MODEL'='true'; 'STARTUP_AUTO_PROVISION_LOCAL_MODE'='true'; 'STARTUP_AUTO_PROVISION_POLL_INTERVAL_SECONDS'='15'; 'STARTUP_AUTO_PROVISION_MAX_ATTEMPTS'='0'; 'LOCAL_OLLAMA_UNIFIED_MODEL'='gemma4'; 'OLLAMA_MODEL'='gemma4'; 'NLP_PROVIDER_ORDER'='ollama,local'; 'VISION_PROVIDER_ORDER'='ollama'; 'EMBEDDING_PROVIDER_ORDER'='ollama'; 'OLLAMA_AUTO_UPGRADE_ON_PULL_FAIL'='true'; 'LUNA_STATE_DIR'='C:\LUNA_System\LUNA_LocalState'; 'SUPABASE_OFFLINE_LOG_LEVEL'='info' }; " ^
    "foreach($entry in $updates.GetEnumerator()){ $key=$entry.Key; $value=$entry.Value; $pattern='^\s*'+[regex]::Escape($key)+'\s*='; $updated=$false; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $pattern){ if(-not $updated){ $lines[$i]=($key + '=' + $value); $updated=$true } else { $lines[$i]='' } } }; if(-not $updated){ $lines += ($key + '=' + $value) } }; " ^
    "$placeholder='your-project-id|your-service-role-key|your-db-password|example\.supabase\.co'; foreach($key in @('SUPABASE_URL','SUPABASE_DB_URL','SUPABASE_SERVICE_ROLE_KEY')){ $pattern='^\s*'+[regex]::Escape($key)+'\s*=\s*(.*)$'; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $pattern){ $value=($Matches[1] -as [string]); if($value -match $placeholder){ $lines[$i]=($key + '=') }; break } } }; " ^
    "$lines = $lines | Where-Object { $_ -ne '' }; Set-Content -Path $envPath -Value $lines -Encoding UTF8"

if %errorlevel% neq 0 (
    echo Warning: Could not normalize .env local defaults. Proceeding with existing values.
) else (
    echo Local mode defaults normalized in .env ^(offline enabled, Gemini disabled, Ollama-only routing aligned^)
)

if not "!LUNA_CLOUD_URL!"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$envPath='.env'; $lines=@(Get-Content -Path $envPath -ErrorAction SilentlyContinue); if($null -eq $lines){$lines=@()}; " ^
      "$key='CLOUD_URL'; $value='!LUNA_CLOUD_URL!'; $pattern='^\s*'+[regex]::Escape($key)+'\s*='; $updated=$false; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $pattern){ if(-not $updated){ $lines[$i]=($key + '=' + $value); $updated=$true } else { $lines[$i]='' } } }; if(-not $updated){ $lines += ($key + '=' + $value) }; " ^
      "$lines = $lines | Where-Object { $_ -ne '' }; Set-Content -Path $envPath -Value $lines -Encoding UTF8"

    if %errorlevel% neq 0 (
        echo Warning: Could not write CLOUD_URL into .env automatically.
    ) else (
        echo CLOUD_URL configured from installer source endpoint.
    )
) else (
    echo Warning: Installer cloud URL not provided by source endpoint. CLOUD_URL was left unchanged.
)

if not "!LUNA_SUPABASE_URL!"=="" if not "!LUNA_SUPABASE_DB_URL!"=="" if not "!LUNA_SUPABASE_SERVICE_ROLE_KEY!"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$envPath='.env'; $lines=@(Get-Content -Path $envPath -ErrorAction SilentlyContinue); if($null -eq $lines){$lines=@()}; " ^
      "$updates=[ordered]@{ 'SUPABASE_URL'=$env:LUNA_SUPABASE_URL; 'SUPABASE_DB_URL'=$env:LUNA_SUPABASE_DB_URL; 'SUPABASE_SERVICE_ROLE_KEY'=$env:LUNA_SUPABASE_SERVICE_ROLE_KEY }; " ^
      "foreach($entry in $updates.GetEnumerator()){ $key=$entry.Key; $value=$entry.Value; $pattern='^\s*'+[regex]::Escape($key)+'\s*='; $updated=$false; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $pattern){ if(-not $updated){ $lines[$i]=($key + '=' + $value); $updated=$true } else { $lines[$i]='' } } }; if(-not $updated){ $lines += ($key + '=' + $value) } }; " ^
      "$lines = $lines | Where-Object { $_ -ne '' }; Set-Content -Path $envPath -Value $lines -Encoding UTF8"

    if %errorlevel% neq 0 (
        echo Warning: Could not apply provisioned Supabase credentials into .env automatically.
    ) else (
        echo Supabase credentials applied from approved installer payload.
    )
) else (
    echo Provisioned Supabase credentials were not embedded in this installer package.
    echo Auto-provisioning will continue in the background at runtime.
)

echo.
echo [4/6] Setting up Virtual Environment...
echo.
if not exist "venv\Scripts\activate.bat" (
    !PYTHON_EXE! -m venv venv
    if !errorlevel! neq 0 (
        echo Failed to create python environment. Please reopen this terminal to refresh PATH and run start.bat manually.
        explorer .
        pause
        exit /b 1
    )
)

echo.
echo [5/6] Launching LUNA Background Server...
echo.
echo ========================================================
echo SETUP COMPLETE!
echo The backend is now starting in a new window.
echo The first boot may take 2-5 minutes to download AI
echo dependencies in that new black window.
echo ========================================================
echo.

start cmd /k "start.bat"

echo [6/6] Creating Desktop Shortcut for Future Use...
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Start LUNA Local Mode.lnk"
copy /Y "%~f0" "!LOCAL_LAUNCHER_BAT!" >nul 2>&1
if errorlevel 1 (
    echo Warning: Could not refresh local launcher copy at !LOCAL_LAUNCHER_BAT!
)
set "TARGET_PATH=%LOCAL_LAUNCHER_BAT%"
set "WORKING_DIR=%INSTALL_DIR%"

powershell -Command "$wshell = New-Object -ComObject WScript.Shell; $shortcut = $wshell.CreateShortcut('%SHORTCUT_PATH%'); $shortcut.TargetPath = '%TARGET_PATH%'; $shortcut.WorkingDirectory = '%WORKING_DIR%'; $shortcut.Description = 'Launch LUNA Offline Mode'; $shortcut.Save()"

echo.
echo --------------------------------------------------------
echo A shortcut "Start LUNA Local Mode" has been placed on
echo your Desktop and points to the same installer-launcher BAT.
echo Double-click the same BAT/shortcut anytime to launch.
echo If LUNA is already installed, it auto-refreshes source then launches.
echo Reinstall/refresh is optional and only needed for recovery.
echo --------------------------------------------------------
echo You can safely close this installer window now.
pause
goto :eof

:ensure_ollama_running
set "OLLAMA_WAIT_SECONDS=%~1"
if "%OLLAMA_WAIT_SECONDS%"=="" set "OLLAMA_WAIT_SECONDS=30"

where ollama >nul 2>&1
if errorlevel 1 exit /b 1

ollama list >nul 2>&1
if !errorlevel! equ 0 exit /b 0

start "" /b ollama serve >nul 2>&1

for /L %%I in (1,1,%OLLAMA_WAIT_SECONDS%) do (
    ollama list >nul 2>&1
    if !errorlevel! equ 0 exit /b 0
    timeout /t 1 /nobreak >nul
)

exit /b 1

:refresh_existing_source_snapshot
set "UPDATE_ZIP=%TEMP%\luna_source_update.zip"
set "UPDATE_STAGE=%TEMP%\luna_source_update_%RANDOM%_%RANDOM%"
set "UPDATE_SOURCE_DIR="
set "LUNA_UPDATE_ERROR="

if "!LUNA_REPO_ZIP_URL!"=="" (
    set "LUNA_UPDATE_ERROR=missing_repo_zip_url"
    exit /b 1
)
if /I "!LUNA_REPO_ZIP_URL!"=="__LUNA_REPO_ZIP_URL__" (
    set "LUNA_UPDATE_ERROR=placeholder_repo_zip_url"
    exit /b 1
)

set "UPDATE_DOWNLOAD_OK="
curl.exe -fL --retry 2 --retry-delay 1 --connect-timeout 15 --max-time 180 "!LUNA_REPO_ZIP_URL!" -o "!UPDATE_ZIP!" >nul 2>&1
if not errorlevel 1 set "UPDATE_DOWNLOAD_OK=1"

if "!UPDATE_DOWNLOAD_OK!"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '!LUNA_REPO_ZIP_URL!' -OutFile '!UPDATE_ZIP!' -TimeoutSec 240; exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        set "LUNA_UPDATE_ERROR=download_failed"
        goto :refresh_existing_source_snapshot_fail
    )
)

if not exist "!UPDATE_ZIP!" (
    set "LUNA_UPDATE_ERROR=zip_missing_after_download"
    goto :refresh_existing_source_snapshot_fail
)

for %%Z in ("!UPDATE_ZIP!") do (
    if %%~zZ LSS 1024 (
        set "LUNA_UPDATE_ERROR=zip_too_small"
        goto :refresh_existing_source_snapshot_fail
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force '!UPDATE_ZIP!' '!UPDATE_STAGE!'" >nul 2>&1
if errorlevel 1 (
    set "LUNA_UPDATE_ERROR=zip_extract_failed"
    goto :refresh_existing_source_snapshot_fail
)

if exist "!UPDATE_STAGE!\!LUNA_SOURCE_ROOT!\Updated_Pipeline_Supabase\start.bat" (
    set "UPDATE_SOURCE_DIR=!UPDATE_STAGE!\!LUNA_SOURCE_ROOT!\Updated_Pipeline_Supabase"
) else (
    for /d %%D in ("!UPDATE_STAGE!\*") do (
        if exist "%%~fD\Updated_Pipeline_Supabase\start.bat" (
            set "UPDATE_SOURCE_DIR=%%~fD\Updated_Pipeline_Supabase"
        )
    )
)

if "!UPDATE_SOURCE_DIR!"=="" (
    set "LUNA_UPDATE_ERROR=source_dir_not_found"
    goto :refresh_existing_source_snapshot_fail
)

robocopy "!UPDATE_SOURCE_DIR!" "!LUNA_APP_DIR!" /E /R:2 /W:1 /NFL /NDL /NP /XD ".git" "venv" "__pycache__" "Results" "reports" "violations" /XF ".env" >nul
set "ROBOCOPY_CODE=!errorlevel!"
if !ROBOCOPY_CODE! GEQ 8 (
    set "LUNA_UPDATE_ERROR=robocopy_failed_!ROBOCOPY_CODE!"
    goto :refresh_existing_source_snapshot_fail
)

if exist "!UPDATE_ZIP!" del "!UPDATE_ZIP!" >nul 2>&1
if exist "!UPDATE_STAGE!" rmdir /s /q "!UPDATE_STAGE!" >nul 2>&1
set "LUNA_UPDATE_ERROR="
exit /b 0

:refresh_existing_source_snapshot_fail
if exist "!UPDATE_ZIP!" del "!UPDATE_ZIP!" >nul 2>&1
if exist "!UPDATE_STAGE!" rmdir /s /q "!UPDATE_STAGE!" >nul 2>&1
exit /b 1

:safe_refresh_local_launcher
set "LUNA_LAUNCHER_UPDATE_ERROR="
call :refresh_local_launcher_from_template >nul 2>&1
if not errorlevel 1 exit /b 0

set "TEMPLATE_BAT=!LUNA_APP_DIR!\frontend\static\LUNA_LocalInstaller.bat"
set "UPDATED_LAUNCHER=%TEMP%\luna_launcher_update_%RANDOM%_%RANDOM%.bat"

if /I "!LUNA_SELF_UPDATE_LAUNCHER!" NEQ "true" (
    set "LUNA_LAUNCHER_UPDATE_ERROR=self_update_disabled"
    exit /b 1
)
if not exist "!TEMPLATE_BAT!" (
    set "LUNA_LAUNCHER_UPDATE_ERROR=template_missing"
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$current = Get-Content -Raw -Path '%~f0' -ErrorAction Stop; " ^
  "$template = Get-Content -Raw -Path '!TEMPLATE_BAT!' -ErrorAction Stop; " ^
  "$tokenMap = [ordered]@{ '__LUNA_REPO_ZIP_URL__'='LUNA_REPO_ZIP_URL'; '__LUNA_SOURCE_ROOT__'='LUNA_SOURCE_ROOT'; '__LUNA_CLOUD_URL__'='LUNA_CLOUD_URL'; '__LUNA_INSTALLER_VERSION__'='LUNA_INSTALLER_VERSION'; '__LUNA_MACHINE_ID__'='LUNA_MACHINE_ID'; '__LUNA_SUPABASE_URL__'='LUNA_SUPABASE_URL'; '__LUNA_SUPABASE_DB_URL__'='LUNA_SUPABASE_DB_URL'; '__LUNA_SUPABASE_SERVICE_ROLE_KEY__'='LUNA_SUPABASE_SERVICE_ROLE_KEY' }; " ^
  "foreach($token in $tokenMap.Keys){ $varName = $tokenMap[$token]; $pattern = '(?im)^\s*set\s+\"' + [regex]::Escape($varName) + '=(.*)\"\s*$'; $m = [regex]::Match($current, $pattern); $value = if($m.Success){ $m.Groups[1].Value } else { '' }; $template = $template.Replace($token, [string]$value) }; " ^
    "Set-Content -Path '!UPDATED_LAUNCHER!' -Value $template -Encoding ASCII"

if errorlevel 1 (
    if exist "!UPDATED_LAUNCHER!" del "!UPDATED_LAUNCHER!" >nul 2>&1
    set "LUNA_LAUNCHER_UPDATE_ERROR=fallback_template_render_failed"
    exit /b 1
)

if /I "%~f0"=="!LOCAL_LAUNCHER_BAT!" (
    start "" cmd /c "timeout /t 2 >nul & copy /Y \"!UPDATED_LAUNCHER!\" \"!LOCAL_LAUNCHER_BAT!\" >nul & del \"!UPDATED_LAUNCHER!\" >nul"
) else (
    copy /Y "!UPDATED_LAUNCHER!" "!LOCAL_LAUNCHER_BAT!" >nul 2>&1
    if errorlevel 1 (
        del "!UPDATED_LAUNCHER!" >nul 2>&1
        set "LUNA_LAUNCHER_UPDATE_ERROR=fallback_launcher_copy_failed"
        exit /b 1
    )
    del "!UPDATED_LAUNCHER!" >nul 2>&1
)

set "LUNA_LAUNCHER_UPDATE_ERROR="
exit /b 0

:refresh_local_launcher_from_template
set "LUNA_LAUNCHER_UPDATE_ERROR="
set "TEMPLATE_BAT=!LUNA_APP_DIR!\frontend\static\LUNA_LocalInstaller.bat"
set "UPDATED_LAUNCHER=%TEMP%\luna_launcher_update_%RANDOM%_%RANDOM%.bat"

if /I "!LUNA_SELF_UPDATE_LAUNCHER!" NEQ "true" (
    set "LUNA_LAUNCHER_UPDATE_ERROR=self_update_disabled"
    exit /b 1
)
if not exist "!TEMPLATE_BAT!" (
    set "LUNA_LAUNCHER_UPDATE_ERROR=template_missing"
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$current = Get-Content -Raw -Path '%~f0' -ErrorAction Stop; " ^
  "$template = Get-Content -Raw -Path '!TEMPLATE_BAT!' -ErrorAction Stop; " ^
  "$tokenMap = [ordered]@{ '__LUNA_REPO_ZIP_URL__'='LUNA_REPO_ZIP_URL'; '__LUNA_SOURCE_ROOT__'='LUNA_SOURCE_ROOT'; '__LUNA_CLOUD_URL__'='LUNA_CLOUD_URL'; '__LUNA_INSTALLER_VERSION__'='LUNA_INSTALLER_VERSION'; '__LUNA_MACHINE_ID__'='LUNA_MACHINE_ID'; '__LUNA_SUPABASE_URL__'='LUNA_SUPABASE_URL'; '__LUNA_SUPABASE_DB_URL__'='LUNA_SUPABASE_DB_URL'; '__LUNA_SUPABASE_SERVICE_ROLE_KEY__'='LUNA_SUPABASE_SERVICE_ROLE_KEY' }; " ^
  "foreach($token in $tokenMap.Keys){ $varName = $tokenMap[$token]; $pattern = '(?im)^\s*set\s+\"' + [regex]::Escape($varName) + '=(.*)\"\s*$'; $m = [regex]::Match($current, $pattern); $value = if($m.Success){ $m.Groups[1].Value } else { '' }; $template = $template.Replace($token, [string]$value) }; " ^
    "Set-Content -Path '!UPDATED_LAUNCHER!' -Value $template -Encoding ASCII"

if errorlevel 1 (
    if exist "!UPDATED_LAUNCHER!" del "!UPDATED_LAUNCHER!" >nul 2>&1
    set "LUNA_LAUNCHER_UPDATE_ERROR=template_render_failed"
    exit /b 1
)

if /I "%~f0"=="!LOCAL_LAUNCHER_BAT!" (
    start "" cmd /c "timeout /t 2 >nul & copy /Y \"!UPDATED_LAUNCHER!\" \"!LOCAL_LAUNCHER_BAT!\" >nul & del \"!UPDATED_LAUNCHER!\" >nul"
) else (
    copy /Y "!UPDATED_LAUNCHER!" "!LOCAL_LAUNCHER_BAT!" >nul 2>&1
    if errorlevel 1 (
        del "!UPDATED_LAUNCHER!" >nul 2>&1
        set "LUNA_LAUNCHER_UPDATE_ERROR=launcher_copy_failed"
        exit /b 1
    )
    del "!UPDATED_LAUNCHER!" >nul 2>&1
)

set "LUNA_LAUNCHER_UPDATE_ERROR="
exit /b 0
