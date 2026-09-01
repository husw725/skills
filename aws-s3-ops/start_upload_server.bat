@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   HTML Share Upload Server (S3)
echo ========================================

if not exist "scripts\.s3creds" (
    echo [ERROR] scripts\.s3creds not found! Create it first: two hex lines, AK then SK.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3 first.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Initializing local environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Checking dependencies...
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple boto3 --quiet

start "" http://localhost:8000
python scripts\upload_server.py 8000
pause
