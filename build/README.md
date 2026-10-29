# Đóng gói & phát hành PinkAgc Browser

Biến app thành **.exe cài đặt + tự cập nhật tập trung**: bạn publish bản mới ở 1 chỗ → mọi máy khách tự update.

## Kiến trúc (đã chốt)
- **Vendor 4.6GB (ovobrowser) nhét vào BỘ CÀI** — khách cài 1 lần.
- **Auto-update chỉ thay file `.exe` nhỏ** (vài chục MB), vendor giữ nguyên → nhẹ.
- **Host cập nhật: `agency.pinkagc.com/browser/`** (an toàn: `.htaccess` không có catch-all, không chặn `.exe/.json`).

## Thành phần
| File | Việc |
|------|------|
| `app.py` | Entry-point: server + tự mở trình duyệt (double-click là chạy). |
| `core/brand.py` | `VERSION` + `UPDATE_URL = agency.pinkagc.com/browser/version.json`. |
| `core/updater.py` | Kiểm tra manifest + tải exe mới + thay nóng qua `_update.bat` (Windows, bản .exe). |
| `/api/v3/version`, `/check-update`, `/update/apply` | API cho nút "Cài bản mới" ở màn Giới thiệu. |
| `build/build-exe.ps1` | Build `dist\PinkAgcBrowser.exe` (PyInstaller, KHÔNG kèm vendor). |
| `build/installer.iss` | Inno Setup: bộ cài đầy đủ (exe + vendor). |
| `build/publish.ps1` | Build + sinh `version.json` + nhắc upload lên host. |

## A. Phát hành bản cập nhật (cho khách CŨ) — thường xuyên
1. Sửa `VERSION` trong `core/brand.py` (vd `0.1.0` → `0.1.1`).
2. `powershell -ExecutionPolicy Bypass -File build\publish.ps1` → ra `dist\PinkAgcBrowser.exe` + `dist\version.json`.
3. **Upload 2 file** lên `agency.pinkagc.com/browser/` (FTP/file manager, như deploy PHP).
4. Xong. App khách bấm **Giới thiệu → Kiểm tra cập nhật** (hoặc tự check) → thấy bản mới → **Cài bản mới** → tự tải, thay exe, mở lại.

> "Update ở máy bạn → khách update luôn." ✔

## B. Bộ cài đầy đủ (cho khách MỚI) — ít khi
1. `build\build-exe.ps1` (ra exe).
2. Cài **Inno Setup**, chạy `iscc build\installer.iss` → `dist\PinkAgcBrowser-Setup-x.y.z.exe` (**kèm vendor 4.6GB → file rất nặng**).
3. Host bộ cài này ở **Google Drive / file host** (ĐỪNG để trên web hosting vì 4.6GB), gửi link cho khách mới.

## Còn lại (1 lần)
- **Build thử**: `pip install pyinstaller` rồi chạy `build-exe.ps1`; lần đầu có thể cần tinh chỉnh `--add-data`/`--hidden-import`.
- *(tuỳ chọn)* **Ký số** (code signing) để Windows SmartScreen không cảnh báo khách.
- Tạo sẵn thư mục `browser/` trên agency.pinkagc.com.
