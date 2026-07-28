@echo off
rem TikTok Drama Daily Report - scheduled task entry (installed by install.bat)
cd /d %~dp0
.venv\Scripts\python daily_update.py --push >> daily_update.log 2>&1
