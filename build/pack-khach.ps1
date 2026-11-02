# Gói bản KHÁCH theo mô hình GPM: app exe + 1 ovobrowser-core SẠCH, profile tách riêng (tạo lúc chạy),
# KHÔNG kèm engine thừa / Data / cache / profile của mình.
#   Chạy:  powershell -ExecutionPolicy Bypass -File build\pack-khach.ps1 [-Build] [-Zip]
#   -Build : build lại exe trước khi gói (mặc định dùng PinkAgcBrowser.exe sẵn có ở gốc/dist).
#   -Zip   : nén luôn ra .zip để giao khách.
param([switch]$Build, [switch]$Zip)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if ($Build) {
  Write-Host "== Build exe trước khi gói ==" -ForegroundColor Cyan
  powershell -ExecutionPolicy Bypass -File "$root\build\build-exe.ps1"
}

# Nguồn exe: ưu tiên bản ở gốc (đã swap), fallback dist\.
$exe = if (Test-Path "$root\PinkAgcBrowser.exe") { "$root\PinkAgcBrowser.exe" }
       elseif (Test-Path "$root\dist\PinkAgcBrowser.exe") { "$root\dist\PinkAgcBrowser.exe" }
       else { throw "Không thấy PinkAgcBrowser.exe — chạy với -Build hoặc build\build-exe.ps1 trước." }

$ovo = "$root\vendor\ovobrowser"
if (-not (Get-ChildItem $ovo -Recurse -Filter chrome.exe -EA SilentlyContinue)) {
  throw "Không thấy chrome.exe trong vendor\ovobrowser — thiếu engine mặc định."
}

$out = "$root\dist-khach"
$pkg = "$out\PinkAgc-Browser"
if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Force -Path $pkg | Out-Null

Write-Host "== 1) Copy app exe ==" -ForegroundColor Cyan
Copy-Item $exe "$pkg\PinkAgcBrowser.exe" -Force

Write-Host "== 2) Copy ovobrowser-core (sạch: loại profile/cache/junk) ==" -ForegroundColor Cyan
# /XD: bỏ mọi thư mục user-data lỡ lẫn vào core (asset*, profiles, *Cache*).
# /XF: bỏ log/tmp/symbol. Chỉ 1 engine ovobrowser — KHÔNG đụng botbrowser/fpchromium/apostate.
robocopy $ovo "$pkg\vendor\ovobrowser" /E `
  /XD asset "asset.OLD*" profiles Cache "Code Cache" GPUCache `
  /XF *.log *.tmp *.pdb *.old `
  /NFL /NDL /NP /NJH /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy lỗi (code $LASTEXITCODE)" }

Write-Host "== 3) README cho khách ==" -ForegroundColor Cyan
@"
PinkAgc Browser
===============
Chạy: bấm đúp PinkAgcBrowser.exe (chạy nền, mở cửa sổ app — không có cửa sổ đen).
Lần đầu chạy sẽ tự tạo thư mục asset\ (profile + dữ liệu) cạnh file exe.

Thư mục:
  PinkAgcBrowser.exe     - ứng dụng
  vendor\ovobrowser\     - nhân trình duyệt (Chromium antidetect) mặc định
  asset\ (tự tạo)        - profile + cấu hình + DB của bạn

Engine khác (botbrowser/fpchromium) tải thêm trong app: tab Engine.
Hỗ trợ: liên hệ nơi bạn mua bản quyền.
"@ | Out-File "$pkg\README.txt" -Encoding utf8

# ---- Báo cáo ----
$sz = [math]::Round((Get-ChildItem $pkg -Recurse -File | Measure-Object Length -Sum).Sum/1MB, 0)
$nf = (Get-ChildItem $pkg -Recurse -File).Count
Write-Host ""
Write-Host "XONG: $pkg" -ForegroundColor Green
Write-Host ("  {0} file, {1} MB" -f $nf, $sz) -ForegroundColor Green

if ($Zip) {
  Write-Host "== 4) Nén .zip (có thể hơi lâu) ==" -ForegroundColor Cyan
  $zip = "$out\PinkAgc-Browser.zip"
  if (Test-Path $zip) { Remove-Item $zip -Force }
  Compress-Archive -Path $pkg -DestinationPath $zip -CompressionLevel Optimal
  $zsz = [math]::Round((Get-Item $zip).Length/1MB, 0)
  Write-Host ("  ZIP: $zip  ({0} MB)" -f $zsz) -ForegroundColor Green
}
