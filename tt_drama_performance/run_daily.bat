@echo off
rem TikTok 短剧日报 - Windows 定时任务入口
rem 修改下面这行为你本机的仓库路径
cd /d %~dp0
python daily_update.py --push >> daily_update.log 2>&1
