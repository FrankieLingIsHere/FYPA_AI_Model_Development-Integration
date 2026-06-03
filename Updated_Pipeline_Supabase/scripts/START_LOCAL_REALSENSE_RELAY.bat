@echo off
REM Readability: Utility script: keep operational maintenance steps visible and repeatable.
setlocal EnableExtensions

REM Section: perform this operational step before continuing.
echo ==========================================
echo CASM Local RealSense Relay
echo ==========================================
echo This sends RealSense frames to the local backend at http://127.0.0.1:5000.
echo Use this for local mode. For cloud mode, use START_EDGE_REALSENSE_RELAY.bat.
echo.

call "%~dp0START_EDGE_REALSENSE_RELAY.bat" local
