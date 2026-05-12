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
    echo   This tool needs a program called Python to run, and Python
    echo   isn't installed on this computer yet. Don't worry - it's
    echo   free and only takes a minute to set up.
    echo.
    echo   HOW TO INSTALL PYTHON:
    echo.
    echo     1. Open a web browser.
    echo     2. Go to:  https://www.python.org/downloads/
    echo     3. Click the big yellow "Download Python" button.
    echo     4. Open the file that downloads to your computer.
    echo     5. IMPORTANT:  On the FIRST screen of the installer,
    echo                    check the box that says
    echo                    "Add Python to PATH".
    echo     6. Click "Install Now" and wait for it to finish.
    echo     7. Come back here and double-click
    echo        "Start Photo Importer" again.
    echo.
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
echo   If it still doesn't work, contact your IT support.
echo  ============================================================
echo.
pause
exit /b 1
