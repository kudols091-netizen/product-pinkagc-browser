"""Tự cập nhật (Windows, bản đóng gói .exe).

Luồng: app khách đọc manifest `brand.UPDATE_URL` (JSON {version,url,notes}). Nếu version > hiện tại
-> tải .exe mới cạnh exe đang chạy -> dựng `_update.bat` chờ app thoát, thay exe, khởi động lại.
Dev (`python -m core.api`) không self-update: báo dùng `git pull`.

Bạn phát hành: tăng brand.VERSION -> build exe -> upload exe + version.json lên host (UPDATE_URL).
Mọi máy khách sẽ thấy và tự cập nhật. "Update ở máy mình -> khách update luôn."
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import brand

_CREATE_NO_WINDOW = 0x08000000


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def check() -> dict:
    """So brand.VERSION với manifest UPDATE_URL. Thuần stdlib."""
    url = getattr(brand, "UPDATE_URL", "")
    if not url:
        return {"current": brand.VERSION, "has_update": False, "reason": "chưa cấu hình UPDATE_URL"}
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"current": brand.VERSION, "has_update": False, "error": str(e)}
    latest = str(info.get("version", ""))
    return {"current": brand.VERSION, "latest": latest,
            "has_update": bool(latest) and _ver_tuple(latest) > _ver_tuple(brand.VERSION),
            "url": info.get("url", ""), "notes": info.get("notes", "")}


def apply_update(dl_url: str) -> tuple[bool, str]:
    """Tải exe mới + dựng .bat thay nóng + hẹn khởi động lại. CHỈ bản đóng gói.
    Trả (ok, message). Nếu ok, app NÊN tự thoát ngay sau để .bat thay được file."""
    if not is_frozen():
        return False, "Bản dev: dùng `git pull` để cập nhật (self-update chỉ áp cho bản .exe đóng gói)."
    if not dl_url:
        return False, "Manifest thiếu 'url' (link tải .exe mới)."
    exe = Path(sys.executable)                       # PinkAgcBrowser.exe đang chạy
    new = exe.with_name(exe.stem + "_new.exe")
    try:
        urllib.request.urlretrieve(dl_url, new)      # tải cạnh exe
    except Exception as e:  # noqa: BLE001
        return False, f"Tải thất bại: {e}"
    if new.stat().st_size < 1024:
        new.unlink(missing_ok=True)
        return False, "File tải về rỗng/hỏng."
    bat = exe.with_name("_update.bat")
    bat.write_text(
        "@echo off\r\n"
        "timeout /t 2 >nul\r\n"
        ":wait\r\n"
        f'tasklist /fi "imagename eq {exe.name}" | find /i "{exe.name}" >nul '
        "&& (timeout /t 1 >nul & goto wait)\r\n"
        f'move /y "{new.name}" "{exe.name}" >nul\r\n'
        f'start "" "{exe.name}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe.parent), creationflags=_CREATE_NO_WINDOW)
    return True, "Đã tải bản mới — app sẽ đóng rồi tự cài & mở lại trong vài giây."


if __name__ == "__main__":
    print("frozen:", is_frozen())
    print("check :", check())
