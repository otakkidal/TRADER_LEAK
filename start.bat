@echo off
cd /d "%~dp0"
echo ========================================
echo SMC GOLD FULL AUTO - FIXED FINAL
echo Lokasi: %CD%
echo ========================================
echo.

if not exist requirements.txt (
    echo ERROR: requirements.txt tidak ada!
    pause
    exit /b
)

echo [1] Cek Python...

if exist ".venv\Scripts\python.exe" goto PAKAI_VENV
goto PAKAI_GLOBAL

:PAKAI_VENV
echo Pakai .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo [2] Starting...
".venv\Scripts\python.exe" main_gold_auto.py
goto END

:PAKAI_GLOBAL
echo Pakai python global
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo [2] Starting...
python main_gold_auto.py
goto END

:END
echo.
pause
