@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo [PicotooPet QC] Running Auto Quality Control Self-Check
echo =======================================================

cd /d "%~dp0"

:: Check virtual environment
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Using Python: !PYTHON_EXE!
echo.

:: Generate on-the-fly synthetic assets for self-check (solid/geometric mock, sine audio)
echo [1/3] Generating mock test assets in temporary folder...
!PYTHON_EXE! -c "import cv2, json, numpy as np; img = np.full((960, 540, 3), 120, dtype=np.uint8); cv2.ellipse(img, (270, 320), (100, 140), 0, 0, 360, (35, 35, 35), -1); cv2.circle(img, (270, 240), 70, (45, 45, 45), -1); cv2.ellipse(img, (270, 250), (45, 55), 0, 0, 360, (230, 230, 230), -1); cv2.ellipse(img, (270, 780), (80, 40), 0, 0, 360, (0, 220, 255), -1); cv2.imwrite('mock_shot.png', img); ref = img[180:460, 170:370]; cv2.imwrite('mock_ref.png', ref); spec = {'shot_id':'S01','expect':{'dogs':1,'people':0,'bowls':1,'faces_visible':False},'identity_refs':{'dog':'mock_ref.png'},'min_motion':0.0,'max_motion':5.0,'caption':{'text':'Maotai lunchtime','y_ratio':0.20},'allow_light_change':False}; open('mock_spec.json','w',encoding='utf-8').write(json.dumps(spec,indent=2))"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to generate mock assets.
    exit /b 2
)

echo.
echo [2/3] Running QC check command:
echo python -m qc check --spec mock_spec.json --media mock_shot.png --out report.json
echo.

!PYTHON_EXE! -m qc check --spec mock_spec.json --media mock_shot.png --out report.json
set "QC_EXIT=%ERRORLEVEL%"

echo.
echo =======================================================
echo [3/3] Execution finished with exit code: %QC_EXIT%
if exist "report.json" (
    echo --- Content of report.json ---
    type report.json
    echo ------------------------------
)
if exist "report.jpg" (
    echo Visual report collage generated at: report.jpg
)
echo =======================================================

:: Clean temporary mock assets
del /q mock_shot.png mock_ref.png mock_spec.json 2>nul

if %QC_EXIT% equ 0 (
    echo [RESULT] QC PASSED (Exit 0)
    goto end
)
if %QC_EXIT% equ 1 (
    echo [RESULT] QC FAILED Checks (Exit 1)
    goto end
)
echo [RESULT] QC PROGRAM ERROR (Exit %QC_EXIT%)

:end
pause
exit /b %QC_EXIT%
