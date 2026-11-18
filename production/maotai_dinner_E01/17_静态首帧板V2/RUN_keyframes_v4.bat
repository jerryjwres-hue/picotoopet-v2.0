@echo off
set "LOG=%~dp0..\24_³¡¾°°ü\blender_install_log.txt"
echo INSTALL_START %date% %time% > "%LOG%"
where winget >> "%LOG%" 2>&1
winget install --id BlenderFoundation.Blender -e --silent --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
echo INSTALL_EXIT %errorlevel% >> "%LOG%"
