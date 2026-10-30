@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Install-IosSweet-Windows.ps1" -Interactive
if errorlevel 1 (
  echo.
  echo Setup needs attention. See the message above.
  pause
)
