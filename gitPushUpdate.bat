@echo off
cd /d "%~dp0"

set COUNT=0
for /f %%i in ('git rev-list --count HEAD 2^>nul') do set COUNT=%%i
set /a NEXT=COUNT+1

git add -A
git commit -m "%NEXT%"
git push