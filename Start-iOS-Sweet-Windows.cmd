@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start-IosSweet-Windows.ps1"
if errorlevel 1 (
  echo.
  echo Native Windows startup was blocked. See the reason above.
  echo The existing Docker guest and private iOS disk were not changed.
  pause
  exit /b 1
)
exit /b 0
