@echo off
cd /d "%~dp0"
echo PicotooPet FLUX keyframe board - stage 2
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_stage2.json
echo.
echo Finished. You can close this window.
pause
