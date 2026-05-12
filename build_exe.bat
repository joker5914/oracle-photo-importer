@echo off
REM Build a single-file Windows .exe of photo_importer using PyInstaller.
REM Mainly for IT staff who want to distribute a standalone executable.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo  Setup hasn't been done yet on this machine.
    echo  Please double-click "Start Photo Importer.bat" once first,
    echo  let it finish setting up, then run this script again.
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install pyinstaller
pyinstaller --onefile --name photo_importer photo_importer.py
if errorlevel 1 (
    echo.
    echo  PyInstaller build failed.
    pause
    exit /b 1
)
echo.
echo  Built: dist\photo_importer.exe
echo.
pause
endlocal
