@echo off
echo ================================================================
echo OpenCV GUI Fix for Windows
echo ================================================================
echo.
echo The current OpenCV installation does not have GUI support.
echo This will reinstall opencv-python with full GUI support.
echo.
pause

echo.
echo Uninstalling current OpenCV...
pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python

echo.
echo Installing OpenCV with GUI support...
pip install opencv-python==4.10.0.84

echo.
echo ================================================================
echo Installation complete!
echo ================================================================
echo.
echo You can now run: python run_live_demo.py
echo.
pause
