"""Dispatcher engine — chọn lõi browser theo tên.

camoufox  : Firefox fork, mã mở, không cần binary ngoài (khuyến nghị khi Firefox-fp ok).
botbrowser: Chromium fork, fidelity Chrome thật (cần BOTBROWSER_BIN + .enc).

Cùng hợp đồng: serve(...) -> (proc_or_server, endpoint). endpoint là ws cho automation nối vào.
"""
from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from typing import Any

from . import botbrowser, fpchromium, launcher, ovobrowser
from .db import Profile

ENGINES = ("camoufox", "ovobrowser", "fpchromium", "botbrowser")
DEFAULT_ENGINE = "camoufox"


def cleanup_orphans(profiles_root: str | Path) -> None:
    """Diệt tiến trình browser engine MỒ CÔI từ lần chạy trước (server crash/restart để lại,
    chúng giữ khoá profile -> launch mới timeout). Khớp CHÍNH XÁC theo --user-data-dir nằm trong
    profiles_root nên không đụng Chrome/Firefox thật của user. Best-effort, chỉ Windows.

    Gọi lúc server khởi động, TRƯỚC khi nhận request (lúc này running rỗng -> mọi process trỏ
    vào profiles_root đều là orphan)."""
    if os.name != "nt":
        return
    root = str(Path(profiles_root).resolve()).replace("'", "''")   # escape nháy đơn cho PowerShell
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='firefox.exe' "
        "or Name='camoufox.exe'\" | "
        f"Where-Object {{ $_.CommandLine -and $_.CommandLine -like '*{root}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001  — dọn dẹp không được không làm chết server
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(engine: str, profile: Profile, profiles_root: str, *, headless: bool = True) -> tuple[Any, str]:
    """Trả (handle, endpoint). handle có .terminate() để stop."""
    engine = (engine or DEFAULT_ENGINE).lower()
    storage = profile.storage_path or profile.id
    if engine == "camoufox":
        return launcher.serve_profile(profile, profiles_root, headless=headless)
    if engine == "ovobrowser":
        return ovobrowser.serve(
            profile.fingerprint_data, profile.dynamic_data, profiles_root,
            storage_name=storage, headless=headless, port=_free_port())
    if engine == "fpchromium":
        return fpchromium.serve(
            profile.fingerprint_data, profile.dynamic_data, profiles_root,
            storage_name=storage, headless=headless, port=_free_port())
    if engine == "botbrowser":
        return botbrowser.serve(
            profile.fingerprint_data, profile.dynamic_data, profiles_root,
            storage_name=storage, headless=headless, port=_free_port())
    raise ValueError(f"engine không hỗ trợ: {engine!r} (chọn: {ENGINES})")


_CHROMIUM = ("ovobrowser", "fpchromium", "botbrowser")


def graceful_stop(handle: Any, endpoint: str, engine: str) -> None:
    """Đóng profile sạch. Chromium: gửi CDP Browser.close (Chrome exit bình thường, không bị
    'didn't shut down correctly') rồi mới terminate. Lỗi/engine khác -> terminate thẳng."""
    if engine in _CHROMIUM and endpoint:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.connect_over_cdp(endpoint)
                try:
                    b.new_browser_cdp_session().send("Browser.close")   # Chrome tự thoát sạch
                except Exception:  # noqa: BLE001
                    b.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        handle.terminate()           # chắc chắn tắt + dọn relay (RelayHandle); no-op nếu đã thoát
    except Exception:  # noqa: BLE001
        pass


def resolve_engine(profile: Profile, requested: str | None) -> str:
    """Ưu tiên: request > dynamic_data.engine > theo skin trình duyệt.

    Firefox -> luôn camoufox (Gecko thật). Chromium skin -> botbrowser nếu có binary,
    chưa có binary thì rơi về camoufox (chạy được nhưng ra Firefox — xem warnings).
    """
    import os

    from . import browser_profiles
    if requested:
        return requested
    saved = (profile.dynamic_data or {}).get("engine")
    if saved:
        return saved
    btype = ((profile.fingerprint_data or {}).get("browser", {}) or {}).get("browser_type", "Chrome")
    if browser_profiles.identity(btype).kind == "firefox":
        return "camoufox"
    # Chromium skin: ưu tiên ovobrowser (mở, ổn định, fidelity đủ) > fpchromium > BotBrowser > Camoufox.
    if os.environ.get("OVOBROWSER_BIN"):
        return "ovobrowser"
    if os.environ.get("FPCHROMIUM_BIN"):
        return "fpchromium"
    if os.environ.get("BOTBROWSER_BIN"):
        return "botbrowser"
    return DEFAULT_ENGINE
