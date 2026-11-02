# Build PinkAgc Browser -> dist\PinkAgcBrowser.exe (PyInstaller single-file).
# Yeu cau: pip install pyinstaller flask playwright pysocks opencv-python-headless numpy
# Chay tu thu muc goc: powershell -ExecutionPolicy Bypass -File build\build-exe.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$icon = ""
if (Test-Path "ui\favicon.ico") { $icon = "--icon=ui\favicon.ico" }

# --add-data "ui;ui": bundle thu muc UI vao .exe (frozen -> _MEIPASS\ui, khop _UI_DIR cua api.py)
# KHONG bundle vendor\ (4.6GB ovobrowser) va asset\ (du lieu) -> de canh .exe luc phat hanh.
# --windowed: KHONG hien cua so console den (chay nen nhu GPM); stdout/stderr=None da duoc app.py va.
# --collect-all playwright: GOI playwright (driver) -> automation + Test fingerprint + inject cookie
#   chay duoc trong .exe (noi CDP vao ovobrowser, KHONG tai browser rieng cua playwright).
# --exclude-module: camoufox (Firefox) can binary rieng -> van loai (profile Firefox raise loi co
#   kiem soat); cv2/numpy/torch (captcha nang) loai de nhe. Engine chinh: ovobrowser/Chromium.
pyinstaller --noconfirm --onefile --windowed --name "PinkAgcBrowser" `
  $icon `
  --add-data "ui;ui" `
  --hidden-import flask --hidden-import socks `
  --collect-submodules core `
  --collect-all playwright `
  --exclude-module camoufox `
  --exclude-module cv2 --exclude-module numpy --exclude-module torch `
  app.py

Write-Host ""
Write-Host "Xong: dist\PinkAgcBrowser.exe" -ForegroundColor Green
Write-Host "Phat hanh: dat .exe + thu muc vendor\ canh nhau (asset\ se tu tao khi chay)."
