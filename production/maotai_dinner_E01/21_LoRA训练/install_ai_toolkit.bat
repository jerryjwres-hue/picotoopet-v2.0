@echo off
setlocal
set "AIT=D:\opc in D\AI\ai-toolkit"
set "LOG=%~dp0install_log.txt"
echo START %date% %time% > "%LOG%"
if not exist "%AIT%\run.py" git clone https://github.com/ostris/ai-toolkit.git "%AIT%" >> "%LOG%" 2>&1
cd /d "%AIT%"
git log -1 --format="AIT_COMMIT %%h %%ci" >> "%LOG%" 2>&1
if not exist venv\Scripts\python.exe uv venv --python 3.12 venv >> "%LOG%" 2>&1
uv pip install --python venv\Scripts\python.exe torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130 >> "%LOG%" 2>&1
uv pip install --python venv\Scripts\python.exe -r requirements.txt >> "%LOG%" 2>&1
venv\Scripts\python.exe -c "import torch;print('TORCH',torch.__version__,torch.cuda.is_available(),torch.cuda.get_device_name(0))" >> "%LOG%" 2>&1
echo DOWNLOAD_BASE %time% >> "%LOG%"
venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download;p=snapshot_download('black-forest-labs/FLUX.2-klein-base-4B');print('BASE_OK',p)" >> "%LOG%" 2>&1
echo INSTALL_DONE %date% %time% >> "%LOG%"
