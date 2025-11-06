@echo off
REM Run GUI PPE inference using the repository's .venv if present.
REM Place this file in the project root next to gui_infer.py.

cd /d %~dp0

SET VENV_ACT="%~dp0.venv\Scripts\activate.bat"
SET VENV_PY="%~dp0.venv\Scripts\python.exe"

if exist %VENV_ACT% (
    echo Activating virtualenv...
    call %VENV_ACT%
    echo Running gui_infer.py...
    python gui_infer.py
) else if exist %VENV_PY% (
    echo Virtualenv activation script not found but python.exe exists in .venv, running directly...
    %VENV_PY% gui_infer.py
) else (
    echo No .venv detected, using system python. If you want to use the project's venv, create it at .venv\
    python gui_infer.py
)

pause
