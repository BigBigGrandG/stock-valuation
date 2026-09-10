@echo off
setlocal

set "PROJECT_ROOT=%~dp0"

start "Stock Valuation Backend" /D "%PROJECT_ROOT%backend" cmd /d /k "..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8002"
start "Stock Valuation Frontend" /D "%PROJECT_ROOT%frontend" cmd /d /k "npm run dev"

for /l %%i in (1,1,30) do (
    powershell -NoProfile -Command "try { $null = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3000' -TimeoutSec 1; exit 0 } catch { exit 1 }"
    if not errorlevel 1 goto :open_browser
    timeout /t 1 /nobreak >nul
)

:open_browser
start "" "http://localhost:3000"

endlocal
