@echo off
REM One-command setup + launch for the Box Office vs. Ratings dashboard.
REM First run: creates a virtual environment and installs dependencies.
REM Every run after that: starts the app immediately.
REM Requires: Python 3.10+ on PATH. No database needed (bundled CSV fallback).

cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv || goto :error
)

call venv\Scripts\activate.bat

echo Installing dependencies (fast if already installed)...
pip install -r requirements.txt -q || goto :error

echo.
echo Starting the dashboard at http://127.0.0.1:8050  (Ctrl+C to stop)
start "" http://127.0.0.1:8050
python app.py
goto :eof

:error
echo.
echo Setup failed. Check that Python 3.10+ is installed and on PATH.
pause
