@echo off
setlocal
cd /d "%~dp0"
title Which .pth is my voice clone?

set RPY=
for /f "delims=" %%i in ('python -c "import sys;sys.path.insert(0,'.');import common;c=common.load_config();print(c.get('rvc_python') or '')" 2^>nul') do set RPY=%%i
if "%RPY%"=="" for %%P in ("venv\Scripts\python.exe" ".venv\Scripts\python.exe") do if exist "%%~P" set RPY=%%~P
if "%RPY%"=="" for /f "delims=" %%i in ('python find_rvc_python.py --quiet 2^>nul') do if not defined RPY set RPY=%%i

echo.
if "%RPY%"=="" goto syspython
echo Using this python, which has torch, so the check looks INSIDE the files:
echo    %RPY%
echo.
"%RPY%" check_model.py %*
goto done

:syspython
echo Using the python on this PC's PATH.
echo The report's first lines say whether that python can look inside the files.
echo A full content check needs torch. If the report says "name and size only",
echo run menu 6 first - Find my RVC python - then run this again.
echo.
python check_model.py %*

:done
echo.
pause
