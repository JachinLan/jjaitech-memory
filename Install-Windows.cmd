@echo off
setlocal DisableDelayedExpansion
set "JJ_MEMORY_ENTRY=%~dp0install.ps1"
powershell.exe -NoProfile -Command "& ([scriptblock]::Create([IO.File]::ReadAllText($env:JJ_MEMORY_ENTRY)))"
set "JJ_RESULT=%ERRORLEVEL%"
if not "%JJ_RESULT%"=="0" echo Installation failed. Keep this output for IT.
pause
exit /b %JJ_RESULT%
