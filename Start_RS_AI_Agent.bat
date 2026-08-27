@echo off
title RS AI Agent Platform
echo ============================================================
echo   Starting RS AI Agent Platform...
echo ============================================================
cd /d "%~dp0"
start http://localhost:8000
py run.py
if %ERRORLEVEL% NEQ 0 (
    python run.py
)
pause
