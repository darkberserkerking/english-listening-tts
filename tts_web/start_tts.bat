@echo off
chcp 65001 >nul
cd /d "%~dp0"
title TTS Web Server
echo.
echo   Starting TTS web server...
echo.
python app.py
echo.
echo   Server stopped. Press any key to close.
pause >nul
