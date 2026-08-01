@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Phase2Windows.ps1" %*
exit /b %errorlevel%
