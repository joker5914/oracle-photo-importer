@echo off
REM Build a single-file Windows .exe of photo_importer using PyInstaller.
setlocal
if not exist .venv\Scripts\activate.bat (
    echo Virtual environment not found. Run install.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install pyinstaller
pyinstaller --onefile --name photo_importer photo_importer.py
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)
echo.
echo Built: dist\photo_importer.exe
endlocal
