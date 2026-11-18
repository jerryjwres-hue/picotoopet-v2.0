@echo off
cd /d "%~dp0"
echo PicotooPet LoRA dataset stills (FLUX, 36 images)
"D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_lora_dataset.json
pause
