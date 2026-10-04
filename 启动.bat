@echo off
chcp 65001 >nul
cd /d "%~dp0"
python rag_multi_user.py
echo.
echo [Server stopped] Press any key to exit.
pause
