@echo off
setlocal
cd /d "%~dp0"
title Khmer TTS engines and voices

set PY=python
where %PY% >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3 was not found on this computer.
  echo Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo 1 - light engines   (edge-tts + Google)             small, needs internet
echo 2 - offline voices  (2 Khmer voices, no internet)   ~600 MB, one time
echo 3 - best quality   (+ VoxCPM2, needs ~8 GB NVIDIA GPU, ~5 GB weights)
echo 4 - just show me what I have
echo.
set /p CH=" Choose 1-4: "

if "%CH%"=="1" %PY% install_khmer_tts.py
if "%CH%"=="2" %PY% install_khmer_tts.py --offline
if "%CH%"=="3" %PY% install_khmer_tts.py --offline --voxcpm
if "%CH%"=="4" %PY% install_khmer_tts.py --check

echo.
pause
