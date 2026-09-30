@echo off
setlocal
cd /d "%~dp0"
title Khmer History Production Pipeline (Sonaro-Kh RVC)

set PY=python
where %PY% >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3 was not found on this computer.
  echo Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run run_all.bat again.
  echo.
  pause
  exit /b 1
)

echo --- making sure the system packages are installed (one-time) ---
%PY% -m pip --quiet install -r requirements_system.txt

%PY% run_all.py

echo.
pause
