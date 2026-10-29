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
from pathlib import Path
from typing import Any, Iterator

from .db import Database, Profile
from .fingerprint import to_camoufox, parse_gpm


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


# --- serve mode: 1 ws endpoint cho mỗi profile (như remote debugging address của GPM) ---

_WS_RE = re.compile(rb"(ws://[^\s'\"]+)")


def serve_profile(profile: Profile, profiles_root: str | Path, *,
                  headless: bool = True, port: int = 0) -> tuple[subprocess.Popen, str]:
    """Spawn camoufox launch_server ở tiến trình riêng, trả (proc, ws_endpoint).

    Dùng launch_server của camoufox (phát 1 Playwright BrowserServer ws endpoint).
    """
    kwargs, _ = build_launch_kwargs(profile, profiles_root, headless=headless)
    kwargs["port"] = port
    code = (
        "import json,sys;from camoufox.server import launch_server;"
        f"launch_server(**json.loads({json.dumps(json.dumps(kwargs))}))"
    )
    proc = subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.stdout is not None
    for _ in range(200):                       # đợi ws endpoint in ra (tối đa ~ vài giây/dòng)
        line = proc.stdout.readline()
        if not line:
            break
        m = _WS_RE.search(line)
        if m:
            return proc, m.group(1).decode()
    proc.terminate()
    raise RuntimeError("Không lấy được ws endpoint từ camoufox launch_server")
