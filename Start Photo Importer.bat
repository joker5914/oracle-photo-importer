@echo off
title Customer Photo Importer
cd /d "%~dp0"

REM ============================================================
REM   Find Python on this computer
REM ============================================================
set "PYCMD="
where py >nul 2>&1 && set "PYCMD=py -3"
if "%PYCMD%"=="" (
    where python >nul 2>&1 && set "PYCMD=python"
)

if "%PYCMD%"=="" (
    cls
    echo.
    echo  ============================================================
    echo                  Customer Photo Importer
    echo  ============================================================
    echo.
    echo   This computer doesn't have Python installed, which is
    echo   needed to run the tool from source.
    echo.
    echo   THE EASY WAY  -  use the ready-made version:
    echo   ============================================
    echo   You don't need to install anything. Just download the
    echo   prebuilt file and double-click it.
    echo.
    echo     1. Go to:
    echo        https://github.com/joker5914/oracle-photo-importer/releases/latest
    echo     2. Click  "Customer Photo Importer.exe"  to download it.
    echo     3. Double-click the downloaded file.
    echo.
    echo   ------------------------------------------------------------
    echo   The harder way is to install Python from
    echo   https://www.python.org/downloads/  (make sure to check the
    echo   "Add Python to PATH" box during install), then run
    echo   "Start Photo Importer" again.
    echo  ============================================================
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM   First-time setup: create the virtual environment
REM ============================================================
if not exist ".venv\Scripts\python.exe" (
    cls
    echo.
    echo  ============================================================
    echo                  Customer Photo Importer
    echo  ============================================================
    echo.
    echo   This is your first time using the tool.
    echo   Setting things up - this will take about a minute.
    echo.
    echo   Please don't close this window while it's working.
    echo.
    %PYCMD% -m venv .venv
    if errorlevel 1 goto :SETUP_FAILED
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip --quiet
    if errorlevel 1 goto :SETUP_FAILED
    python -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto :SETUP_FAILED
    echo.
    echo   All set up! Starting the tool now...
    timeout /t 2 >nul
) else (
    call ".venv\Scripts\activate.bat"
)

REM ============================================================
REM   Launch the importer
REM ============================================================
python photo_importer.py
exit /b %ERRORLEVEL%

:SETUP_FAILED
echo.
echo  ============================================================
echo   Setup didn't finish. Please try this:
echo.
echo     1. Make sure your computer has internet access.
echo     2. Close this window.
echo     3. Double-click "Start Photo Importer" again.
echo.
echo   If it still doesn't work, contact your IT support, or use
echo   the prebuilt .exe instead:
echo   https://github.com/joker5914/oracle-photo-importer/releases/latest
echo  ============================================================
echo.
pause
exit /b 1
