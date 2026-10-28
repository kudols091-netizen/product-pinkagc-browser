# PinkAgc Browser

Antidetect browser manager — clone feature-parity GPM Login Global, lõi mở (Camoufox + BotBrowser),
giữ schema SQLite 1:1 và REST API `/api/v3` tương thích script GPM.

> Sản phẩm riêng trong gia đình PinkAgc. **Không liên quan** code PinkAgc Manager (FB tool) cùng repo.

## Kiến trúc

```
core/
  brand.py            tên + hằng số thương hiệu (một chỗ đổi)
  db.py               SQLite schema GPM 1:1 (profiles/groups/tags/proxies + M:N), soft-delete, audit
  browser_profiles.py 5 skin dropdown: Chrome/Edge/Opera/Brave (Chromium) + Firefox (Gecko)
  fingerprint.py      bridge fingerprint_data (GPM snake_case) -> Normalized -> engine kwargs/configs
  launcher.py         engine Camoufox (Firefox thật)
  botbrowser.py       engine BotBrowser (Chrome thật) — cần BOTBROWSER_BIN + .enc
  engines.py          dispatcher + routing skin->engine
  proxy_providers.py  provider VN (get_current/rotate) + checker (alive/latency/exit IP)
  ovobrowser.py       engine Chrome CHÍNH (mã mở, ổn định, qua CreepJS) — adapter flag từ fingerprint_data
  automation.py       runner no-code Playwright+CDP + OpenCV image-click
  mcp_server.py       MCP server (stdio) — expose profile/proxy/automation làm tool
  api.py              REST :19996 + Web UI (lifecycle/bulk/trash/proxy/automation)
ui/index.html         trình quản lý profile (web): bulk, clone, random FP, note/màu/pin, thùng rác
tools/setup_botbrowser.py   tải + giải nén BotBrowser (engine phụ)
tools/gate_pha_a.py         cổng nghiệm thu: canvas-stability + deviceMemory + webdriver + CreepJS
```

## Engine Chrome

Mặc định **ovobrowser** (ungoogled-chromium patch source-level, free, portable). Tải từ releases
ovobrowser, giải nén, set `OVOBROWSER_BIN`. Mỗi profile một bộ noise seed (canvas/webgl/audio/
rects/font) → fingerprint duy nhất; deviceMemory/brands/gpu spoof lái từ `fingerprint_data`.
Firefox → Camoufox. BotBrowser (premium) / fingerprint-chromium là engine phụ.

## Automation + MCP

```bash
python -m core.mcp_server          # MCP server stdio (9 tool)
claude mcp add pinkagc -- python -m core.mcp_server
# hoặc REST: POST /api/v3/profiles/<id>/run {steps:[...]}
```
Kịch bản = list step JSON (goto/click/type/waitfor/press/scroll/screenshot/eval/extract/image_click).

## 5 skin trình duyệt

| Skin | Engine | Khác nhau ở |
|---|---|---|
| Chrome / Edge / Opera / Brave | BotBrowser (1 lõi Chromium) | UA + Sec-CH-UA brands + navigator.vendor + (Brave: navigator.brave) |
| Firefox | Camoufox (Gecko thật) | engine khác hẳn — không phải UA giả |

## Chạy

```bash
pip install -r requirements.txt
python -m camoufox fetch              # tải engine Firefox (1 lần)
python -m core.api                    # UI + API: http://127.0.0.1:19996/

# Engine Chrome thật (tùy chọn, ~726MB):
python tools/setup_botbrowser.py      # rồi export BOTBROWSER_BIN + bỏ .enc vào BOTBROWSER_PROFILES_DIR
```

## Test

```bash
python test_backbone.py          # DB + bridge Camoufox (+ live launch nếu đã fetch)
python test_extras.py            # botbrowser configs + proxy + API smoke
python test_browser_profiles.py  # 5 skin + routing engine + fidelity
```
