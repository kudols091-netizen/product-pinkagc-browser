# Đóng gói & phát hành PinkAgc Browser

Mục tiêu: biến app (chạy `python -m core.api`) thành **.exe cài đặt + tự cập nhật** để giao khách.

## Thành phần đã có
| File | Việc |
|------|------|
| `app.py` (gốc) | Entry-point: khởi động server + tự mở trình duyệt. Chạy dev: `python app.py`. Cũng là file PyInstaller bundle. |
| `core/brand.py` | `VERSION` + `UPDATE_URL` (nơi đặt JSON công bố bản mới). |
| `/api/v3/version`, `/api/v3/check-update` | API trả phiên bản + so với `UPDATE_URL` để báo có bản mới. |
| `build/build-exe.ps1` | Build `dist\PinkAgcBrowser.exe` (PyInstaller one-file). |
| `build/installer.iss` | Script Inno Setup tạo bộ cài. |

## Quy trình phát hành
1. **Tăng version**: sửa `VERSION` trong `core/brand.py` (và `installer.iss` `MyAppVersion`).
2. **Build exe**: `powershell -ExecutionPolicy Bypass -File build\build-exe.ps1` → `dist\PinkAgcBrowser.exe`.
3. **Đóng gói**: cài Inno Setup rồi `iscc build\installer.iss` → `dist\PinkAgcBrowser-Setup-x.y.z.exe`.
4. **Đăng bản**: upload setup.exe lên host; cập nhật file JSON tại `UPDATE_URL`:
   ```json
   { "version": "0.1.1", "url": "https://.../PinkAgcBrowser-Setup-0.1.1.exe", "notes": "Sửa abc" }
   ```
   App sẽ gọi `check-update`, thấy version mới hơn → báo người dùng tải.

## 2 quyết định còn lại (của bạn)
- **vendor/ (~4.6GB ovobrowser)**: nặng để nhét vào bộ cài. Chọn 1:
  - (a) **Nhét luôn** vào installer (`installer.iss` giữ dòng `vendor\*`) — bộ cài ~vài GB.
  - (b) **Tải lần đầu**: bỏ dòng `vendor\*`, viết bước "tải ovobrowser khi chạy lần đầu" (giống `tools/` hiện có). Bộ cài nhẹ (vài chục MB).
- **UPDATE_URL host**: đặt JSON ở đâu (GitHub Releases raw, S3, hosting riêng). Có thể dùng chính `app.pinkagc.com`.
- *(tuỳ chọn)* **Ký số (code signing)** để Windows SmartScreen không cảnh báo — cần chứng chỉ.

## Trạng thái
- ✅ Chạy được ngay: `python app.py` (server + mở trình duyệt), API version/check-update.
- ⏳ Cần **1 lần build thử** + chọn phương án vendor + host UPDATE_URL để ra bộ cài hoàn chỉnh.
  Các script `build-exe.ps1` / `installer.iss` là chuẩn PyInstaller/Inno; có thể cần tinh chỉnh nhỏ sau lần build đầu (thường là `--add-data`/hidden-import).
