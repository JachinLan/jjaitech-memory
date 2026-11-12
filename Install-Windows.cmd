@echo off
setlocal DisableDelayedExpansion
call "%~dp0jjaitech-memory\deployment\install-windows.cmd"
exit /b %ERRORLEVEL%
