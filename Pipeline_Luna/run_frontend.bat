@echo off
echo ====================================
echo PPE Safety Monitor - Frontend
echo ====================================
echo.
echo Starting web application...
echo Open browser to: http://localhost:5001
echo.
echo Press Ctrl+C to stop
echo ====================================
echo.

.venv\Scripts\python.exe view_reports.py

pause
