@echo off
set "AIT=D:\opc in D\AI\ai-toolkit"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%AIT%"
echo TRAIN_START %date% %time% > "%~dp0train_log.txt"
venv\Scripts\python.exe run.py "%~dp0maotai_lora_v1.yaml" >> "%~dp0train_log.txt" 2>&1
echo TRAIN_EXIT %errorlevel% %date% %time% >> "%~dp0train_log.txt"
