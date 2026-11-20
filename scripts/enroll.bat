@echo off
rem Re-enroll the owner's face: stop the background SafeCamera, enroll, start it again.
cd /d "%~dp0.."
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object CommandLine -like '*safecamera*' | ForEach-Object { Stop-Process -Id $_.ProcessId }"
python -m safecamera --enroll
start "" pythonw -m safecamera
echo.
echo SafeCamera restarted in the background.
pause
