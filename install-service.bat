@echo off
rem Windows installer: .venv + package + scheduled task (Task Scheduler).
rem   install-service.bat             install / update
rem   install-service.bat uninstall   remove the scheduled task
cd /d "%~dp0"

rem A SYSTEM task needs admin - re-launch elevated if we aren't.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Asking for admin rights...
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '%~1'"
  )
  exit /b
)

if /i "%~1"=="uninstall" (
  .venv\Scripts\python.exe -m google_docs_backup service uninstall
  goto :done
)

if not exist .venv\Scripts\python.exe (
  echo Creating .venv ...
  python -m venv .venv || goto :fail
)
echo Installing google-docs-backup into .venv ...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -e . || goto :fail
.venv\Scripts\python.exe -m google_docs_backup service install || goto :fail
echo.
.venv\Scripts\python.exe -m google_docs_backup service status

:done
echo.
pause
exit /b 0

:fail
echo.
echo INSTALL FAILED - see the error above.
pause
exit /b 1
