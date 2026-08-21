@echo off
setlocal EnableExtensions
title PVP Director Console Setup
cd /d "%~dp0"
echo ============================================================
echo PVP Director Console Native v2 - N6E2.2 PREBUILT SETUP
echo ============================================================
echo.
echo Starting prebuilt installation. No source build will run on this PC.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-PvpDirectorConsolePrebuilt.ps1" -PackageRoot "%~dp0"
set "PVP_EXIT=%ERRORLEVEL%"
echo.
if not "%PVP_EXIT%"=="0" (
  echo ============================================================
  echo INSTALL FAILED - exit code %PVP_EXIT%
  echo This window is intentionally kept open.
  echo.
  if exist "%~dp0PVP_DIRECTOR_CONSOLE_N6E22_BOOTSTRAP.log" (
    echo Bootstrap log:
    echo %~dp0PVP_DIRECTOR_CONSOLE_N6E22_BOOTSTRAP.log
    echo ------------------------------------------------------------
    type "%~dp0PVP_DIRECTOR_CONSOLE_N6E22_BOOTSTRAP.log"
    echo ------------------------------------------------------------
  )
  echo If a PVP_DIRECTOR_CONSOLE_N6E22_INSTALL_RESULT_*.zip exists,
  echo send that ZIP back for diagnosis.
  echo ============================================================
  if /I not "%PVP_INSTALLER_CI%"=="1" pause
) else (
  echo Installation completed successfully.
)
exit /b %PVP_EXIT%
