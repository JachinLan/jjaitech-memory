@echo off
setlocal
chcp 65001 >nul
set "JJAITECH_INSTALL_ROOT=%~dp0..\.."
powershell.exe -NoProfile -Command "& ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $env:JJAITECH_INSTALL_ROOT 'jjaitech-memory\distribution\bootstrap-windows.ps1')))) -PackageRoot $env:JJAITECH_INSTALL_ROOT"
set "JJAITECH_EXIT=%ERRORLEVEL%"
if not "%JJAITECH_EXIT%"=="0" echo Installation failed. Keep this output; do not change company security policies.
pause
exit /b %JJAITECH_EXIT%
