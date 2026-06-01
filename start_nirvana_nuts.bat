@echo off
echo.
echo ============================================================
echo   🥜 NIRVANA NUTS GROWTH ENGINE
echo   Twitter Growth ^& Engagement AI
echo   Built with love by TradeHive
echo ============================================================
echo.
echo   Starting server on http://localhost:8000
echo.

cd /d "%~dp0src\agents\nirvana_nuts"
python run_dashboard.py
pause
