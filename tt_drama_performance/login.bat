@echo off
rem Check login status; if not logged in, opens a browser window for you to log in.
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo venv not found - run install.bat first.
  pause & exit /b 1
)
.venv\Scripts\python daily_update.py --login
pause
