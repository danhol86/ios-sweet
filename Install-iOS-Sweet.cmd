@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start-IosSweet-Docker.ps1" -Interactive
if errorlevel 1 goto install_error
exit /b 0
:install_error
echo.
echo Setup did not finish. Follow the error above, then double-click this same installer to retry without losing cached downloads.
pause
exit /b 1
