@echo off
set "T=D:\opc in D\AI\picotoopet_tools"
if not exist "%T%" mkdir "%T%"
cd /d "%T%"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONUTF8=1
set CUDA_VISIBLE_DEVICES=
if not exist tts_venv\Scripts\python.exe uv venv --python 3.12 tts_venv > "%~dp0tts_setup.txt" 2>&1
uv pip install --python tts_venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cpu >> "%~dp0tts_setup.txt" 2>&1
uv pip install --python tts_venv\Scripts\python.exe kokoro soundfile pip >> "%~dp0tts_setup.txt" 2>&1
cd /d "%~dp0"
"%T%\tts_venv\Scripts\python.exe" tts_vo.py > tts_console.txt 2>&1
echo TTS_EXIT %errorlevel% >> tts_console.txt
