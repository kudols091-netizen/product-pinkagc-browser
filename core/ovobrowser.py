"""Engine ovobrowser — lõi Chromium fingerprint source-level, mã mở, miễn phí, ỔN ĐỊNH.

Khác fingerprint-chromium (crash canvas ~2/3 seed): ovobrowser căn canvas main-thread+Worker
-> 4/4 không crash (đã verify qua cổng Pha A). Flag khớp mô hình GPM gần 1:1: noise theo TỪNG
nhóm (Canvas/WebGL/Audio/ClientRects/Font) + device-memory + gpu vendor/renderer + screen.

TRỌNG YẾU (README ovo): `--fingerprint=N` một mình KHÔNG bật noise — phải truyền từng cờ
`--fingerprint-canvas=<seed>` ... để mỗi account ra một visitor khác. Bật noise/gpu-spoof =
đổi visitor (đúng nhu cầu đa tài khoản), đổi lại FingerprintJS Pro có thể gắn cờ "tampering"
— đánh đổi kinh điển của antidetect, giống GPM.

Flag đã verify từ README ovobrowser. Binary qua env: OVOBROWSER_BIN.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from . import proxy_providers
from .botbrowser import _read_cdp_ws
from .fingerprint import NormalizedFingerprint, parse_gpm
from .proxy_relay import RelayHandle, maybe_relay

_PLATFORM = {"windows": "windows", "macos": "macos", "linux": "linux"}
_BRAND = {"chrome": "Chrome", "edge": "Edge", "opera": "Opera", "brave": "Chrome", "vivaldi": "Vivaldi"}
_NOISE = ("canvas", "webgl", "audio", "rects", "font")   # 5 nhóm noise độc lập


def seed_for(name: str) -> int:
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % (2 ** 31)


def build_args(n: NormalizedFingerprint, *, seed: int, user_data_dir: str, port: int,
               brand_version: str | None = None, noise: bool = True,
               headless: bool = True) -> list[str]:
    args = [
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run", "--no-default-browser-check", "--no-sandbox", "--disable-quic",
        "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",   # ẩn 'Restore pages?' (Chrome 150 dùng flag sau)
        f"--fingerprint-platform={_PLATFORM.get(n.os_type, 'windows')}",
    ]
    brand = _BRAND.get(n.browser_kind, "Chrome")
    args.append(f"--fingerprint-brand={brand}")
    if brand_version:
        args.append(f"--fingerprint-brand-version={brand_version}")
    if n.hardware_concurrency:
        args.append(f"--fingerprint-hardware-concurrency={n.hardware_concurrency}")
    if n.device_memory:
        # Chrome cap deviceMemory ở 8 + chỉ nhận {0.25,0.5,1,2,4,8}; snap về giá trị hợp lệ gần nhất.
        valid = (0.25, 0.5, 1, 2, 4, 8)
        dm = min(valid, key=lambda v: abs(v - n.device_memory))
        args.append(f"--fingerprint-device-memory={dm:g}")
    if n.webgl_vendor and n.webgl_renderer:        # spoof GPU theo webgl_meta_data của GPM
        args.append(f"--fingerprint-gpu-vendor={n.webgl_vendor}")
        args.append(f"--fingerprint-gpu-renderer={n.webgl_renderer}")
    if n.screen_wh:
        args.append(f"--fingerprint-screen={n.screen_wh[0]}x{n.screen_wh[1]}")
    if n.color_depth:
        args.append(f"--fingerprint-screen-color-depth={n.color_depth}")
    if n.language:
        args += [f"--lang={n.language}", f"--accept-lang={n.language}"]
    if n.timezone:
        args.append(f"--timezone={n.timezone}")
    if n.do_not_track:
        args.append("--fingerprint-dnt")
    if n.user_agent:
        args.append(f"--user-agent={n.user_agent}")
    args += ["--fingerprint-disable-bluetooth", "--fingerprint-webgpu"]
    if n.proxy:
        # Chống rò DNS: tắt DoH (Chrome đi DNS-over-HTTPS thẳng, không qua proxy) + tắt prefetch.
        # Qua proxy HTTP(relay)->socks5 remote-DNS nên resolver nằm ở exit IP, cùng quốc gia proxy.
        args += ["--disable-features=DnsOverHttps", "--dns-prefetch-disable"]
    if noise:
        # Mỗi nhóm một seed dẫn xuất ổn định từ account seed -> cùng account cùng fingerprint.
        for i, cat in enumerate(_NOISE):
            args.append(f"--fingerprint-{cat}={(seed + i * 101) % (2 ** 31)}")
    if headless:
        args += ["--headless=new", "--enable-unsafe-swiftshader"]
    if n.proxy:
        # Proxy có auth đã được maybe_relay() đổi sang relay cục bộ không-auth; ở đây chỉ còn host:port.
        args.append(f"--proxy-server={n.proxy['server']}")
    return args


def serve(profile_fp: dict, profile_dyn: dict, profiles_root: str | Path, *,
          storage_name: str, headless: bool = True, port: int = 9222,
          seed: int | None = None, noise: bool = True) -> tuple[Any, str]:
    """Spawn ovobrowser, trả (proc, cdp_ws). Cần OVOBROWSER_BIN."""
    from . import engine_store                   # khoá version per-profile: dùng binary của engine_version nếu đã tải
    binary = engine_store.resolve_binary((profile_dyn or {}).get("engine_version"))
    if not binary or not Path(binary).exists():
        raise RuntimeError("Chưa cấu hình engine (OVOBROWSER_BIN) hoặc version đã chọn chưa tải về.")
    n = parse_gpm(profile_fp, profile_dyn)
    if seed is None:
        seed = (profile_dyn or {}).get("fp_seed") or seed_for(storage_name)
    # KHÔNG ép brand-version: --fingerprint-brand-version chỉ đổi Sec-CH-UA chứ không đổi navigator.userAgent
    # -> UA(binary) ≠ Sec-CH-UA(ép) = inconsistency scanner bắt. Để native: cả hai cùng version binary.
    bver = None

    if n.timezone is None and n.proxy:           # auto-timezone: khớp giờ với IP proxy (chống rò mismatch)
        tz = proxy_providers.geo_timezone(n.proxy)
        if tz:
            n.timezone = tz
    n.proxy, relay = maybe_relay(n.proxy)        # proxy có user:pass -> relay cục bộ (Chromium bỏ qua cred)
    udd = Path(profiles_root) / storage_name
    udd.mkdir(parents=True, exist_ok=True)
    args = build_args(n, seed=int(seed), user_data_dir=str(udd), port=port,
                      brand_version=bver, noise=noise, headless=headless)
    webrtc_mode = str(((profile_fp or {}).get("webrtc", {}) or {}).get("mode", "BaseOnIp")).lower()
    if webrtc_mode != "real":
        args.append("--webrtc-ip-handling-policy=disable_non_proxied_udp")
    if (profile_dyn or {}).get("limit_window") and n.screen_wh and not headless:
        args.append(f"--window-size={n.screen_wh[0]},{n.screen_wh[1]}")
    exts = [e for e in ((profile_dyn or {}).get("extensions") or []) if Path(e).is_dir()]
    if exts:                                      # nạp extension unpacked (--headless=new hỗ trợ)
        args += [f"--load-extension={','.join(exts)}", f"--disable-extensions-except={','.join(exts)}"]
    if (profile_dyn or {}).get("save_bandwidth"):          # tiết kiệm băng thông: chặn tải ảnh (farm nhiều nick)
        args.append("--blink-settings=imagesEnabled=false")
    fc = (profile_dyn or {}).get("fake_camera")            # camera/mic giả: feed file vào getUserMedia (KYC/liveness)
    fm = (profile_dyn or {}).get("fake_mic")
    if fc or fm:
        args += ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        if fc and Path(fc).is_file():
            args.append(f"--use-file-for-fake-video-capture={fc}")   # .y4m
        if fm and Path(fm).is_file():
            args.append(f"--use-file-for-fake-audio-capture={fm}")   # .wav
    args += [a for a in str((profile_dyn or {}).get("chrome_params") or "").split() if a]   # flag tuỳ chỉnh
    raw_urls = (profile_dyn or {}).get("start_url") or (profile_fp or {}).get("startup_urls") or ""
    starturls = [u for u in str(raw_urls).split() if u]    # URL khởi động
    proc = subprocess.Popen([binary, *args, *starturls], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = _read_cdp_ws(port)
    except Exception:
        proc.terminate()
        if relay: relay.terminate()
        raise
    return (RelayHandle(proc, relay) if relay else proc), ws
