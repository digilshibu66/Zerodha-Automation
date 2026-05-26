@echo off
chcp 65001 >nul

echo ========================================
echo   OpenClaw Trading Automation Setup
echo ========================================
echo.

where openclaw >nul 2>nul
if %ERRORLEVEL% equ 0 (
    for /f "tokens=*" %%i in ('openclaw --version 2^>nul') do echo ^[OK^] OpenClaw already installed ^(%%i^)
) else (
    echo ^[INFO^] OpenClaw not found -- will install via PowerShell
)
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup.ps1"
