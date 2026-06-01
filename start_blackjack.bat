@echo off
echo.
echo ============================================================
echo   ♠♣ BLACKJACK ADVISOR DASHBOARD ♥♦
echo   Professional Card Counting ^& Strategy
echo   Built with love by TradeHive
echo ============================================================
echo.
echo   Starting server on http://localhost:8000
echo.

cd /d "%~dp0src\agents\blackjack\web_dashboard"
python run_dashboard.py
pause
