@echo off
REM =========================================================
REM  Gain Map JPEG Tool - Setup script (Windows)
REM
REM  Run once, on first install. Double-click this file or
REM  run from cmd.exe:
REM    setup.bat
REM
REM  After that, use run.bat to start the app.
REM =========================================================

cd /d "%~dp0"

echo.
echo ==========================================
echo  Gain Map JPEG Tool - Setup
echo ==========================================
echo.

REM --- Check Python ---

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo.
    echo Download Python 3.11 or newer from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: When installing, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Found Python %PYTHON_VERSION%

REM --- Check exiftool ---

where exiftool >nul 2>nul
if errorlevel 1 (
    echo.
    echo WARNING: exiftool is not installed. The app will not work without it.
    echo.
    echo Download the Windows executable from:
    echo   https://exiftool.org/
    echo.
    echo Rename "exiftool(-k).exe" to "exiftool.exe" and place it
    echo somewhere on your PATH (e.g. C:\Windows).
    echo.
    set /p CONT="Continue anyway? (y/N) "
    if /i not "%CONT%"=="y" exit /b 1
) else (
    for /f %%v in ('exiftool -ver') do set EXIFTOOL_VERSION=%%v
    echo Found exiftool %EXIFTOOL_VERSION%
)

REM --- Create virtual environment ---

if exist venv (
    echo.
    echo Virtual environment already exists. Skipping creation.
) else (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM --- Install dependencies ---

echo.
echo Installing Python dependencies (this can take a minute)...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Setup complete!
echo ==========================================
echo.
echo To start the app, double-click run.bat
echo.
pause
