@echo off
echo Cleaning up integration documentation files...
echo.

:: List files to delete that were created during integration
echo Deleting .md files created during integration...
del /Q "C:\Users\satya\OneDrive\Documents\AI Projects\tradehive-ai-agents\CRITICAL_GAPS_BEFORE_DRYRUN.md"
del /Q "C:\Users\satya\OneDrive\Documents\AI Projects\tradehive-ai-agents\INTEGRATION_STATUS.md"
del /Q "C:\Users\satya\OneDrive\Documents\AI Projects\tradehive-ai-agents\V2_INTEGRATION_PLAN.md"
del /Q "C:\Users\satya\OneDrive\Documents\AI Projects\tradehive-ai-agents\V2_INTEGRATION_COMPLETE.md"
del /Q "C:\Users\satya\OneDrive\Documents\AI Projects\tradehive-ai-agents\CURRENT_STATUS.md"

echo Deleting .txt files created during integration...
del /Q "C:\Users\satya\OneDrive\Documents\AI Projects\tradehive-ai-agents\ENHANCED_SYSTEM_SUMMARY.txt"

echo.
echo Remaining documentation files (kept):
echo - CLAUDE.md (original project docs)
echo - README.md (original project docs)
echo - API_READINESS_REPORT.md (original project docs)
echo - requirements.txt (original dependencies)
echo.
echo Cleanup complete!
