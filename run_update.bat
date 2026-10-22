@echo off
cd /d "%~dp0"
if not exist data mkdir data
set PYTHONIOENCODING=utf-8
python fin_update.py >> data\update_log.txt 2>&1
if errorlevel 1 py fin_update.py >> data\update_log.txt 2>&1
