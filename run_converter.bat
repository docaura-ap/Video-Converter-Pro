@echo off
cd /d "%~dp0"

:: ── Create venv if missing ──────────────────────────────────────────────────
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Python not found. Please install Python 3.10 or newer.
        pause
        exit /b 1
    )
)

:: ── Install dependencies if needed ─────────────────────────────────────────
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

:: ── Download frontend libraries if missing (one-time) ──────────────────────
if not exist "frontend\lib\react.production.min.js" (
    echo Downloading frontend libraries ^(one-time setup^)...
    venv\Scripts\python.exe setup_deps.py
    if errorlevel 1 (
        echo ERROR: Could not download frontend libraries. Check your internet connection.
        pause
        exit /b 1
    )
)

:: ── Launch app ──────────────────────────────────────────────────────────────
if exist "venv\Scripts\pythonw.exe" (
    start "" /D "%~dp0" "venv\Scripts\pythonw.exe" main.py
) else (
    start "" /D "%~dp0" "venv\Scripts\python.exe" main.py
)
exit
