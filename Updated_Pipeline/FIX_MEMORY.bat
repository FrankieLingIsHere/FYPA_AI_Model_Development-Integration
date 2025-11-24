@echo off
REM ================================================================
REM Fix Windows Page File Size for AI Model Loading
REM ================================================================
REM This script increases virtual memory (page file) to support
REM large AI models like LLaVA that need 8-12GB of memory
REM ================================================================

echo.
echo ================================================================
echo    Increase Windows Page File for AI Models
echo ================================================================
echo.
echo Current error: "The paging file is too small for this operation"
echo.
echo This means Windows virtual memory needs to be increased.
echo.
echo MANUAL STEPS TO FIX:
echo ================================================================
echo.
echo 1. Press Windows Key + Pause/Break (or right-click This PC ^> Properties)
echo 2. Click "Advanced system settings"
echo 3. Under "Performance" click "Settings"
echo 4. Go to "Advanced" tab
echo 5. Under "Virtual memory" click "Change..."
echo 6. UNCHECK "Automatically manage paging file size"
echo 7. Select your C: drive
echo 8. Choose "Custom size"
echo 9. Set:
echo    - Initial size: 16384 MB (16 GB)
echo    - Maximum size: 32768 MB (32 GB)
echo 10. Click "Set"
echo 11. Click "OK" on all windows
echo 12. RESTART YOUR COMPUTER
echo.
echo ================================================================
echo After restart, run LUNA again and LLaVA will work!
echo ================================================================
echo.
pause
