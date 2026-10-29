# PinkAgc Browser — Tài liệu Giao diện (UI)

> SPA một file `ui/index.html` (vanilla JS, không framework). Backend Flask phục vụ tại
> `http://127.0.0.1:19996/`. Tài liệu này mô tả toàn bộ phần **giao diện**: nhận diện, bố cục,
> từng màn, các modal và thành phần dùng chung.

---

## 1. Nhận diện & bố cục

| Yếu tố | Giá trị |
|--------|---------|
| Sidebar (nền tối) | `#1B1C26` |
| Màu nhấn (hồng) | `#EA1A87` (`--primary`) |
| Nền trang | `#FFF5FA` (`--page`, hồng rất nhạt) |
| Logo | chim cánh cụt (`ui/mascot.png`) |
| Bố cục | **Sidebar trái cố định** + **vùng nội dung** (SPA đổi màn không reload) |

- Sidebar chia 3 cụm, ngăn bởi vạch: **Main** · **Automation** · **Others**.
- Mỗi mục có icon SVG + nhãn; mục đang mở tô nền hồng. MCP có badge `new`.
- Tự làm mới danh sách mỗi 6s (trừ khi đang gõ tìm kiếm / mở modal / menu cột đang mở).

### Sidebar — cây điều hướng (NAV)

```
MAIN
├─ Trang chủ        (= Profiles)
├─ Profiles
├─ Nhóm
├─ Proxy
├─ Extensions
└─ Thùng rác
AUTOMATION
├─ Automation
├─ App store
└─ Developer
OTHERS
├─ Cài đặt
├─ MCP  [new]
├─ Log
└─ Giới thiệu
```

---

## 2. Các màn

### 2.1 Profiles *(màn chính)*

**Tiêu đề:** "Danh sách Profile".

**Thanh công cụ:**
- `＋ Tạo profile` · `⧉ Tạo hàng loạt` · `↑ Import` (JSON) · `⟳ Làm mới`
- Dropdown lọc **Nhóm** · Dropdown lọc **Tag**
- Ô **Tìm profile** (lọc toàn danh sách theo tên)
- Nút **⚙** — menu *Hiển thị cột* (ẩn/hiện: OS · Browser · Engine · Timezone · Lần chạy cuối · Tags), lưu `localStorage`

**Bảng — các cột:**

| Cột | Nội dung |
|-----|----------|
| ☐ | checkbox chọn |
| Tên | 📌 (ghim) + chấm màu nhãn + tên + ✎ (có ghi chú) |
| OS | Windows / macOS / Linux |
| Browser | Chrome / Edge / … |
| Engine | badge: `firefox` (camoufox) / `chromium` (botbrowser) / `auto`… |
| Proxy | badge **loại** (SOCKS5/HTTP) + host:port |
| Timezone | auto / múi giờ ép |
| Trạng thái | pill ● **Sẵn sàng** / ● **Đang chạy** |
| Lần chạy cuối | thời gian tương đối (vd `10h`, `1 ngày`, `—`) |
| Tags | các chip hồng |
| Thao tác | nút theo dòng (xem dưới) |

**Thao tác từng dòng:** `▶ Mở` / `■ Dừng` · `Proxy` (gán) · `⧉` nhân bản · `⤮` random fingerprint · `✎` sửa · `🗑` xoá.

**Thanh chọn hàng loạt** (hiện khi tick ≥1): `▶ Mở` · `■ Đóng` · `⧉ Nhân bản` · `↑ Export` · `＋ Gán tag` · `🗑 Xoá` · `Bỏ chọn`.

**Phân trang:** `‹ trang/tổng ›` · *Số bản ghi mỗi trang* (10/20/30/50/100) · *Tổng số N*.

---

### 2.2 Modal **Tạo profile**

Hàng đầu: **Tên** · **Nhóm** · `⤮ Thông số ngẫu nhiên` · `Thêm mới`.
Cột phải: **bảng tóm tắt** (Browser/OS/UA/Proxy/Language/Timezone/WebRTC/GPU/Screen) + ghi chú mặc định an toàn.

5 tab:

| Tab | Nội dung |
|-----|----------|
| **Thao tác nhanh** | Số lượng (tạo hàng loạt) · Trình duyệt · OS · Engine · URL khởi động · Proxy (+ *Chọn từ thư viện*, *Kiểm tra proxy*) |
| **Kết nối** | WebRTC (Base on IP…) · Geolocation · Timezone (datalist gợi ý) |
| **Hardware** | Screen resolution · Canvas/Client Rects/WebGL/Audio (Noise/Real) · WebGL GPU (pool thật) · số nhân CPU |
| **Software** | User agent · Ngôn ngữ · Do Not Track · Ẩn media devices |
| **Cookies** | textarea dán cookie JSON / Netscape (nạp ở lần Mở tới) |

---

### 2.3 Modal **Sửa profile** (fingerprint chi tiết)

2 tab:
- **Thông tin:** Tên · Nhóm · Timezone (trống = auto) · Ghi chú · **Tags** (cách nhau dấu phẩy) · Màu nhãn (color) · ☑ Ghim lên đầu.
- **Hardware / Fingerprint:** Screen resolution · **WebGL GPU** (dropdown pool GPU thật) · Số nhân CPU · Device memory · mode **Canvas / Client Rects / WebGL image / Audio** (Noise/Real/Masked) · ☑ Do Not Track.

Footer: `Huỷ` · `Lưu`.

---

### 2.4 Nhóm

- Thanh công cụ: ô **Tên nhóm** (inline) + `＋ Thêm mới` + `⟳`.
- Bảng: **Tên nhóm** · **Số profile** · Thao tác (`Đổi tên` · `🗑`).

---

### 2.5 Proxy

**Thanh công cụ:** `＋ Thêm proxy` · `↑ Import hàng loạt` · ô tìm proxy.

**Bảng:** ☐ · **IP:Port** · **Quốc gia / Exit IP** · **Loại** · **Độ trễ** · **Trạng thái** (● Hoạt động / Không hoạt động / Chưa kiểm tra) · Thao tác (`▶ Kiểm tra` · `🗑`). Chân bảng: *Tổng số N*.

**Modal Thêm proxy:**
- **Loại proxy** (Tự nhận / Http / Https / Socks5)
- **Danh sách proxy** — textarea **nhiều dòng** (mỗi dòng 1 proxy: `IP:Port` hoặc `IP:Port:User:Pass`; Socks5 UDP thêm `:True`)
- `Cancel` · `OK` (thêm hàng loạt, tự gắn scheme theo loại đã chọn)

**Modal Gán proxy cho 1 profile:** nhập raw proxy **hoặc** chọn provider + API key · `Kiểm tra` · `Gán`.

---

### 2.6 Extensions

- Chọn **Profile** (dropdown) + `＋ Thêm extension`.
- Bảng: đường dẫn thư mục extension (unpacked) · `🗑`. Áp dụng ở lần Mở kế tiếp.

---

### 2.7 Thùng rác

- Bảng: **Tên profile** · **Proxy** · **Lần chạy cuối** · Thao tác (`⤮ Khôi phục` · `🗑 Xoá vĩnh viễn`).
- Rỗng → mascot + "Thùng rác trống".

---

### 2.8 Automation *(no-code)*

Bố cục 2 cột:
- **Trái:** chọn **Profile** · textarea **Kịch bản (JSON steps)** · `✓ Kiểm tra cú pháp` · `▶ Chạy`.
- **Phải:** danh sách **action hỗ trợ** (`goto · click · type · fill · wait · waitfor · press · scroll · screenshot · eval · extract · image_click`) · ghi chú · ô **output** kết quả.

Chạy headless, xong tự đóng (nếu profile chưa mở). `type` gõ thật, `image_click` dùng OpenCV.

---

### 2.9 App store

Lưới thẻ **template kịch bản automation** dựng sẵn: tên · mô tả · `▶ Dùng` (nạp vào màn Automation) · số bước.

---

### 2.10 Developer *(tài liệu API)*

- Tiêu đề "Developer / API" + health (engine/profile đang chạy).
- Thanh: `↑ Export profile` · `Import`.
- Thẻ **Base URL** (`…/api/v3`) + nút Copy + 2 ví dụ `curl`.
- **Tham chiếu API 2 cột**, nhóm theo chủ đề (**Profiles · Nhóm · Proxy · Cookies & Extensions · Cài đặt & Hệ thống · MCP**), mỗi endpoint có **badge method** (GET/POST/DELETE) + path + mô tả + params.
- `GET /api/v3/endpoints` tự liệt kê mọi route.

---

### 2.11 Cài đặt

3 tab (như GPM): **Chung** · **Trình duyệt** · **API Gateway** — cấu hình mặc định: OS/Browser/Engine, headless, mode fingerprint (canvas/webgl/audio/font…), screen, ngôn ngữ, URL khởi động, tham số Chrome, xoá cache…

---

### 2.12 MCP *(kết nối AI agent)* `new`

Bố cục 2 cột:
- **Trái:** (1) Lệnh `claude mcp add` để đăng ký vào Claude Code (copy sẵn); (2) **Config JSON** thủ công cho Claude Desktop/Cursor (đã điền sẵn path Python + env).
- **Phải:** bảng **9 tool** khả dụng (tạo/mở/đóng/clone profile, đổi proxy, random fingerprint, chạy automation…).

Chạy **stdio cục bộ** — không mở cổng mạng, không cần token.

---

### 2.13 Log · Giới thiệu

- **Log:** nhật ký hành động trong phiên (tạo/mở/đóng profile…).
- **Giới thiệu:** mascot + tên + mô tả + dòng kiểm tra engine (health).

---

## 3. Thành phần UI dùng chung

| Thành phần | Mô tả |
|------------|-------|
| **Toast** | thông báo góc, có chấm trạng thái (ok/err) |
| **Pill trạng thái** | ● Sẵn sàng / ● Đang chạy |
| **Proxy badge** | badge loại (SOCKS5/HTTP) + host:port |
| **Tag chip** | chip bo tròn màu hồng |
| **Chấm màu nhãn** | đứng trước tên profile |
| **Overlay + Modal** | nền mờ + hộp thoại (Tạo/Sửa/Proxy); modal nhỏ `sm` cho gán proxy |
| **Segmented / tabs** | chuyển tab trong modal, Cài đặt |
| **Pager** | ‹ › + số bản ghi/trang + tổng số |
| **Empty state** | mascot + tiêu đề + gợi ý (khi danh sách rỗng) |

---

## 4. Trạng thái hoàn thiện

✅ **Mọi màn đã có backend + chức năng thật.** Giao diện đối chuẩn GPM Login
(Tạo hàng loạt/Import, bulk actions, filter nhóm+tag, ẩn/hiện cột, phân trang, proxy bulk,
tags, Developer=API docs, MCP, Settings 3 tab). Mục *Plugins* đã gỡ khỏi NAV.
