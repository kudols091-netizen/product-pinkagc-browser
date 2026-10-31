# Giao diện PinkAgc Browser

> Trình duyệt antidetect tự host — quản lý profile, fingerprint, proxy, automation từ một chỗ.
> Ảnh chụp toàn bộ giao diện (SPA vanilla JS, Flask 127.0.0.1:19996), font **Roboto** bundle sẵn.

Tài liệu này chụp đầy đủ các màn hình + modal của PinkAgc Browser ở cỡ hiển thị hiện tại (zoom 75%, chế độ Sáng), kèm vài ảnh phụ (tab mua proxy, các tab modal, menu thao tác, dark mode).

---

## Nhận diện & Typography

- **Font giao diện**: **Roboto** (bundle local trong `ui/fonts/`, 3 subset `latin` / `latin-ext` / `vietnamese`, variable 100–900) → chạy offline, đủ dấu tiếng Việt.
- **Trọng lượng dùng**: 400 (dữ liệu) · 500 (nhãn/nav/tab/nút) · 600 (nút chính) · 700 (tiêu đề). Không dùng weight > 700.
- **Code / mono**: `ui-monospace` cho khối code (Developer) và giá trị IP:Port.
- **Màu**: chính `#EA1A87` (hồng Pinkagc) · sidebar `#1B1C26` · nền `#FFF5FA` · trạng thái có chữ đi kèm (Sống/Chết/Đang chạy...).

---

## 1. Các màn hình chính

### Trang chủ
![Trang chủ](screenshots/01-trang-chu.png)

### Danh sách Profile
![Danh sách Profile](screenshots/02-profiles.png)

### Quản lý Nhóm
![Quản lý Nhóm](screenshots/03-nhom.png)

### Quản lý Proxy
![Quản lý Proxy](screenshots/04-proxy.png)

### Quản lý Extensions
![Quản lý Extensions](screenshots/05-extensions.png)

### Thùng rác
![Thùng rác](screenshots/06-thung-rac.png)

---

## 2. Automation & Engine

### Automation — Kịch bản
![Automation](screenshots/07-automation.png)

### Lịch & Nhật ký
![Lịch & Nhật ký](screenshots/08-lich-nhat-ky.png)

### Engine trình duyệt
![Engine](screenshots/09-engine.png)

### App store
![App store](screenshots/10-app-store.png)

---

## 3. Hệ thống & Tích hợp

### Cloud / Team
![Cloud / Team](screenshots/11-cloud-team.png)

### Developer / API
![Developer / API](screenshots/12-developer.png)

### Cài đặt
![Cài đặt](screenshots/13-cai-dat.png)

### MCP cho AI agent
![MCP](screenshots/14-mcp.png)

### Nhật ký (Log)
![Log](screenshots/15-log.png)

### Giới thiệu
![Giới thiệu](screenshots/16-gioi-thieu.png)

---

## 4. Proxy — Mua proxy giá tốt
![Proxy — Mua proxy](screenshots/17-proxy-mua.png)

---

## 5. Modal Tạo profile (5 tab)

### Thao tác nhanh
![Tạo profile — Thao tác nhanh](screenshots/18-modal-tao-thaotacnhanh.png)

### Kết nối
![Tạo profile — Kết nối](screenshots/19-modal-tao-ketnoi.png)

### Phần cứng
![Tạo profile — Phần cứng](screenshots/20-modal-tao-phancung.png)

### Phần mềm
![Tạo profile — Phần mềm](screenshots/21-modal-tao-phanmem.png)

---

## 6. Thao tác profile & Proxy

### Modal Gán proxy (chọn từ thư viện)
![Gán proxy](screenshots/22-modal-gan-proxy.png)

### Menu thao tác profile (14 mục)
![Menu thao tác](screenshots/23-menu-thaotac.png)

---

## 7. Dark mode
![Dark mode](screenshots/24-dark-mode.png)

---

*Chụp tự động bằng Playwright (ovobrowser/Chromium 150, viewport 1500×950, đã đợi `document.fonts.ready` để Roboto nạp đầy đủ trước khi chụp).*
