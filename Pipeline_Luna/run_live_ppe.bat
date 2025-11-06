@echo off
REM Run live PPE compliance script using the repository's .venv if present.
REM The script expects this .bat to be placed in the project root.

cd /d %~dp0

SET VENV_ACT="%~dp0.venv\Scripts\activate.bat"
SET VENV_PY="%~dp0.venv\Scripts\python.exe"

if exist %VENV_ACT% (
    echo Activating virtualenv...
    call %VENV_ACT%
    echo Running live_ppe_compliance.py...
    python live_ppe_compliance.py
) else if exist %VENV_PY% (
    echo Virtualenv activation script not found but python.exe exists in .venv, running directly...
    %VENV_PY% live_ppe_compliance.py
) else (
    echo No .venv detected, using system python. If you want to use the project's venv, create it at .venv\
    python live_ppe_compliance.py
)

pause
