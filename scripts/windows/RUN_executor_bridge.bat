@echo off
setlocal
if "%~1"=="" (
    py -3 "%~dp0executor_bridge.py"
) else (
    py -3 "%~dp0executor_bridge.py" "%~1"
)
exit /b %ERRORLEVEL%
