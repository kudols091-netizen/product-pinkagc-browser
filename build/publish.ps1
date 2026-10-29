# Phat hanh ban moi PinkAgc Browser (auto-update cho khach cu).
# Truoc khi chay: tang VERSION trong core\brand.py.
# Chay: powershell -ExecutionPolicy Bypass -File build\publish.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# Doc VERSION tu brand.py
$ver = (Select-String -Path "core\brand.py" -Pattern 'VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Phat hanh version: $ver" -ForegroundColor Cyan

# 1) Build exe (KHONG kem vendor -> file nhe, dung cho auto-update)
& "$PSScriptRoot\build-exe.ps1"

# 2) Sinh version.json
$notes = Read-Host "Ghi chu ban nay (notes, Enter de bo trong)"
$manifest = [ordered]@{
  version = $ver
  url     = "https://agency.pinkagc.com/browser/PinkAgcBrowser.exe"
  notes   = $notes
}
$manifest | ConvertTo-Json | Set-Content -Path "dist\version.json" -Encoding utf8

Write-Host ""
Write-Host "Da san sang trong dist\:" -ForegroundColor Green
Write-Host "  - PinkAgcBrowser.exe   (ban update, vai chuc MB)"
Write-Host "  - version.json"
Write-Host ""
Write-Host ">> UPLOAD ca 2 file len: agency.pinkagc.com/browser/" -ForegroundColor Yellow
Write-Host "   (nhu cach ban deploy PHP: FTP / file manager)"
Write-Host "Xong -> moi may khach check version.json se tu tai exe moi va cap nhat."
Write-Host ""
Write-Host "LUU Y: bo cai DAY DU (co vendor 4.6GB) cho khach MOI la file khac," -ForegroundColor DarkYellow
Write-Host "       build bang build\installer.iss, host o Google Drive (dung de tren web hosting)."
