@echo off
REM Registers a daily 09:10 Windows Task Scheduler job that refreshes the finance data.
cd /d "%~dp0"
if not exist data mkdir data
schtasks /create /tn "FinanceDataDailyUpdate" /tr "\"%~dp0run_update.bat\"" /sc daily /st 09:10 /f
echo.
echo Registered. Running once now...
call "%~dp0run_update.bat"
echo Done. Check data\update_log.txt
pause
