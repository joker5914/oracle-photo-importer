@echo off
REM Activate the local venv and run the importer with any passed args.
setlocal
if not exist .venv\Scripts\activate.bat (
    echo Virtual environment not found. Run install.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat
python photo_importer.py %*
endlocal
