@echo off
rem Double-click to start the Accrual Workbook and open it in your browser.
rem Keep this window open while you use the app; closing it stops the app.
title Accrual Workbook
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python packages. This takes a minute...
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH", then double-click this file again.
    pause
    exit /b 1
  )
  python -m venv .venv || (echo Could not create the Python environment. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo Package install failed. & pause & exit /b 1)
)

if not exist "data\sample\gl_detail.csv" ".venv\Scripts\python.exe" scripts\make_sample_data.py

echo Starting the Accrual Workbook at http://localhost:5000
echo Keep this window open while you use the app. Close it to stop.
start "" cmd /c "timeout /t 3 >nul & start http://localhost:5000"
".venv\Scripts\python.exe" -m accrual_workbook serve
pause
