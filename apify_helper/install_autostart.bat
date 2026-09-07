@echo off
REM Run ONCE as Administrator: registers auto-start at logon and opens the firewall port for LAN access.
cd /d "%~dp0"
set PORT=8765
schtasks /Create /F /TN "ShortDramaDataConsole" /SC ONLOGON /RL LIMITED /TR "\"%~dp0start.bat\""
if errorlevel 1 (
  echo [WARN] Could not create scheduled task. Right-click this file and choose "Run as administrator".
) else (
  echo [OK] Auto-start registered: task "ShortDramaDataConsole" runs start.bat at every logon.
)
netsh advfirewall firewall add rule name="ShortDramaDataConsole %PORT%" dir=in action=allow protocol=TCP localport=%PORT% >nul
if errorlevel 1 (
  echo [WARN] Firewall rule not added. LAN users may not be able to connect until port %PORT% is allowed.
) else (
  echo [OK] Firewall: inbound TCP %PORT% allowed.
)
echo.
echo To remove:  schtasks /Delete /F /TN "ShortDramaDataConsole"
echo             netsh advfirewall firewall delete rule name="ShortDramaDataConsole %PORT%"
pause
