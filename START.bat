@echo off
setlocal
cd /d "%~dp0"
title Sonora Khmer Studio

rem shared neural weights for the Clean and Clear engine (both tools use this)
set CLEAN_CHECKPOINTS_DIR=%~dp0checkpoints
if not exist "%CLEAN_CHECKPOINTS_DIR%" mkdir "%CLEAN_CHECKPOINTS_DIR%" >nul 2>&1

set PY=python
where %PY% >nul 2>nul
if errorlevel 1 set PY=py

:menu
cls
echo =====================================================================
echo  SONORA KHMER STUDIO
echo  Khmer narration, cloning and mastering - one package
echo =====================================================================
echo.
echo    1   Sonora Studio ....... type text, listen live,
echo                              use your cloned voice
echo.
echo    2   Batch Pipeline ...... a whole Khmer script to one
echo                              finished audiobook, unattended
echo.
echo    3   Check my RVC model .. which .pth file is the clone?
echo.
echo    4   Install the Clean and Clear engine  (neural denoise)
echo.
echo    5   Play the sample audio  (raw vs cleaned)
echo.
echo    6   Find my RVC python ... which python runs your RVC-WebUI
echo                              (use this if an install says "no torch")
echo.
echo    7   Khmer voices ......... add engines / better quality
echo    8   Train my own Khmer voice  (free Google Colab)
echo.
echo    9   Hear the narration styles  (all 14 styles, one passage)
echo   10   Choose the narration style for the audiobook
echo.
echo   11   Test the clone ....... one paragraph through your
echo                              clone, before a whole book
echo   12   Fix the RVC python ... install what RVC itself is
echo                              missing (use this if the clone
echo                              test says "No module named ...")
echo.
echo   13   Voice training ...... prepare my recordings into an
echo                              RVC dataset, or make a numbered
echo                              Khmer script to read aloud (plus
echo                              the exact Train-tab settings)
echo.
echo    0   Quit
echo.
set /p CH="  Choose 1-13 or 0: "

if "%CH%"=="1" (
  call "%~dp0sonora\start.bat"
  goto menu
)
if "%CH%"=="2" (
  call "%~dp0pipeline\run_all.bat"
  goto menu
)
if "%CH%"=="3" (
  call "%~dp0pipeline\check_model.bat"
  goto menu
)
if "%CH%"=="4" (
  call "%~dp0pipeline\install_clean_engine.bat"
  goto menu
)
if "%CH%"=="5" (
  start "" "%~dp0pipeline\demo"
  goto menu
)
if "%CH%"=="6" (
  call "%~dp0pipeline\find_python.bat"
  goto menu
)
if "%CH%"=="7" (
  call "%~dp0pipeline\install_khmer_tts.bat"
  goto menu
)
if "%CH%"=="8" (
  echo.
  echo The training kit is in the khmer-colab folder next to this file:
  echo    khmer-colab\README.md               the full walkthrough
  echo    khmer-colab\Khmer_Voice_Colab.ipynb  upload this to Google Colab
  echo    khmer-colab\prepare_khmer_dataset.py prepare your recordings first
  echo.
  start "" "%~dp0khmer-colab"
  pause
  goto menu
)
if "%CH%"=="9" (
  start "" "%~dp0pipeline\demo\narration-styles.mp3"
  goto menu
)
if "%CH%"=="10" (
  %PY% "%~dp0pipeline\set_style.py"
  if errorlevel 9009 echo Python was not found - install it from python.org and tick "Add to PATH" during setup.
  pause
  goto menu
)
if "%CH%"=="11" (
  call "%~dp0pipeline\test_clone.bat"
  goto menu
)
if "%CH%"=="12" (
  call "%~dp0pipeline\fix_rvc_env.bat"
  goto menu
)
if "%CH%"=="13" (
  call "%~dp0pipeline\prep_voice_dataset.bat"
  goto menu
)
if "%CH%"=="0" exit /b 0
goto menu
