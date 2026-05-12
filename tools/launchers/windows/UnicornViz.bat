@echo off
setlocal
set REPO=%~dp0\..\..\..
cd /d "%REPO%"

if "%~1"=="" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0UnicornVizGUI.ps1"
  exit /b %ERRORLEVEL%
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m unicornviz %*
) else (
  python -m unicornviz %*
)
