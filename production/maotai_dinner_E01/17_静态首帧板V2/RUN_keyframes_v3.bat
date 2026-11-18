@echo off
cd /d "%~dp0"
copy /Y "%~dp0..\21_LoRAÑµÁ·\output\maotai_lora_v2\maotai_lora_v2.safetensors" "D:\opc in D\AI\ComfyUI\ComfyUI\models\loras\maotai_lora_v2.safetensors"
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_keyframes_v3.json
pause
