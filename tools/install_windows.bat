@echo off
setlocal
set SCRIPT_DIR=%~dp0

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install_windows.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
  echo Windows installer failed with exit code %EXIT_CODE%.
) else (
  echo Windows installer finished.
)
pause
exit /b %EXIT_CODE%
