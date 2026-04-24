:: MultiViewSyncPlayer Windows 一键安装脚本
:: 功能：检测 Python → 创建 venv → pip 安装 → 首次启动
:: 生成时间：2026-04-24
@echo off
chcp 65001 >nul

echo ============================================
echo   MultiViewSyncPlayer 安装脚本
echo ============================================
echo.

:: 检测 Python
where python >nul 2>&1 || (
    echo [错误] 未检测到 Python，请先安装 Python >= 3.9
    echo 按任意键打开 Python 下载页...
    pause >nul
    start https://www.python.org/downloads/
    exit /b 1
)

:: 检测版本
python -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" || (
    echo [错误] Python 版本低于 3.9，请升级。
    pause
    exit /b 1
)

:: 创建 venv
if not exist .venv (
    echo [1/3] 创建虚拟环境...
    python -m venv .venv
) else (
    echo [1/3] 虚拟环境已存在，跳过。
)

call .venv\Scripts\activate.bat

:: 升级 pip
echo [2/3] 升级 pip...
python -m pip install --upgrade pip -q

:: 安装依赖
echo [3/3] 安装依赖...
pip install -r requirements.txt -q

echo.
echo ============================================
echo   [完成] 安装完毕！
echo   启动命令：call .venv\Scripts\activate ^&^& python run.py
echo ============================================
echo.

choice /C YN /M "是否现在启动？(Y/N)"
if errorlevel 2 exit /b 0
python run.py
