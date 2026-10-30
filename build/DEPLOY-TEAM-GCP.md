# Deploy Team Server lên Google Cloud (VM) — hướng dẫn chi tiết

Mục tiêu: chạy **Team server (Python)** 24/7 trên 1 GCP VM nhỏ, có **HTTPS** tại
`https://team.pinkagc.com`, để app PinkAgc Browser trên mọi máy đồng bộ profile + chia sẻ đội nhóm.
Team server chỉ cần **Flask** (siêu nhẹ, RAM ~50MB).

> Chi phí: `e2-micro` ở vùng US gần như **always-free**; còn lại trừ vào **credit $300** free trial → ~0đ hơn 1 năm.

---

## Bước 1 — Tạo VM (Compute Engine)
**Cách A — Console (dễ):**
1. console.cloud.google.com → menu ☰ → **Compute Engine → VM instances** → (bật API nếu hỏi) → **Create instance**.
2. Cấu hình:
   - **Name**: `pinkagc-team`
   - **Region**: `us-central1` (hoặc `us-west1`/`us-east1`) để ăn free-tier · **Machine**: `e2-micro` (đủ) hoặc `e2-small`.
   - **Boot disk**: Ubuntu 24.04 LTS, 10–20GB.
   - **Firewall**: tick ✅ **Allow HTTP traffic** + ✅ **Allow HTTPS traffic** (mở 80/443 cho Caddy).
3. **Create**. Ghi lại **External IP** của VM.

**Cách B — gcloud (nếu quen CLI):**
```bash
gcloud compute instances create pinkagc-team \
  --zone=us-central1-a --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --tags=http-server,https-server
```

---

## Bước 2 — Trỏ tên miền `team.pinkagc.com` về VM
Vào nơi quản lý DNS của `pinkagc.com` (chỗ bạn quản domain), thêm bản ghi:
```
Loại A   |   Tên: team   |   Giá trị: <External IP của VM>   |   TTL: mặc định
```
Đợi vài phút cho DNS lan. (Caddy cần cái này để xin chứng chỉ HTTPS.)

---

## Bước 3 — SSH vào VM + cài đặt
Bấm **SSH** cạnh VM trong Console (mở terminal web). Chạy:
```bash
sudo apt update && sudo apt install -y python3 python3-venv git

# Lấy code (repo private -> dùng GitHub token khi bị hỏi mật khẩu)
sudo mkdir -p /opt/pinkagc-browser && sudo chown $USER:$USER /opt/pinkagc-browser
git clone https://github.com/kudols091-netizen/pinkagc-browser.git /opt/pinkagc-browser
cd /opt/pinkagc-browser

# Môi trường Python + Flask (team server chỉ cần Flask)
python3 -m venv .venv
.venv/bin/pip install flask
mkdir -p asset

# Chạy thử tay (Ctrl+C để dừng)
.venv/bin/python -m core.team_server --host 127.0.0.1 --port 8787
```
> Repo private: khi `git clone` hỏi user/pass, nhập **username GitHub** + **Personal Access Token** (tạo ở GitHub → Settings → Developer settings → Fine-grained token, quyền Read repo). Hoặc dùng `gcloud compute scp` copy thư mục `core/` lên.

---

## Bước 4 — Chạy 24/7 bằng systemd
```bash
# Sửa User= trong file service cho khớp user SSH của bạn (xem bằng: whoami)
sudo cp /opt/pinkagc-browser/build/team-server.service /etc/systemd/system/
sudo nano /etc/systemd/system/team-server.service   # đổi User=pinkagc -> user của bạn
sudo systemctl daemon-reload
sudo systemctl enable --now team-server
sudo systemctl status team-server      # phải thấy "active (running)"
```

---

## Bước 5 — HTTPS bằng Caddy (tự cấp chứng chỉ)
```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp /opt/pinkagc-browser/build/Caddyfile /etc/caddy/Caddyfile   # (đã trỏ team.pinkagc.com)
sudo systemctl restart caddy
```
Caddy sẽ **tự xin chứng chỉ Let's Encrypt** cho `team.pinkagc.com` (cần Bước 2 xong + port 80/443 mở ở Bước 1).

**Kiểm tra:** mở `https://team.pinkagc.com/team/me` → thấy JSON `{"success":false,"message":"unauthorized"}` là **server chạy + HTTPS OK** (401 vì chưa đăng nhập — đúng).

---

## Bước 6 — Dùng trong app PinkAgc Browser
Trên **mỗi máy** (bạn + nhân viên/khách):
1. Mở app → **Cloud / Team**.
2. **Server URL**: `https://team.pinkagc.com` · nhập username/password.
3. **Người đầu tiên bấm Đăng ký = admin**; người sau Đăng ký = member.
4. **Đăng nhập** → **Đồng bộ ngay** (đẩy profile lên + kéo về).
5. Chia sẻ 1 profile: **Profiles → ⋯ → Chia sẻ (team)** (username + quyền read/run/write).

---

## Cập nhật server sau này
```bash
cd /opt/pinkagc-browser && git pull && sudo systemctl restart team-server
```

## Sự cố thường gặp
- **Caddy không ra HTTPS**: DNS `team` chưa trỏ đúng IP, hoặc 80/443 chưa mở (Bước 1 chưa tick HTTP/HTTPS). Xem `sudo journalctl -u caddy -n 50`.
- **team-server không chạy**: sai `User=`/đường dẫn trong service. Xem `sudo journalctl -u team-server -n 50`.
- **Không kết nối từ app**: dùng đúng `https://` + domain (không phải IP, vì chứng chỉ cấp cho domain).
- **An toàn**: team server bind `127.0.0.1` (không ra ngoài), chỉ Caddy (TLS) proxy vào → token đi qua HTTPS. Đừng mở 8787 ra internet.
