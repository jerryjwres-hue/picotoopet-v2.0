@echo off
cd /d "%~dp0"
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_stage3.json
pause
