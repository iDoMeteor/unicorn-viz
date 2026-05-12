@echo off
setlocal
set SCRIPT_DIR=%~dp0

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%UnicornVizGUI.ps1"
exit /b %ERRORLEVEL%
