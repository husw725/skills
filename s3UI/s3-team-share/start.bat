@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Starting S3 Team Share App...
echo ========================================

:: Set paths
set "P_DIR=%~dp0python_win"
set "P_EXE=%~dp0python_win\python.exe"
set "P_GET_PIP=%~dp0python_win\get-pip.py"
set "P_REQ=%~dp0requirements.txt"
set "P_MARKER=%~dp0python_win\Lib\site-packages\pip"

:: 1. Verify Python executable exists
if not exist "%P_EXE%" (
    echo [ERROR] Portable Python not found at: "%P_EXE%"
    pause
    exit /b
)

:: 2. Setup pip if not present
if not exist "%P_MARKER%" (
    echo [INFO] First time setup: Initializing pip...
    "%P_EXE%" "%P_GET_PIP%" --no-warn-script-location
)

:: 3. Install required libraries
echo [INFO] Checking dependencies...
"%P_EXE%" -m pip install -r "%P_REQ%" --quiet --no-warn-script-location

:: 4. Start the application
echo [INFO] Launching UI...
"%P_EXE%" -m streamlit run app.py --server.port 8501

if %errorlevel% neq 0 (
    echo [ERROR] Application failed to start.
    pause
)
