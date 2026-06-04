@echo off
cd /d "%~dp0"

:: Create venv if it doesn't exist
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Python not found. Please install Python 3.10 or newer.
        pause
        exit /b 1
    )
)

:: Check all required packages at once
venv\Scripts\python.exe -c "import webview" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo ERROR: Dependency installation failed.
        pause
        exit /b 1
    )
)

:: Download React/Babel for offline use if not already present
if not exist "frontend\lib\react.production.min.js" (
    echo Downloading frontend libraries ^(one-time setup^)...
    venv\Scripts\python.exe setup_deps.py
    if errorlevel 1 (
        echo ERROR: Could not download frontend libraries. Check your internet connection.
        pause
        exit /b 1
    )
)

:: Launch — prefer pythonw.exe (no console window), fall back to python.exe
if exist "venv\Scripts\pythonw.exe" (
    start "" /D "%~dp0" "venv\Scripts\pythonw.exe" main.py
) else (
    start "" /D "%~dp0" "venv\Scripts\python.exe" main.py
)
exit
