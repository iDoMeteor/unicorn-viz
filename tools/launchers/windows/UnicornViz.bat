@echo off
setlocal
set REPO=%~dp0\..\..\..
cd /d "%REPO%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m unicornviz %*
) else (
  python -m unicornviz %*
)
