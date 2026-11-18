@echo off
cd /d "%~dp0"
call RUN_qc_v1.bat
call RUN_tts.bat
echo ALL_CPU_TASKS_DONE > cpu_tasks_done.txt
