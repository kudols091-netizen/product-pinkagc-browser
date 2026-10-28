"""Engine BotBrowser (Chromium fork) — cho fidelity Chrome THẬT.

Khác Camoufox (Firefox): BotBrowser là Chromium, có `navigator.deviceMemory`, UA Chrome,
CDP chuẩn. Fingerprint lõi nằm trong file `.enc` prebuilt (vd chrome155_win11_x64.enc) —
KHÔNG serialize tay được; ta CHỌN .enc khớp os/version rồi override phần động qua configs + CLI.

Launch (xác nhận từ repo botswin/BotBrowser):
  botbrowser --bot-profile=<x.enc> --user-data-dir=<dir> --remote-debugging-port=<p>
             --proxy-server=... --proxy-username=... --proxy-password=... --no-sandbox

Cần cấu hình đường dẫn qua env:
  BOTBROWSER_BIN           -> binary chrome của BotBrowser
  BOTBROWSER_PROFILES_DIR  -> thư mục chứa các .enc
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .fingerprint import NormalizedFingerprint

_OS_TOKEN = {"windows": "win", "macos": "mac", "linux": "linux"}


def to_botbrowser_configs(n: NormalizedFingerprint) -> dict[str, Any]:
    """Phần override động (BotBrowser configs.*). Lõi fingerprint do .enc lo.

    Chromium nhận nhiều field hơn Firefox: ngoài tz/locale/geo còn mac/dns/portProtection/
    hardwareConcurrency/deviceMemory. (Tên key cần verify với CLI_FLAGS.md của bản BotBrowser.)
    """
    cfg: dict[str, Any] = {}
    if n.timezone:
        cfg["timezone"] = n.timezone
    if n.language:
        cfg["locale"] = n.language
    if n.geolocation:
        lat, lon, acc = n.geolocation
        cfg["geolocation"] = {"latitude": lat, "longitude": lon, "accuracy": acc}
    if n.port_protect:
        cfg["portProtection"] = [int(p) for p in n.port_protect.split(";") if p.strip().isdigit()]
    if n.hardware_concurrency:
        cfg["hardwareConcurrency"] = n.hardware_concurrency
    if n.device_memory:
        cfg["deviceMemory"] = n.device_memory          # Chromium CÓ API này (khác Firefox)
    if n.mac_address:
        cfg["macAddress"] = n.mac_address
    if n.custom_dns:
        cfg["dnsServer"] = n.custom_dns
    if n.webrtc_ip:
        cfg["webrtcIp"] = n.webrtc_ip
    # Danh tính skin (chrome/edge/opera/brave): UA + Sec-CH-UA brands + vendor + platform.
    # Đây là thứ làm 4 skin Chromium phân biệt & NHẤT QUÁN (UA khớp brands khớp vendor).
    # (tên key cần verify với CLI_FLAGS.md của bản BotBrowser đang dùng.)
    if n.skin_user_agent:
        cfg["userAgent"] = n.skin_user_agent
    if n.ua_brands:
        cfg["userAgentData"] = {"brands": n.ua_brands,
                                "platform": n.ua_platform or "Windows", "mobile": False}
    if n.vendor is not None:
        cfg["vendor"] = n.vendor
    if n.platform:
        cfg["platform"] = n.platform
    if n.has_brave_api:
        # Brave thật cần navigator.brave.isBrave(): lý tưởng là .enc Brave, nếu không thì inject JS.
        cfg["brave"] = True
    return cfg


def pick_profile(n: NormalizedFingerprint, profiles_dir: str | Path,
                 chrome_major: str = "155") -> Optional[str]:
    """Chọn .enc khớp os + chrome major gần nhất. Trả path hoặc None nếu không có."""
    d = Path(profiles_dir)
    if not d.is_dir():
        return None
    os_tok = _OS_TOKEN.get(n.os_type, "win")
    encs = sorted(d.glob("*.enc"))
    exact = [p for p in encs if os_tok in p.name.lower() and chrome_major in p.name]
    by_os = [p for p in encs if os_tok in p.name.lower()]
    for bucket in (exact, by_os, encs):
        if bucket:
            return str(bucket[0])
    return None


def _proxy_url(p: dict[str, str]) -> str:
    """Playwright proxy dict -> URL nhúng credential (BotBrowser: --proxy-server=scheme://user:pass@host:port).

    BotBrowser KHÔNG nhận --proxy-username/--proxy-password rời; credential phải nhúng vào URL.
    """
    server = p["server"]
    if p.get("username") and "://" in server:
        scheme, rest = server.split("://", 1)
        return f"{scheme}://{p['username']}:{p.get('password','')}@{rest}"
    return server


def build_args(n: NormalizedFingerprint, *, bot_profile: str, user_data_dir: str,
               port: int, headless: bool = True) -> list[str]:
    """CLI khớp interface thật BotBrowser (CLI_FLAGS.md). Identity nằm trong .enc; tz/locale
    tự căn theo proxy (smart auto-config). Override tz/locale/UA là flag ENT-tier -> bỏ ở core."""
    args = [
        f"--bot-profile={bot_profile}",
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run", "--no-default-browser-check", "--no-sandbox",
    ]
    if headless:
        args.append("--headless=new")
    if n.proxy:
        args.append(f"--proxy-server={_proxy_url(n.proxy)}")   # credential nhúng trong URL
    return args


def _read_cdp_ws(port: int, timeout: float = 15.0) -> str:
    """Đọc ws endpoint CDP từ http://127.0.0.1:<port>/json/version."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                data = json.loads(r.read().decode())
                return data["webSocketDebuggerUrl"]
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.3)
    raise RuntimeError(
        f"Engine không mở được trên port {port} sau {timeout:.0f}s — thường do: binary sai/thiếu, "
        f"profile đang mở ở tiến trình khác (giữ khoá), hoặc máy thiếu RAM. Chi tiết: {last}")


def serve(profile_fp: dict, profile_dyn: dict, profiles_root: str | Path, *,
          storage_name: str, headless: bool = True, port: int = 9222) -> tuple[Any, str]:
    """Spawn BotBrowser, trả (proc, cdp_ws). Cần BOTBROWSER_BIN + BOTBROWSER_PROFILES_DIR."""
    import subprocess

    from .fingerprint import parse_gpm
    binary = os.environ.get("BOTBROWSER_BIN")
    enc_dir = os.environ.get("BOTBROWSER_PROFILES_DIR", "")
    if not binary or not Path(binary).exists():
        raise RuntimeError("Chưa cấu hình BOTBROWSER_BIN (binary chrome của BotBrowser).")
    n = parse_gpm(profile_fp, profile_dyn)
    # .enc PHẢI cùng major với binary, nếu không BotBrowser từ chối profile -> rơi Chromium trần.
    major = str((profile_fp.get("browser", {}) or {}).get("browser_version", "149")).split(".")[0] or "149"
    enc = pick_profile(n, enc_dir, chrome_major=major)
    if not enc:
        raise RuntimeError(f"Không tìm thấy .enc khớp trong BOTBROWSER_PROFILES_DIR={enc_dir!r}")

    udd = Path(profiles_root) / storage_name
    udd.mkdir(parents=True, exist_ok=True)

    args = build_args(n, bot_profile=enc, user_data_dir=str(udd), port=port, headless=headless)
    proc = subprocess.Popen([binary, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = _read_cdp_ws(port)
    except Exception:
        proc.terminate()
        raise
    return proc, ws
