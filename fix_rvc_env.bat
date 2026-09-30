@echo off
setlocal
cd /d "%~dp0"
title Fix the RVC python

set PY=python
where %PY% >nul 2>nul
if errorlevel 1 set PY=py

%PY% fix_rvc_env.py %*
if errorlevel 9009 echo Python was not found - install it from python.org and tick "Add to PATH" during setup.

echo.
pause
