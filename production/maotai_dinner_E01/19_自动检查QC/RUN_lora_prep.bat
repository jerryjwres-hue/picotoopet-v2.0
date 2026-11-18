@echo off
start "FLUX_LORA_DATASET" /D "D:\opc in D\LTX\电影项目\茅台晚餐_连续性V2\17_静态首帧板V2" cmd /c ""D:\opc in D\AI\ComfyUI\standalone-env\python.exe" run_flux_board.py jobs_lora_dataset.json"
start "AITOOLKIT_INSTALL" /D "D:\opc in D\LTX\电影项目\茅台晚餐_连续性V2\21_LoRA训练" cmd /c install_ai_toolkit.bat
