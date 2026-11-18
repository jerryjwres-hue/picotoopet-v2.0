@echo off
cd /d "%~dp0"
(
echo === where
where git python conda uv 2^>^&1
echo === conda paths
dir /b "%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3" 2^>^&1
echo === disks
wmic logicaldisk get caption,freespace,size
echo === gpu
nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
echo === ram
wmic computersystem get totalphysicalmemory
echo === hf cache
dir "%USERPROFILE%\.cache\huggingface\hub"
) > diag.txt 2^>^&1
