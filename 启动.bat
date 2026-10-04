@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   多用户 RAG 知识库问答系统 - 本地启动
echo ============================================
echo.
python rag_multi_user.py
echo.
echo 服务已停止。
pause
