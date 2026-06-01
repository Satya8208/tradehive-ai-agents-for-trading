@echo off
set PYTHONUTF8=1
echo.
echo ============================================================
echo   POKER GOD LIVE ADVISOR
echo   Fast terminal coach for live Hold'em sessions
echo   Built with love by TradeHive
echo ============================================================
echo.
echo   Launching interactive advisor...
echo.

cd /d "%~dp0"
python -X utf8 src\agents\poker\live_advisor.py
pause
