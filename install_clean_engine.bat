@echo off
setlocal
cd /d "%~dp0"
title Clean and Clear engine setup (clearvoice)

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

%PY% install_clean_engine.py %*

echo.
pause
