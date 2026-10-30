@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start-IosSweet-Docker.ps1" -Interactive
if errorlevel 1 (
  echo.
  echo Docker Desktop or private iOS guest files need attention. See above.
  pause
)
