@echo off
setlocal
chcp 65001 >nul
echo jjaitech-memory 1.3.0-rc.3 - Windows pilot only
echo Not approved for company-wide rollout. Read docs/OPERATIONS.md first.
py -3 -X utf8 "%~dp0install_windows.py" %*
set "JJAITECH_EXIT=%ERRORLEVEL%"
if not "%JJAITECH_EXIT%"=="0" echo Installation/check failed. Keep the output for review.
pause
exit /b %JJAITECH_EXIT%
