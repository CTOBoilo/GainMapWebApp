@echo off
REM =========================================================
REM  Gain Map JPEG Tool - Start the app (Windows)
REM
REM  Double-click this file to launch the app, then open
REM  http://127.0.0.1:5000 in your browser.
REM =========================================================

cd /d "%~dp0"

if not exist venv (
    echo ERROR: virtual environment not found.
    echo Run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo Starting Gain Map JPEG Tool...
echo Open your browser at http://127.0.0.1:5000 (or 5001)
echo Press Ctrl+C to stop.
echo.

python app.py

pause
