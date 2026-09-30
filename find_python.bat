@echo off
setlocal
cd /d "%~dp0"
title Which python runs my RVC-WebUI

echo.
echo Looking for the python that has torch (that is your RVC python)...
echo It scans the RVC folder in config.json, including subfolders, and
echo also reads the RVC launcher .bat file if there is one.
echo.

python find_rvc_python.py

echo.
echo If the list above shows "no torch" for everything, your RVC python
echo is somewhere unusual. Send this whole window to me and I will point
echo at the right file. (Right-click -^> Mark to copy text from here.)
echo.
pause
