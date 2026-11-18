@echo off
cd /d "%~dp0"
set "PYTHONPATH=D:\opc in D\AI\ComfyUI\ComfyUI\.venv\Lib\site-packages"
set CUDA_VISIBLE_DEVICES=
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" qc_v0.py qc_jobs_S2.json >> qc_console.txt 2>&1
echo done >> qc_console.txt
