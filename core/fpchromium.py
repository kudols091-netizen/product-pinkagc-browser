"""Engine fingerprint-chromium (adryfish) — lõi Chrome THẬT, mã mở, miễn phí.

Khác BotBrowser (demo-gate) và Camoufox (Firefox): fingerprint-chromium là ungoogled-chromium
patch sẵn, spoof bằng CLI flag — KHÔNG .enc, không modal, không trả phí. Mỗi profile một
`--fingerprint=<seed>` -> fingerprint duy nhất & ỔN ĐỊNH theo seed.

Flag đã verify từ README (adryfish/fingerprint-chromium):
  --fingerprint=<int32>              bật spoof, seed quyết toàn bộ fingerprint
  --fingerprint-platform=windows|linux|macos
  --fingerprint-platform-version=<x>
  --fingerprint-brand=Chrome|Edge|Opera|Vivaldi   (KHÔNG có Brave)
  --fingerprint-brand-version=<major>
  --fingerprint-hardware-concurrency=<int>
  --lang / --accept-lang / --timezone / --proxy-server
Giới hạn đã biết: --proxy-server KHÔNG hỗ trợ user:pass (cần relay auth cục bộ ở Phase B).
GPU vendor/renderer: tự sinh theo seed (flag override bị gỡ từ Chrome 144).

Cấu hình đường dẫn binary qua env: FPCHROMIUM_BIN
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from . import proxy_providers
from .botbrowser import _read_cdp_ws          # cùng cơ chế đọc CDP ws, không viết lại
from .fingerprint import NormalizedFingerprint, parse_gpm
from .proxy_relay import RelayHandle, maybe_relay

_FPC_PLATFORM = {"windows": "windows", "macos": "macos", "linux": "linux"}
# fingerprint-chromium không có Brave -> map về Chrome (mất navigator.brave, cảnh báo).
_FPC_BRAND = {"chrome": "Chrome", "edge": "Edge", "opera": "Opera",
              "brave": "Chrome", "vivaldi": "Vivaldi"}


def seed_for(name: str) -> int:
    """Seed 32-bit ỔN ĐỊNH từ tên/id profile -> cùng profile luôn ra cùng fingerprint."""
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % (2 ** 31)


def build_args(n: NormalizedFingerprint, *, seed: int, user_data_dir: str, port: int,
               brand_version: str | None = None, headless: bool = True) -> list[str]:
    args = [
        f"--fingerprint={seed}",
        f"--fingerprint-platform={_FPC_PLATFORM.get(n.os_type, 'windows')}",
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run", "--no-default-browser-check", "--no-sandbox",
        "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",   # ẩn 'Restore pages?' (Chrome 150 dùng flag sau)
    ]
    brand = _FPC_BRAND.get(n.browser_kind)
    if brand:
        args.append(f"--fingerprint-brand={brand}")
    if brand_version:
        args.append(f"--fingerprint-brand-version={brand_version}")
    if n.hardware_concurrency:
        args.append(f"--fingerprint-hardware-concurrency={n.hardware_concurrency}")
    if n.language:
        args.append(f"--lang={n.language}")
        args.append(f"--accept-lang={n.language}")
    if n.timezone:
        args.append(f"--timezone={n.timezone}")
    if headless:
        # headless=new + WebGL cần swiftshader, nếu không GPU process crash ("Target crashed").
        args += ["--headless=new", "--enable-unsafe-swiftshader"]
    if n.proxy:
        # Proxy có auth đã được maybe_relay() đổi sang relay cục bộ không-auth; ở đây chỉ còn host:port.
        args.append(f"--proxy-server={n.proxy['server']}")
        # Chống rò DNS: tắt DoH + prefetch -> DNS đi qua proxy (remote), cùng quốc gia exit IP.
        args += ["--disable-features=DnsOverHttps", "--dns-prefetch-disable"]
    return args


def serve(profile_fp: dict, profile_dyn: dict, profiles_root: str | Path, *,
          storage_name: str, headless: bool = True, port: int = 9222,
          seed: int | None = None) -> tuple[Any, str]:
    """Spawn fingerprint-chromium, trả (proc, cdp_ws). Cần FPCHROMIUM_BIN."""
    binary = os.environ.get("FPCHROMIUM_BIN")
    if not binary or not Path(binary).exists():
        raise RuntimeError("Chưa cấu hình FPCHROMIUM_BIN (binary chrome của fingerprint-chromium).")
    n = parse_gpm(profile_fp, profile_dyn)
    if n.browser_kind == "brave":
        n.warnings.append("fingerprint-chromium không có Brave -> chạy brand Chrome (mất navigator.brave).")
    if seed is None:
        seed = (profile_dyn or {}).get("fp_seed") or seed_for(storage_name)
    # KHÔNG ép brand-version (chỉ đổi Sec-CH-UA, không đổi UA -> lệch version). Để native theo binary.
    bver = None

    if n.timezone is None and n.proxy:           # auto-timezone: khớp giờ với IP proxy (chống rò mismatch)
        tz = proxy_providers.geo_timezone(n.proxy)
        if tz:
            n.timezone = tz
    n.proxy, relay = maybe_relay(n.proxy)        # proxy có user:pass -> relay cục bộ (Chromium bỏ qua cred)
    udd = Path(profiles_root) / storage_name
    udd.mkdir(parents=True, exist_ok=True)
    args = build_args(n, seed=int(seed), user_data_dir=str(udd), port=port,
                      brand_version=bver, headless=headless)
    exts = [e for e in ((profile_dyn or {}).get("extensions") or []) if Path(e).is_dir()]
    if exts:
        args += [f"--load-extension={','.join(exts)}", f"--disable-extensions-except={','.join(exts)}"]
    args += [a for a in str((profile_dyn or {}).get("chrome_params") or "").split() if a]
    args += [u for u in str((profile_dyn or {}).get("start_url") or "").split() if u]        # URL khởi động
    if os.environ.get("FPC_DEBUG"):
        logf = open(udd / "chrome.log", "w", encoding="utf-8", errors="replace")
        print("[fpc args]", " ".join(args))
        proc = subprocess.Popen([binary, *args], stdout=logf, stderr=subprocess.STDOUT)
    else:
        proc = subprocess.Popen([binary, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = _read_cdp_ws(port)
    except Exception:
        proc.terminate()
        if relay: relay.terminate()
        raise
    return (RelayHandle(proc, relay) if relay else proc), ws
