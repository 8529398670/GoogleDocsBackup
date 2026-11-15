@echo off
cd /d "%~dp0"

set COUNT=0
for /f %%i in ('git rev-list --count HEAD 2^>nul') do set COUNT=%%i
set /a NEXT=COUNT+1

git add -A
git diff --cached --quiet
if %errorlevel%==0 (
  echo No changes to commit - commit %COUNT% is already the latest.
) else (
  git commit -q -m "%NEXT%"
  echo Committed "%NEXT%".
)

git push -q
if %errorlevel%==0 (
  echo GitHub is up to date.
) else (
  echo PUSH FAILED - see the error above.
)
