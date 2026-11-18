@echo off
cd /d "%~dp0"
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_char_v2.json
pause
