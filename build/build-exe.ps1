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
# --exclude-module: engine mac dinh (ovobrowser) chay qua CDP, KHONG can playwright/camoufox.
#   Loai chung + numpy/cv2/torch -> exe ~16MB (thay vi ~120MB). Camoufox trong ban dong goi
#   se raise RuntimeError co kiem soat (launcher.py), khach dung ovobrowser la chinh.
pyinstaller --noconfirm --onefile --name "PinkAgcBrowser" `
  $icon `
  --add-data "ui;ui" `
  --hidden-import flask --hidden-import socks `
  --collect-submodules core `
  --exclude-module playwright --exclude-module camoufox `
  --exclude-module cv2 --exclude-module numpy --exclude-module torch `
  app.py

Write-Host ""
Write-Host "Xong: dist\PinkAgcBrowser.exe" -ForegroundColor Green
Write-Host "Phat hanh: dat .exe + thu muc vendor\ canh nhau (asset\ se tu tao khi chay)."
