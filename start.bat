@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

call :kill_window "CrawlerAI Backend"
call :kill_window "CrawlerAI Worker"
call :kill_window "CrawlerAI Frontend"

call :kill_port 8000
call :kill_port 3000

start "CrawlerAI Backend" cmd /k "cd /d ""%ROOT%backend"" && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "CrawlerAI Worker" cmd /k "cd /d ""%ROOT%backend"" && python -m app.workers"
start "CrawlerAI Frontend" cmd /k "cd /d ""%ROOT%frontend"" && npm run dev"

endlocal
goto :eof

:kill_window
taskkill /F /T /FI "WINDOWTITLE eq %~1" >nul 2>&1
exit /b 0

:kill_port
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$port = %~1; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0
