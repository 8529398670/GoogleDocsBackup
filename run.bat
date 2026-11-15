@echo off
cd /d "%~dp0"
python python\backup.py run %*
pause
