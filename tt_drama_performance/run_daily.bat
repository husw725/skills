@echo off
rem TikTok Drama Daily Report - scheduled task entry (installed by install.bat)
cd /d %~dp0
rem pull latest code/data first so all machines stay in sync
git pull --rebase --autostash >> daily_update.log 2>&1
.venv\Scripts\python daily_update.py >> daily_update.log 2>&1
