@echo off
setlocal
cd /d "%~dp0"
title Clone test - one paragraph

set PY=python
where %PY% >nul 2>nul
if errorlevel 1 set PY=py

echo Choose:
echo    1  quick test      (00 to 04: preflight, text, voice, YOUR clone)
echo    2  full test       (also 05 Clean and Clear, needs the neural engine)
echo.
set /p CH=" 1 or 2: "

if "%CH%"=="2" (
  %PY% test_clone.py --clean
) else (
  %PY% test_clone.py
)

echo.
pause
