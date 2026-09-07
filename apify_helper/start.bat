@echo off
REM Short Drama Data Console - start script (Windows)
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist config.json copy config.example.json config.json >nul
python -m pip install -r requirements.txt -q --disable-pip-version-warning
if errorlevel 1 (
  echo [ERROR] pip install failed. Check network / proxy, then run start.bat again.
  pause
  exit /b 1
)
echo Starting... keep this window open. Close it (or Ctrl+C) to stop the service.
python app.py
pause
