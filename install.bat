@echo off
REM ================================================================
REM  Oracle Photo Importer - Windows install script
REM  Creates a local virtual environment and installs dependencies.
REM ================================================================
setlocal EnableDelayedExpansion

echo.
echo === Oracle Photo Importer - Windows install ===
echo.

REM --- Locate Python ---
set "PYCMD="
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PYCMD=py -3"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "PYCMD=python"
    )
)

if "!PYCMD!"=="" (
    echo ERROR: Python 3.8+ is required but was not found.
    echo Install it from https://www.python.org/downloads/ and re-run install.bat.
    exit /b 1
)

echo Using Python: !PYCMD!
!PYCMD! --version

REM --- Create venv ---
if not exist .venv (
    echo Creating virtual environment in .venv ...
    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        exit /b 1
    )
)

REM --- Install dependencies ---
echo Installing dependencies ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency install failed.
    exit /b 1
)

REM --- Seed .env from example ---
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo Created .env from template - edit it with your Oracle credentials.
    )
)

echo.
echo Install complete.
echo.
echo Next steps:
echo   1. Edit .env with your Oracle credentials.
echo   2. Run: run.bat --dir "C:\path\to\photos"
echo.
endlocal
