@echo off
setlocal
cd /d "%~dp0"
title Sonora - Notebook to Podcast

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3 was not found on this computer.
  echo Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run start.bat again.
  echo.
  pause
  exit /b 1
)

rem ---- make sure pip exists (Python 3.14 installs can ship without it) ----
python -m pip --version >nul 2>&1
if not errorlevel 1 goto pipok
echo pip was not found - restoring it now (one-time fix)...
python -m ensurepip --upgrade >nul 2>&1
python -m pip --version >nul 2>&1
if not errorlevel 1 goto pipok
echo Downloading get-pip.py ...
curl -L -o get-pip.py https://bootstrap.pypa.io/get-pip.py >nul 2>&1
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py" >nul 2>&1
python get-pip.py --quiet >nul 2>&1
python -m pip --version >nul 2>&1
if not errorlevel 1 goto pipok
echo.
echo Could not set up pip automatically. Run this command once in a terminal:
echo     python -m ensurepip --upgrade
echo then run start.bat again.
echo.
pause
exit /b 1
:pipok

echo Installing the HD voice engine (first run only, ~1 min)...
python -m pip install --quiet edge-tts imageio-ffmpeg numpy gtts
if errorlevel 1 (
  echo.
  echo Could not install dependencies. Check your internet connection and try again.
  echo.
  pause
  exit /b 1
)

echo Starting Sonora...
start /b python server.py
timeout /t 8 /nobreak >nul
start "" "http://localhost:8000"
echo.
echo Sonora is running at http://localhost:8000
echo ^(If the page says "can't connect", wait a few seconds and press F5.^)
echo Keep this window open while you work - close it to stop Sonora.
pause
