@echo off
set "T=D:\opc in D\AI\picotoopet_tools"
if not exist "%T%" mkdir "%T%"
cd /d "%T%"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONUTF8=1
set CUDA_VISIBLE_DEVICES=
if not exist qc_venv\Scripts\python.exe uv venv --python 3.12 qc_venv > "%~dp0qc_v1_setup.txt" 2>&1
uv pip install --python qc_venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cpu >> "%~dp0qc_v1_setup.txt" 2>&1
uv pip install --python qc_venv\Scripts\python.exe "transformers>=4.45" av pillow numpy scipy >> "%~dp0qc_v1_setup.txt" 2>&1
cd /d "%~dp0"
"%T%\qc_venv\Scripts\python.exe" qc_v1.py qc_jobs_v1.json > qc_v1_console.txt 2>&1
echo QC_V1_EXIT %errorlevel% >> qc_v1_console.txt
