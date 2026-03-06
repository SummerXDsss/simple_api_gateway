@echo off
chcp 65001 >nul
title Local AI API Gateway

echo.
echo  ╔══════════════════════════════════════╗
echo  ║      Local AI API Gateway            ║
echo  ║      正在启动服务...                  ║
echo  ╚══════════════════════════════════════╝
echo.

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 检查虚拟环境是否存在
if not exist ".venv\Scripts\uvicorn.exe" (
    echo [错误] 未找到虚拟环境，请先执行：
    echo.
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: 确保 data 目录存在
if not exist "data" mkdir data

echo [信息] 服务地址：http://127.0.0.1:8000
echo [信息] 管理界面：http://127.0.0.1:8000/
echo [信息] 按 Ctrl+C 停止服务
echo.

.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000

echo.
echo [信息] 服务已停止。
pause
