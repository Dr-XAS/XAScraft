@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installers\local\install-windows.ps1" %*
if errorlevel 1 (
  echo Installation failed. See the message above and the XAScraft logs folder.
  pause
  exit /b 1
)
echo Installation complete. Open XAScraft from the Start menu.
pause
