@echo off
cd /d "%~dp0"
set "PYTHONPATH=D:\opc in D\AI\ComfyUI\ComfyUI\.venv\Lib\site-packages"
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" qc_v0.py qc_jobs_all.json >> qc_console.txt 2>&1
echo done_all >> qc_console.txt
