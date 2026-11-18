@echo off
setlocal

echo ==========================================================
echo [PicotooPet Edit] Running Auto Assembly and Edit Self-Check
echo ==========================================================

cd /d "%~dp0"

:: Check virtual environment
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Using Python: %PYTHON_EXE%
echo.

:: Generate on-the-fly synthetic assets for self-check
echo [1/3] Generating synthetic mock shots and audio...
%PYTHON_EXE% _generate_mock_assets.py
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to generate mock assembly assets.
    exit /b 2
)

echo.
echo [2/3] Running assembly command:
echo python -m edit assemble --plan mock_plan.json --out final.mp4
echo.

%PYTHON_EXE% -m edit assemble --plan mock_plan.json --out final.mp4
set "EDIT_EXIT=%ERRORLEVEL%"

echo.
echo ==========================================================
echo [3/3] Assembly finished with exit code: %EDIT_EXIT%
if exist "edl.txt" (
    echo --- Content of edl.txt ---
    type edl.txt
    echo --------------------------
)
if exist "strip.jpg" (
    echo Thumbnail filmstrip generated at: strip.jpg
)
if exist "final.mp4" (
    echo Master final video assembled at: final.mp4
)
echo ==========================================================

:: Clean temporary mock assets
del /q mock_s01.mp4 mock_s02.mp4 mock_music.wav mock_foley.flac mock_plan.json 2>nul

if %EDIT_EXIT% equ 0 (
    echo [RESULT] EDIT ASSEMBLE SUCCESS (Exit 0)
    goto end
)
echo [RESULT] EDIT ASSEMBLE FAILED (Exit %EDIT_EXIT%)

:end
pause
exit /b %EDIT_EXIT%
