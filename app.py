"""Entry-point desktop — khởi động server + tự mở trình duyệt.

Dùng cho cả chạy dev (`python app.py`) lẫn bản đóng gói PyInstaller (double-click .exe).
run.bat có thể gọi file này thay cho `python -m core.api` để có trải nghiệm "mở phát chạy luôn".
"""
from __future__ import annotations

import glob
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Thư mục gốc: cạnh .exe khi đóng gói, cạnh file này khi chạy dev. asset/ profiles/ ghi ở đây.
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
os.chdir(BASE)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Tự dò binary ovobrowser trong vendor/ cạnh app nếu người dùng chưa set OVOBROWSER_BIN.
if not os.environ.get("OVOBROWSER_BIN"):
    hits = glob.glob(str(BASE / "vendor" / "ovobrowser" / "**" / "chrome.exe"), recursive=True)
    if hits:
        os.environ["OVOBROWSER_BIN"] = hits[0]

from core import brand                                   # noqa: E402
from core.api import create_app                          # noqa: E402

PORT = brand.DEFAULT_PORT
URL = f"http://127.0.0.1:{PORT}/"


def _serve() -> None:
    Path("asset/profiles").mkdir(parents=True, exist_ok=True)
    from core import engines
    engines.cleanup_orphans("asset/profiles")            # dọn browser mồ côi lần trước
    create_app(brand.DEFAULT_DB, "asset/profiles").run(host="127.0.0.1", port=PORT, threaded=True)


def main() -> None:
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    import urllib.request
    for _ in range(50):                                  # chờ server sẵn sàng (tối đa ~10s)
        try:
            urllib.request.urlopen(URL, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    print(f"{brand.APP_NAME} v{brand.VERSION}\n{URL}")
    try:
        webbrowser.open(URL)
    except Exception:
        pass
    try:
        while t.is_alive():
            t.join(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
