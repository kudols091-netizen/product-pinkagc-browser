"""Launcher — mở profile bằng Camoufox, trả session điều khiển được.

2 chế độ (ánh xạ GPM StartProfile):
  open_profile()  : context manager interactive, trả Playwright Browser/Context.
  serve_profile() : spawn 1 ws-endpoint server (như GPM trả remote_debugging_address),
                    cho automation từ xa nối vào. Dùng trong api.py.
"""
from __future__ import annotations

import contextlib
import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

from .db import Database, Profile
from .fingerprint import to_camoufox, parse_gpm
from .proxy_relay import maybe_relay


def _profile_dir(profiles_root: str | Path, profile: Profile) -> str:
    d = Path(profiles_root) / (profile.storage_path or profile.id)
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def build_launch_kwargs(profile: Profile, profiles_root: str | Path, *,
                        headless: bool = False, humanize: bool = True) -> tuple[dict, list[str]]:
    n = parse_gpm(profile.fingerprint_data, profile.dynamic_data)
    kwargs = to_camoufox(n, headless=headless, humanize=humanize,
                         user_data_dir=_profile_dir(profiles_root, profile))
    return kwargs, n.warnings


@contextlib.contextmanager
def open_profile(db: Database, profile: Profile, profiles_root: str | Path, *,
                 headless: bool = False) -> Iterator[Any]:
    """Mở profile tương tác. `with open_profile(...) as browser: page = browser.new_page()`."""
    kwargs, warnings = build_launch_kwargs(profile, profiles_root, headless=headless)
    for w in warnings:
        print(f"[warn] {w}", file=sys.stderr)
    db.mark_run(profile.id)
    try:
        from camoufox.sync_api import Camoufox   # lười: chỉ cần khi mở engine camoufox (exe không bundle playwright)
    except ImportError:
        raise RuntimeError("Engine camoufox cần 'camoufox'+'playwright' (bản .exe không kèm) — dùng ovobrowser/fpchromium.")
    try:
        cam = Camoufox(**kwargs)
    except ValueError as e:
        # webgl_config không khớp os -> bỏ, để Camoufox tự sinh (đừng chết vì 1 field)
        if "webgl" in str(e).lower() and "webgl_config" in kwargs:
            kwargs.pop("webgl_config")
            cam = Camoufox(**kwargs)
        else:
            raise
    with cam as browser:
        yield browser


# --- serve mode: mở camoufox giữ profile (như StartProfile của GPM) ---

# Chạy trong subprocess: mở Camoufox IN-PROCESS persistent (giữ cookies/login), in READY rồi chờ.
# Thoát (-> Firefox đóng sạch) khi: (a) parent đóng stdin [app bấm Dừng], HOẶC
# (b) user đóng cửa sổ Firefox tay -> persistent context hết page / đã close -> subprocess tự thoát
# để parent poll() bắt được (nếu không, status kẹt "Đang chạy"). Nhận kwargs qua argv[1] (json).
_CAMO_CODE = (
    "import json,sys,time,threading\n"
    "from camoufox.sync_api import Camoufox\n"
    "kw=json.loads(sys.argv[1])\n"
    "try:\n"
    "    cam=Camoufox(**kw)\n"
    "except ValueError as e:\n"
    "    if 'webgl' in str(e).lower() and 'webgl_config' in kw:\n"
    "        kw.pop('webgl_config'); cam=Camoufox(**kw)\n"
    "    else: raise\n"
    "with cam as b:\n"
    "    print('CAMOUFOX_READY', flush=True)\n"
    "    stop=threading.Event()\n"
    "    def _wait_stdin():\n"
    "        try: sys.stdin.read()\n"       # app bấm Dừng -> parent đóng stdin -> EOF
    "        except Exception: pass\n"
    "        stop.set()\n"
    "    threading.Thread(target=_wait_stdin, daemon=True).start()\n"
    "    try: b.on('close', lambda *a: stop.set())\n"   # context đóng -> dừng
    "    except Exception: pass\n"
    "    while not stop.is_set():\n"
    "        try:\n"
    "            ps=b.pages\n"              # .pages là cache (không round-trip) -> phải ping thật bên dưới
    "            if not ps: break\n"
    "            ps[0].evaluate('1')\n"     # round-trip: user đóng cửa sổ -> Firefox chết -> ném lỗi -> thoát
    "        except Exception: break\n"
    "        time.sleep(0.5)\n"
)


class _CamoufoxHandle:
    """Giữ subprocess camoufox + relay proxy (nếu có); terminate() đóng sạch cả hai (interface như Popen)."""
    def __init__(self, proc: subprocess.Popen, relay=None):
        self.proc, self.relay = proc, relay

    def terminate(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()      # tín hiệu đóng sạch: child thoát with-block -> Firefox tắt gọn
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        if self.relay:
            try:
                self.relay.terminate()
            except Exception:  # noqa: BLE001
                pass


def serve_profile(profile: Profile, profiles_root: str | Path, *,
                  headless: bool = True, port: int = 0) -> tuple[_CamoufoxHandle, str]:
    """Mở camoufox giữ profile, trả (handle, endpoint-sentinel).

    camoufox.launch_server KHÔNG serve được persistent context qua ws (giới hạn Playwright) -> mở
    IN-PROCESS persistent trong subprocess. Firefox không nhận proxy có auth/socks5-auth -> proxy auth
    đi qua relay cục bộ không-auth (như các engine Chromium). Lỗi thật của camoufox được nêu rõ.
    """
    kwargs, _ = build_launch_kwargs(profile, profiles_root, headless=headless)
    relay = None
    if kwargs.get("proxy"):
        kwargs["proxy"], relay = maybe_relay(kwargs["proxy"])   # auth -> relay http cục bộ; Firefox dùng được
    proc = subprocess.Popen([sys.executable, "-u", "-c", _CAMO_CODE, json.dumps(kwargs)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out: list[str] = []
    assert proc.stdout is not None
    ready = {"v": False}
    def _watchdog():                           # camoufox treo (proxy/mạng) mà không in READY -> readline chặn mãi
        if not ready["v"]:
            try: proc.terminate()              # terminate -> readline trả '' -> vòng thoát -> dọn + raise
            except Exception: pass             # noqa: BLE001
    wd = threading.Timer(120, _watchdog); wd.daemon = True; wd.start()
    try:
        for _ in range(400):                   # camoufox khởi động chậm (~5-20s) + in vài dòng patch fingerprint
            line = proc.stdout.readline()
            if not line:
                break
            s = line.decode(errors="replace").rstrip()
            out.append(s)
            if "CAMOUFOX_READY" in s:
                ready["v"] = True; wd.cancel()
                return _CamoufoxHandle(proc, relay), f"camoufox-local://{profile.id}"
    finally:
        wd.cancel()
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass
    if relay:
        try:
            relay.terminate()
        except Exception:  # noqa: BLE001
            pass
    tail = "\n".join(out[-15:]) or "(không có output)"
    raise RuntimeError("camoufox mở thất bại:\n" + tail)
