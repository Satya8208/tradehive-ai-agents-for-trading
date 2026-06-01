@echo off
echo.
echo 🥜 NIRVANA NUTS DASHBOARD
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

cd /d "%~dp0"

REM Check if node_modules exists
if not exist "frontend\node_modules" (
    echo 📦 Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

echo.
echo 🚀 Starting servers...
echo    Backend:  http://localhost:8000
echo    Frontend: http://localhost:3000
echo.
echo    Press Ctrl+C in each window to stop
echo.

REM Start backend in new window
start "Nirvana Nuts Backend" cmd /k "cd /d %~dp0..\.. && python -m uvicorn src.dashboard.backend.api:app --reload --port 8000"

REM Wait a bit
timeout /t 2 /nobreak > nul

REM Start frontend in new window
start "Nirvana Nuts Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

REM Wait and open browser
timeout /t 3 /nobreak > nul
start http://localhost:3000

echo.
echo ✅ Dashboard is running!
echo    Close the terminal windows to stop the servers.
echo.
pause
