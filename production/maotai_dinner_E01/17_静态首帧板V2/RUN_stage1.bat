@echo off
cd /d "%~dp0"
echo PicotooPet FLUX keyframe board - stage 1
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_stage1.json
echo.
echo Finished. You can close this window.
pause
