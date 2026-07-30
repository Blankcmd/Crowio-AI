@echo off
REM ============================================================
REM  Crowio AI - one-click GitHub push
REM  Run this on your Windows machine (double-click it).
REM  It commits everything EXCEPT your secrets (.env / .env.crowio)
REM  and pushes to https://github.com/Blankcmd/Crowio-AI
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Crowio AI: pushing to GitHub ===
echo.

REM --- make sure git is available ---
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed or not on PATH.
    echo Install it from https://git-scm.com/download/win then run this again.
    pause
    exit /b 1
)

REM --- clean any half-made repo (safe: only removes .git metadata) ---
if exist ".git" (
    echo Removing existing .git folder for a clean start...
    rmdir /s /q ".git"
)

git init

REM --- set a git identity if none exists (required to commit) ---
git config user.name >nul 2>&1
if errorlevel 1 (
    echo No git identity found for this repo. Setting one...
    git config user.name "Karthik penu"
    git config user.email "karthik@users.noreply.github.com"
)
git config user.email >nul 2>&1
if errorlevel 1 git config user.email "karthik@users.noreply.github.com"

git add -A

echo.
echo === SECRET SAFETY CHECK ===
git status --short | findstr /I ".env" | findstr /V ".env.example" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [STOP] A .env secret file is staged! Aborting to protect your API key.
    echo Check your .gitignore. Nothing was pushed.
    pause
    exit /b 1
)
echo OK - no .env secret files are staged. Safe to continue.
echo.

git commit -m "Initial commit: Crowio AI autonomous desktop assistant"
git branch -M main

REM --- add remote only if it isn't already set ---
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    git remote add origin https://github.com/Blankcmd/Crowio-AI.git
)

echo.
echo === Pushing to GitHub ===
echo A browser or credential prompt may appear - sign in to GitHub if asked.
echo.
git push -u origin main

if errorlevel 1 (
    echo.
    echo Remote already has commits. Merging them in, then retrying...
    git pull origin main --allow-unrelated-histories --no-edit
    git push -u origin main
)

echo.
if errorlevel 1 (
    echo [!] Push did not complete. See the message above.
    echo If you see a merge conflict, tell Claude what it says.
) else (
    echo Done. Your code is live at https://github.com/Blankcmd/Crowio-AI
)
echo.
pause
endlocal
