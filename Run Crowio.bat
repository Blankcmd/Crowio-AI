@echo off
REM ============================================================
REM  Crowio AI - one-click launcher
REM  Auto-elevates to Administrator, sets up venv, launches UI.
REM ============================================================

REM --- Step 1: relaunch elevated if we are not already admin ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM --- Step 2: move into the folder this script lives in ---
cd /d "%~dp0"

echo ============================================================
echo   CROWIO AI  -  autonomous desktop agent
echo ============================================================
echo.

REM --- Step 3: create a virtual environment on first run ---
if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo.
        echo ERROR: could not create the virtual environment.
        echo Make sure Python 3.10+ is installed and on your PATH.
        echo Get it from https://www.python.org/downloads/
        echo.
        pause
        exit /b
    )
    echo Installing dependencies ^(one time, takes a minute^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    echo.
)

REM --- Step 4: launch the UI ---
echo Launching Crowio AI...
echo.
".venv\Scripts\python.exe" crowio_ui.py

REM --- Keep window open if the app crashes so you can read the error ---
if %errorlevel% neq 0 (
    echo.
    echo Crowio exited with an error. See the message above.
    pause
)
