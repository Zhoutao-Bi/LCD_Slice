@echo off
cd /d "%~dp0"
if exist "dist-v0.1.2\LumaSlice\LumaSlice.exe" (
    start "" "dist-v0.1.2\LumaSlice\LumaSlice.exe"
    exit /b
)
if exist "dist-v0.1.1\LumaSlice\LumaSlice.exe" (
    start "" "dist-v0.1.1\LumaSlice\LumaSlice.exe"
    exit /b
)
if exist "dist\LumaSlice\LumaSlice.exe" (
    start "" "dist\LumaSlice\LumaSlice.exe"
    exit /b
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Please install Python 3.11+ and run: python -m venv .venv
    echo Then run: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "run.py"
