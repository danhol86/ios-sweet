@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start-IosSweet-Docker.ps1" -Interactive
if errorlevel 1 (
  echo.
  echo Docker setup needs attention. See the message above.
  pause
)
