@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
set "PORT=8080"
set "BANNER_APP_ROLE=central"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Cannot find "%PYTHON_EXE%".
  echo [INFO] Create the virtual environment first, then install dependencies:
  echo        py -m venv .venv
  echo        .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

echo [INFO] Starting RBS central admin on port %PORT%...
echo [INFO] URL: http://127.0.0.1:%PORT%/admin
echo [INFO] Press Ctrl+C to stop.
echo.

start "" "http://127.0.0.1:%PORT%/admin"
set "BANNER_APP_ROLE=%BANNER_APP_ROLE%"
"%PYTHON_EXE%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload

endlocal
