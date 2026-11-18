@echo off
cd /d "%~dp0"
set "SRC=%~dp0..\21_LoRAÑµÁ·\output\maotai_lora_v1\maotai_lora_v1.safetensors"
if not exist "%SRC%" (echo LORA_NOT_FOUND & pause & exit /b 1)
copy /Y "%SRC%" "D:\opc in D\AI\ComfyUI\ComfyUI\models\loras\maotai_lora_v1.safetensors"
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_lora_test.json
pause
