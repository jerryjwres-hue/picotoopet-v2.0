@echo off
setlocal

echo ========================================================
echo [PicotooPet QC] Initializing Isolated Python 3.12 Venv
echo ========================================================

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment at .venv ...
    python -m venv .venv
)

echo Activating .venv and installing requirements...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Setup completed successfully!
pause
