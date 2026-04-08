@echo off
echo Stopping all CrawlerAI processes...

REM Kill all windows
taskkill /F /T /FI "WINDOWTITLE eq CrawlerAI Backend" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq CrawlerAI Worker" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq CrawlerAI Frontend" >nul 2>&1

REM Kill processes on ports
echo Killing processes on ports 8000 and 3000...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port = 8000; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port = 3000; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Waiting for processes to terminate...
timeout /t 2 /nobreak >nul

echo Starting CrawlerAI...
call start.bat

echo Done! All processes restarted.
