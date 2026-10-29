@echo off
rem --- PinkAgc Browser launcher (standalone) ---
cd /d "%~dp0"
set "OVOBROWSER_BIN=%~dp0vendor\ovobrowser\app\ovobrowser-150-150.0.7871.124-win64-portable\chrome.exe"
set "PYTHONIOENCODING=utf-8"
echo Mo PinkAgc Browser tai http://127.0.0.1:19996/
python -m core.api
pause
