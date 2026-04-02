@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

start "CrawlerAI Backend" cmd /k "cd /d ""%ROOT%backend"" && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "CrawlerAI Worker" cmd /k "cd /d ""%ROOT%backend"" && python -m app.workers"
start "CrawlerAI Frontend" cmd /k "cd /d ""%ROOT%frontend"" && npm run dev"

endlocal
