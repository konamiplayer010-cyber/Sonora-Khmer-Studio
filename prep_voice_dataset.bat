@echo off
setlocal
cd /d "%~dp0"
title Sonora - voice training: recordings and reading script

set PY=python
where %PY% >nul 2>nul
if errorlevel 1 set PY=py

:menu
cls
echo =====================================================================
echo   VOICE TRAINING - build the material RVC learns from
echo =====================================================================
echo.
echo    1   Prepare my recordings ... I have recordings of me speaking
echo        Khmer  -^>  a clean training dataset + quality report
echo.
echo    2   Make me a reading script ... I have a Khmer text but nothing
echo        recorded yet  -^>  a numbered script to read aloud
echo.
echo    3   Check a dataset folder ... report only, no conversion
echo.
echo    0   Back to the main menu
echo.
set /p CH="  Choose 1-3 or 0: "

if "%CH%"=="1" goto prep
if "%CH%"=="2" goto script
if "%CH%"=="3" goto check
if "%CH%"=="0" exit /b 0
goto menu

:prep
echo.
set /p SRC="  Folder with my recordings (drag the folder here, then Enter): "
set SRC=%SRC:"=%
set /p DST="  Where should the training dataset go? (Enter = D:\khmer-dataset): "
if "%DST%"=="" set DST=D:\khmer-dataset
set DST=%DST:"=%
echo.
set /p DN="  Noise reduction? (y = yes, Enter = no): "
set OPT=
if /i "%DN%"=="y" set OPT=--denoise
echo.
%PY% "%~dp0prep_voice_dataset.py" --in "%SRC%" --out "%DST%" %OPT%
echo.
echo  Dataset: %DST%
echo  Read RVC-TRAIN-SETTINGS.txt there, then RVC-WebUI -^> Train.
pause
goto menu

:script
echo.
set /p BOOK="  Your Khmer text file (drag the .txt here, then Enter): "
set BOOK=%BOOK:"=%
set /p MIN="  How many minutes should I prepare? (Enter = 40): "
if "%MIN%"=="" set MIN=40
echo.
%PY% "%~dp0make_reading_script.py" --in "%BOOK%" --minutes %MIN%
echo.
echo  Read that script aloud and record it - same mic, same room, no music.
echo  Then menu 13 option 1 to build the dataset from your recordings.
pause
goto menu

:check
echo.
set /p DS="  Dataset folder to check (drag it here, then Enter): "
set DS=%DS:"=%
echo.
%PY% "%~dp0prep_voice_dataset.py" --out "%DS%" --check
pause
goto menu

