@echo off
REM ============================================================
REM  Crowio AI - FINISH the merge and push
REM  Run this ONCE after Claude resolved the README conflict.
REM  Do NOT run "Push to GitHub.bat" again - it would reset the
REM  merge and recreate the conflict. Use THIS file instead.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Crowio AI: finishing the merge and pushing ===
echo.

REM --- make sure we're actually in a git repo ---
if not exist ".git" (
    echo [ERROR] No .git folder here. Run "Push to GitHub.bat" first.
    pause
    exit /b 1
)

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

REM --- complete the merge commit (uses the default merge message) ---
git commit --no-edit

echo.
echo === Pushing to GitHub ===
echo A browser or credential prompt may appear - sign in to GitHub if asked.
echo.
git push -u origin main

echo.
if errorlevel 1 (
    echo [!] Push did not complete. See the message above and tell Claude.
) else (
    echo Done. Your code is live at https://github.com/Blankcmd/Crowio-AI
)
echo.
pause
endlocal
