@echo off
rem TikTok Drama Daily Report - one-shot installer
rem Run once after git clone: installs env, logs in, first run, schedules 15:00 daily task.
chcp 65001 >nul
cd /d %~dp0

echo [1/5] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.9+ from https://www.python.org/downloads/ ^(check "Add to PATH"^), then re-run this script.
  pause & exit /b 1
)

echo [2/5] Creating venv + installing dependencies...
python -m venv .venv || (echo venv failed & pause & exit /b 1)
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet playwright openpyxl || (echo pip install failed & pause & exit /b 1)
rem No browser download: uses your installed Google Chrome (browser_channel=chrome in config.json).

if not exist config.json (
  copy config.example.json config.json >nul
  echo NOTE: config.json created - edit it to set your DingTalk webhook ^(optional^).
)

echo [3/5] First-time login: a browser window will open. Log in to tiktokdramacenter.com ^(waits up to 5 min^)...
.venv\Scripts\python daily_update.py --login
if errorlevel 1 (echo Login not completed - re-run install.bat to retry. & pause & exit /b 2)

echo [4/5] First full run ^(export + report + git push^)...
.venv\Scripts\python daily_update.py
if errorlevel 1 echo WARNING: first run had errors ^(see messages above^). Task will still be scheduled; fix and test with run_daily.bat.

echo [5/5] Creating daily task at 15:00...
schtasks /create /f /tn "TTDramaDaily" /tr "\"%~dp0run_daily.bat\"" /sc daily /st 15:00
if errorlevel 1 (echo schtasks failed - open PowerShell as Administrator and re-run install.bat & pause & exit /b 3)
rem If the PC was off at 15:00, run the missed task on next boot
powershell -NoProfile -Command "Set-ScheduledTask -TaskName TTDramaDaily -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable)" >nul 2>&1

echo.
echo DONE. Daily update runs at 15:00. Log: daily_update.log
echo Manual test anytime: schtasks /run /tn TTDramaDaily
pause
