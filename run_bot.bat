@echo off
chcp 65001 >nul

echo ========================================
echo   Trading Automation Bot
echo ========================================
echo.

if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

echo ^[OK^] Starting bot...
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0run_bot.ps1"
