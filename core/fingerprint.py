"""Fingerprint bridge — phần code THẬT của clone.

Dịch `fingerprint_data` (định dạng GPM, snake_case — xem _captures/db_fingerprint_data.json)
sang launch-options mà Camoufox nhận (xác nhận từ camoufox 0.5.8: os/locale/fonts/proxy/geoip/
webgl_config + config{navigator.*, screen.*, timezone, geolocation:*, webrtc:*, mediaDevices:*}).

Thiết kế có chủ đích tách 2 bước:
    parse_gpm()   : GPM JSON  -> NormalizedFingerprint (trung lập, không dính engine)
    to_camoufox() : Normalized -> kwargs cho Camoufox()
Muốn thêm engine Chromium (BotBrowser/Orbita-open) sau này: viết thêm to_botbrowser(),
giữ nguyên parse_gpm(). Không trừu tượng hoá sớm hơn mức này.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional

from . import browser_profiles


@dataclass
class NormalizedFingerprint:
    os_type: str = "windows"               # windows | macos | linux
    is_chrome: bool = True                  # True với 4 skin Chromium; False với Firefox
    browser_kind: str = "chrome"           # chrome|edge|opera|brave|firefox (dropdown GPM)
    engine_hint: str = "botbrowser"        # engine khớp skin (firefox->camoufox, còn lại->botbrowser)
    skin_user_agent: Optional[str] = None  # UA của skin Chromium — CHỈ engine botbrowser dùng
    vendor: Optional[str] = None           # navigator.vendor
    platform: Optional[str] = None         # navigator.platform
    ua_platform: Optional[str] = None      # Sec-CH-UA-Platform
    ua_brands: Optional[list] = None       # userAgentData.brands
    has_brave_api: bool = False            # cần navigator.brave.isBrave()
    user_agent: Optional[str] = None       # UA custom do user ép (allow_custom_user_agent)
    language: Optional[str] = None          # None = auto theo IP
    auto_language: bool = True
    hardware_concurrency: Optional[int] = None
    device_memory: Optional[int] = None
    do_not_track: bool = False
    hide_media_devices: bool = False
    timezone: Optional[str] = None          # None = auto theo IP
    geolocation: Optional[tuple[float, float, float]] = None  # lat, lon, accuracy; None=auto
    webrtc_ip: Optional[str] = None
    webgl_vendor: Optional[str] = None
    webgl_renderer: Optional[str] = None
    fonts: list[str] = field(default_factory=list)
    screen_wh: Optional[tuple[int, int]] = None
    screen_avail: Optional[tuple[int, int]] = None
    color_depth: Optional[int] = None
    max_touch_points: Optional[int] = None
    port_protect: str = ""                   # "3389;5900;..." -> portProtection (botbrowser)
    mac_address: Optional[str] = None        # chỉ engine Chromium dùng; Firefox bỏ qua
    custom_dns: Optional[str] = None
    media_counts: Optional[tuple[int, int, int]] = None  # audio_in, audio_out, video_in
    proxy: Optional[dict[str, str]] = None  # Playwright format {server, username, password}
    warnings: list[str] = field(default_factory=list)


# ---------- GPM -> Normalized ----------

def _parse_proxy(raw: str) -> Optional[dict[str, str]]:
    """GPM raw_proxy -> Playwright proxy dict. Hỗ trợ host:port[:user:pass] và scheme://."""
    raw = (raw or "").strip()
    if not raw:
        return None
    scheme = "http"
    if "://" in raw:
        scheme, raw = raw.split("://", 1)
    if "@" in raw:                                  # user:pass@host:port
        creds, hostport = raw.rsplit("@", 1)
        user, _, pwd = creds.partition(":")
        host, _, port = hostport.partition(":")
        return {"server": f"{scheme}://{host}:{port}", "username": user, "password": pwd}
    parts = raw.split(":")
    if len(parts) == 2:
        host, port = parts
        return {"server": f"{scheme}://{host}:{port}"}
    if len(parts) == 4:
        host, port, user, pwd = parts
        return {"server": f"{scheme}://{host}:{port}", "username": user, "password": pwd}
    return {"server": f"{scheme}://{raw}"}


def parse_gpm(fp: dict[str, Any], dyn: dict[str, Any] | None = None) -> NormalizedFingerprint:
    nav = fp.get("navigator", {}) or {}
    tz = fp.get("timezone", {}) or {}
    geo = fp.get("geolocation", {}) or {}
    rtc = fp.get("webrtc", {}) or {}
    wm = fp.get("webgl_meta_data", {}) or {}
    font = fp.get("font", {}) or {}
    screen = fp.get("screen", {}) or {}
    media = fp.get("media_devices", {}) or {}
    browser = fp.get("browser", {}) or {}

    n = NormalizedFingerprint()
    n.os_type = str((fp.get("os", {}) or {}).get("type", "Windows")).lower()
    if n.os_type not in ("windows", "macos", "linux"):
        n.os_type = "windows"
    major = str(browser.get("browser_version", "155") or "155").split(".")[0] or "155"
    ident = browser_profiles.identity(browser.get("browser_type", "Chrome"), n.os_type,
                                      chrome_major=major)
    n.browser_kind = ident.kind
    n.engine_hint = ident.engine
    n.skin_user_agent = ident.user_agent
    n.vendor = ident.vendor
    n.platform = ident.platform
    n.ua_platform = ident.ua_platform
    n.ua_brands = ident.brands
    n.has_brave_api = ident.has_brave_api
    n.is_chrome = ident.kind in browser_profiles.CHROMIUM_KINDS
    if n.is_chrome:
        n.warnings.append(
            f"Skin Chromium ({ident.kind}) -> fidelity Chrome cần engine BotBrowser; "
            "chạy trên Camoufox sẽ ra Firefox.")

    if nav.get("allow_custom_user_agent") and nav.get("user_agent"):
        n.user_agent = nav["user_agent"]
    n.auto_language = bool(nav.get("auto_language", True))
    if not n.auto_language and nav.get("language"):
        n.language = nav["language"]
    if nav.get("hardware_concurrency"):
        n.hardware_concurrency = int(nav["hardware_concurrency"])
    if nav.get("device_memory"):
        n.device_memory = int(nav["device_memory"])
    n.do_not_track = bool(nav.get("do_not_track"))
    n.hide_media_devices = bool(nav.get("is_hide_media_devices") or media.get("is_masked"))

    if not tz.get("auto_timezone") and tz.get("timezone"):
        n.timezone = tz["timezone"]
    if not geo.get("auto_geolocation") and geo.get("latitude") is not None:
        n.geolocation = (float(geo["latitude"]), float(geo["longitude"]),
                         float(geo.get("accuracy", 100)))
    if rtc.get("public_ip"):
        n.webrtc_ip = rtc["public_ip"]

    if str(wm.get("mode", "")).lower() == "masked" and wm.get("vendor") and wm.get("renderer"):
        n.webgl_vendor, n.webgl_renderer = wm["vendor"], wm["renderer"]

    if font.get("includes"):
        n.fonts = list(font["includes"])
    w, h = screen.get("width", -1), screen.get("height", -1)
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        n.screen_wh = (w, h)
    aw, ah = screen.get("avail_width", -1), screen.get("avail_height", -1)
    if isinstance(aw, int) and isinstance(ah, int) and aw > 0 and ah > 0:
        n.screen_avail = (aw, ah)
    if isinstance(screen.get("color_depth"), int) and screen["color_depth"] > 0:
        n.color_depth = screen["color_depth"]
    if isinstance(screen.get("max_touch_points"), int):
        n.max_touch_points = screen["max_touch_points"]

    n.port_protect = str(rtc.get("port_protect", "") or "")
    n.mac_address = fp.get("mac_address") or None
    n.custom_dns = fp.get("custom_dns_server") or None
    if any(k in media for k in ("audio_inputs", "audio_outputs", "video_inputs")):
        n.media_counts = (int(media.get("audio_inputs", -1)),
                          int(media.get("audio_outputs", -1)),
                          int(media.get("video_inputs", -1)))

    dyn = dyn or {}
    n.proxy = _parse_proxy((dyn.get("proxy", {}) or {}).get("raw_proxy", ""))
    return n


# ---------- Normalized -> Camoufox kwargs ----------

def to_camoufox(n: NormalizedFingerprint, *, headless: bool = False,
                user_data_dir: str | None = None, humanize: bool = True) -> dict[str, Any]:
    # doNotTrack là chuỗi header "1"/"0" (Camoufox yêu cầu str, không phải bool).
    config: dict[str, Any] = {"navigator.doNotTrack": "1" if n.do_not_track else "0"}
    if n.user_agent:
        config["navigator.userAgent"] = n.user_agent
    if n.hardware_concurrency:
        config["navigator.hardwareConcurrency"] = n.hardware_concurrency
    if n.device_memory:
        config["navigator.deviceMemory"] = n.device_memory
    if n.timezone:
        config["timezone"] = n.timezone
    if n.geolocation:
        lat, lon, acc = n.geolocation
        config.update({"geolocation:latitude": lat, "geolocation:longitude": lon,
                       "geolocation:accuracy": acc})
    if n.webrtc_ip:
        config["webrtc:ipv6" if ":" in n.webrtc_ip else "webrtc:ipv4"] = n.webrtc_ip
    if n.hide_media_devices:
        config["mediaDevices:enabled"] = False
    if n.screen_wh:
        config["screen.width"], config["screen.height"] = n.screen_wh
    if n.screen_avail:
        config["screen.availWidth"], config["screen.availHeight"] = n.screen_avail
    if n.color_depth:
        config["screen.colorDepth"] = config["screen.pixelDepth"] = n.color_depth
    if n.max_touch_points is not None:
        config["navigator.maxTouchPoints"] = n.max_touch_points
    # mac_address / custom_dns: API của Chromium — Firefox/Camoufox không expose -> bỏ, cảnh báo.
    if (n.mac_address or n.custom_dns):
        n.warnings.append("mac_address/DNS chỉ áp dụng engine Chromium (BotBrowser), bỏ qua trên Camoufox.")

    kwargs: dict[str, Any] = {"os": n.os_type, "headless": headless, "humanize": humanize,
                              "config": config}
    if n.language:
        kwargs["locale"] = n.language
    if n.fonts:
        kwargs["fonts"] = n.fonts
    # GPU pool của ta là format Chrome/ANGLE ("Google Inc. (…)") -> KHÔNG áp cho Firefox (sẽ lộ
    # GPU kiểu Chrome trên Gecko). Để Camoufox tự sinh webgl native. Chỉ honor GPU không phải Chrome-format.
    if n.webgl_vendor and n.webgl_renderer and not n.webgl_vendor.startswith("Google Inc."):
        kwargs["webgl_config"] = (n.webgl_vendor, n.webgl_renderer)
    if n.proxy:
        kwargs["proxy"] = n.proxy
        # Có proxy mà KHÔNG ép tz/webrtc/geo thủ công -> để geoip tự khớp exit IP (Camoufox khuyến nghị).
        if not (n.timezone or n.webrtc_ip or n.geolocation):
            kwargs["geoip"] = True
    # GPM là mô hình fingerprint THỦ CÔNG per-profile. Khi ta cố ý set navigator/geo/webrtc/screen,
    # Camoufox cảnh báo "not recommended" -> xác nhận chủ đích để honor đúng cấu hình profile.
    manual_keys = {"navigator.hardwareConcurrency", "navigator.deviceMemory",
                   "navigator.userAgent", "geolocation:latitude", "webrtc:ipv4",
                   "webrtc:ipv6", "screen.width", "timezone"}
    if manual_keys & config.keys():
        kwargs["i_know_what_im_doing"] = True
    if user_data_dir:
        kwargs["user_data_dir"] = user_data_dir
        kwargs["persistent_context"] = True
    return kwargs


def gpm_to_camoufox(fp: dict, dyn: dict | None = None, **launch) -> tuple[dict, list[str]]:
    """Tiện ích 1 bước: GPM fingerprint_data -> (camoufox kwargs, warnings)."""
    n = parse_gpm(fp, dyn)
    return to_camoufox(n, **launch), n.warnings


# ---------- Generator: tạo fingerprint_data mới (định dạng GPM) ----------

_UA_CORES = [2, 4, 6, 8, 12, 16]
_MEM = [4, 8]          # Chrome cap navigator.deviceMemory ở 8 (giá trị >8 lộ giả)

# GPU THẬT (Windows, ANGLE/D3D11 — đúng format Chrome báo). device-id 0x... là PCI id thật.
_NVIDIA = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 (0x00002882) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 (0x00001F82) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 (0x00001C03) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 (0x00001F08) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]
_AMD = [
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Series (0x000067DF) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6600 (0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon(TM) Graphics (0x00001638) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]
_INTEL = [
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005917) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]
_GPU_POOL_WIN = _NVIDIA + _AMD + _INTEL

# Device archetype: GPU ↔ cores ↔ memory đi CÙNG NHAU theo mẫu máy thật (coherent), tránh combo
# vô lý (vd RTX 4060 + 2 nhân). generate() chọn 1 archetype rồi lấy trong đó.
# (screen giữ "Real" — không spoof vì window có thể > screen do DPR/maximize, tạo tell mới tệ hơn.)
_DEVICE_PROFILES_WIN = [
    # (GPU, cores, memory) — card rời = nhiều nhân + 8GB; iGPU = ít nhân hơn
    {"gpu": _NVIDIA, "cores": [8, 12, 16], "memory": [8]},
    {"gpu": _AMD,    "cores": [6, 8, 12],  "memory": [8]},
    {"gpu": _INTEL,  "cores": [4, 8],      "memory": [8, 4]},
    {"gpu": _INTEL,  "cores": [2, 4],      "memory": [4]},
]


def _pick_gpu(os_type: str) -> tuple[str, str]:
    """GPU ngẫu nhiên từ pool (chỉ Windows). Non-Windows -> ('','') = để engine dùng GPU native."""
    return random.choice(_GPU_POOL_WIN) if str(os_type).strip().lower().startswith("win") else ("", "")


def _pick_device(os_type: str) -> dict:
    """Bộ (gpu_vendor, gpu_renderer, cores, memory) COHERENT theo 1 mẫu máy thật.
    Non-Windows: không spoof GPU (để engine native), cores/memory generic."""
    if not str(os_type).strip().lower().startswith("win"):
        return {"gpu_vendor": "", "gpu_renderer": "",
                "cores": random.choice(_UA_CORES), "memory": random.choice(_MEM)}
    dev = random.choice(_DEVICE_PROFILES_WIN)
    v, r = random.choice(dev["gpu"])
    return {"gpu_vendor": v, "gpu_renderer": r,
            "cores": random.choice(dev["cores"]), "memory": random.choice(dev["memory"])}

# --- Font pools để spoof danh sách font khả dụng (chống linkability: mỗi profile một set) ---
# Base = font ship sẵn trên OS (gần như luôn có). Optional = font theo app (Office/Adobe...) chỉ 1 số máy có.
_WIN_FONTS_BASE = ["Arial", "Arial Black", "Bahnschrift", "Calibri", "Cambria", "Cambria Math", "Candara",
    "Comic Sans MS", "Consolas", "Constantia", "Corbel", "Courier New", "Ebrima", "Franklin Gothic Medium",
    "Gabriola", "Gadugi", "Georgia", "Impact", "Ink Free", "Javanese Text", "Leelawadee UI", "Lucida Console",
    "Lucida Sans Unicode", "Malgun Gothic", "Marlett", "Microsoft Himalaya", "Microsoft JhengHei",
    "Microsoft New Tai Lue", "Microsoft PhagsPa", "Microsoft Sans Serif", "Microsoft Tai Le", "Microsoft YaHei",
    "Microsoft Yi Baiti", "MingLiU-ExtB", "Mongolian Baiti", "MS Gothic", "MV Boli", "Myanmar Text", "Nirmala UI",
    "Palatino Linotype", "Segoe MDL2 Assets", "Segoe Print", "Segoe Script", "Segoe UI", "Segoe UI Emoji",
    "Segoe UI Historic", "Segoe UI Symbol", "SimSun", "Sitka", "Sylfaen", "Symbol", "Tahoma", "Times New Roman",
    "Trebuchet MS", "Verdana", "Webdings", "Wingdings", "Yu Gothic"]
_WIN_FONTS_OPT = ["Agency FB", "Algerian", "Arial Narrow", "Arial Rounded MT Bold", "Baskerville Old Face",
    "Bauhaus 93", "Bell MT", "Berlin Sans FB", "Bernard MT Condensed", "Bodoni MT", "Book Antiqua",
    "Bookman Old Style", "Bradley Hand ITC", "Britannic Bold", "Broadway", "Brush Script MT", "Calisto MT",
    "Californian FB", "Castellar", "Centaur", "Century", "Century Gothic", "Century Schoolbook", "Chiller",
    "Colonna MT", "Cooper Black", "Copperplate Gothic Bold", "Copperplate Gothic Light", "Curlz MT", "Elephant",
    "Engravers MT", "Eras Bold ITC", "Eras Light ITC", "Felix Titling", "Footlight MT Light", "Forte",
    "Franklin Gothic Book", "Franklin Gothic Demi", "Freestyle Script", "French Script MT", "Garamond", "Gigi",
    "Gill Sans MT", "Gill Sans Ultra Bold", "Goudy Old Style", "Goudy Stout", "Haettenschweiler",
    "Harlow Solid Italic", "Harrington", "High Tower Text", "Imprint MT Shadow", "Informal Roman", "Jokerman",
    "Juice ITC", "Kristen ITC", "Kunstler Script", "Wide Latin", "Lucida Bright", "Lucida Calligraphy",
    "Lucida Fax", "Lucida Handwriting", "Magneto", "Maiandra GD", "Matura MT Script Capitals", "Mistral",
    "Modern No. 20", "Monotype Corsiva", "Niagara Engraved", "Niagara Solid", "OCR A Extended",
    "Old English Text MT", "Onyx", "Palace Script MT", "Papyrus", "Parchment", "Perpetua", "Perpetua Titling MT",
    "Playbill", "Poor Richard", "Pristina", "Rage Italic", "Ravie", "Rockwell", "Rockwell Condensed",
    "Script MT Bold", "Showcard Gothic", "Snap ITC", "Stencil", "Tempus Sans ITC", "Tw Cen MT",
    "Tw Cen MT Condensed", "Viner Hand ITC", "Vivaldi", "Vladimir Script"]
_MAC_FONTS = ["American Typewriter", "Andale Mono", "Apple Chancery", "Apple Color Emoji", "Apple SD Gothic Neo",
    "AppleGothic", "Arial", "Arial Black", "Arial Narrow", "Arial Unicode MS", "Avenir", "Avenir Next",
    "Avenir Next Condensed", "Baskerville", "Big Caslon", "Bodoni 72", "Bradley Hand", "Brush Script MT",
    "Chalkboard", "Chalkboard SE", "Chalkduster", "Charter", "Cochin", "Comic Sans MS", "Copperplate",
    "Courier", "Courier New", "Didot", "DIN Alternate", "DIN Condensed", "Futura", "Geneva", "Georgia",
    "Gill Sans", "Helvetica", "Helvetica Neue", "Herculanum", "Hoefler Text", "Impact", "Lucida Grande",
    "Luminari", "Marker Felt", "Menlo", "Microsoft Sans Serif", "Monaco", "Noteworthy", "Optima", "Palatino",
    "Papyrus", "Phosphate", "PT Mono", "PT Sans", "PT Serif", "Rockwell", "Savoye LET", "SignPainter", "Skia",
    "Snell Roundhand", "Tahoma", "Times", "Times New Roman", "Trattatello", "Trebuchet MS", "Verdana", "Zapfino"]
_LINUX_FONTS = ["Bitstream Vera Sans", "Bitstream Vera Sans Mono", "Bitstream Vera Serif", "Century Schoolbook L",
    "Courier 10 Pitch", "DejaVu Sans", "DejaVu Sans Mono", "DejaVu Serif", "Dingbats", "FreeMono", "FreeSans",
    "FreeSerif", "Liberation Mono", "Liberation Sans", "Liberation Serif", "Nimbus Mono L", "Nimbus Roman No9 L",
    "Nimbus Sans L", "Noto Sans", "Noto Serif", "Noto Mono", "Standard Symbols L", "Ubuntu", "Ubuntu Condensed",
    "Ubuntu Mono", "URW Bookman L", "URW Chancery L", "URW Gothic L", "URW Palladio L"]


def _pick_fonts(os_type: str) -> list[str]:
    """Danh sách font khả dụng THỰC TẾ per-profile: base của OS (luôn có) + subset tuỳ chọn ngẫu nhiên.

    Camoufox nhận trực tiếp qua launch-option `fonts` -> trình bày đúng set này (vá leak font host thật).
    ponytail: ovobrowser/Chromium KHÔNG có cờ spoof font-set (chỉ --fingerprint-font = noise đo đạc) nên
    với Chromium list này mang tính lưu trữ/nhất quán; set-level spoof cần cờ engine mà ovobrowser chưa có.
    """
    ot = str(os_type).strip().lower()
    if ot.startswith("mac"):
        return sorted(random.sample(_MAC_FONTS, random.randint(len(_MAC_FONTS) - 8, len(_MAC_FONTS))))
    if ot.startswith("lin"):
        return sorted(random.sample(_LINUX_FONTS, random.randint(len(_LINUX_FONTS) - 6, len(_LINUX_FONTS))))
    opt = random.sample(_WIN_FONTS_OPT, random.randint(len(_WIN_FONTS_OPT) // 4, len(_WIN_FONTS_OPT) * 3 // 5))
    return sorted(set(_WIN_FONTS_BASE) | set(opt))


def generate(os_type: str = "Windows", browser_version: str = "155.0.0.0",
             browser_type: str = "Chrome") -> dict[str, Any]:
    """Sinh fingerprint_data GPM-format cho profile mới. Noise=mode an toàn mặc định.

    browser_type: Chrome|Edge|Opera|Brave|Firefox (dropdown GPM). Quyết engine lúc launch.
    """
    if browser_type.strip().lower() not in browser_profiles.ALL_KINDS:
        browser_type = "Chrome"
    dev = _pick_device(os_type)       # GPU ↔ cores ↔ memory coherent theo 1 mẫu máy thật
    gpu_vendor, gpu_renderer = dev["gpu_vendor"], dev["gpu_renderer"]
    return {
        "taskbar_title": "",
        "navigator": {
            "allow_custom_user_agent": False, "user_agent": "",
            "auto_language": True, "language": "en-US", "do_not_track": False,
            "hardware_concurrency": dev["cores"],
            "device_memory": dev["memory"],
            "js_heap_size_limit": 2248146944,
            "is_use_bluetooth": False, "is_hide_media_devices": True,
        },
        "browser": {"browser_type": browser_type, "browser_version": browser_version},
        "timezone": {"auto_timezone": True, "timezone": ""},
        "os": {"type": os_type},
        "webrtc": {"mode": "BaseOnIp", "public_ip": "", "port_protect": "3389;5900"},
        "geolocation": {"mode": "Prompt", "auto_geolocation": True,
                        "latitude": 0, "longitude": 0, "accuracy": 100},
        "canvas": {"mode": "Noise", "noise_token": random.randint(1, 2**31)},
        "client_rect": {"mode": "Noise", "noise": random.random()},
        "webgl_image": {"mode": "Noise", "noise_token": random.randint(1, 2**31)},
        "webgl_meta_data": {"mode": "Masked", "vendor": gpu_vendor, "renderer": gpu_renderer},
        "audio_context": {"mode": "Noise", "noise": random.uniform(-5, 5)},
        "screen": {"name": "Real", "width": -1, "height": -1,
                   "category": "Desktop", "max_touch_points": 0},
        "media_devices": {"is_masked": True, "audio_inputs": -1,
                          "audio_outputs": -1, "video_inputs": -1},
        "font": {"mode": "Masked", "includes": _pick_fonts(os_type), "excludes": []},
        "device_name": "", "mac_address": "", "custom_dns_server": "",
        "load_extensions": "", "startup_urls": "", "bookmarks": "",
        "features": {"disable": "", "enable": ""},
    }


_SCREENS = [(1920, 1080), (1536, 864), (1366, 768), (2560, 1440), (1440, 900)]


def randomize_fields(fp: dict[str, Any] | None, fields: list[str] | None = None) -> dict[str, Any]:
    """Random lại field fingerprint_data (editor per-field). fields=None -> random toàn bộ (giữ os/browser).

    fields hợp lệ: cores, memory, canvas, webgl, audio, rects, screen, gpu, fonts.
    """
    import copy
    base = copy.deepcopy(fp) if fp else generate()
    os_type = str((base.get("os", {}) or {}).get("type", "Windows"))
    browser = str((base.get("browser", {}) or {}).get("browser_type", "Chrome"))
    if fields is None:
        fresh = generate(os_type=os_type, browser_type=browser)
        for k in ("device_name", "mac_address", "custom_dns_server", "startup_urls", "bookmarks"):
            fresh[k] = base.get(k, fresh.get(k, ""))      # giữ dữ liệu người dùng nhập
        return fresh
    base.setdefault("navigator", {}); base.setdefault("canvas", {}); base.setdefault("webgl_image", {})
    base.setdefault("audio_context", {}); base.setdefault("client_rect", {}); base.setdefault("screen", {})
    base.setdefault("webgl_meta_data", {"mode": "Masked"})
    ops = {
        "cores":  lambda: base["navigator"].__setitem__("hardware_concurrency", random.choice(_UA_CORES)),
        "memory": lambda: base["navigator"].__setitem__("device_memory", random.choice(_MEM)),
        "canvas": lambda: base["canvas"].__setitem__("noise_token", random.randint(1, 2 ** 31)),
        "webgl":  lambda: base["webgl_image"].__setitem__("noise_token", random.randint(1, 2 ** 31)),
        "audio":  lambda: base["audio_context"].__setitem__("noise", random.uniform(-5, 5)),
        "rects":  lambda: base["client_rect"].__setitem__("noise", random.random()),
        "screen": lambda: base["screen"].update(dict(zip(("width", "height"), random.choice(_SCREENS)))),
        "gpu":    lambda: base["webgl_meta_data"].update(dict(zip(("vendor", "renderer"), _pick_gpu(os_type)))),
        "fonts":  lambda: base.__setitem__("font", {"mode": "Masked", "includes": _pick_fonts(os_type), "excludes": []}),
    }
    for f in fields:
        if f in ops:
            ops[f]()
    return base


if __name__ == "__main__":
    # Self-check: font list thực tế, khác nhau giữa profile, base luôn có, Camoufox nhận được.
    a, b = generate(os_type="Windows"), generate(os_type="Windows")
    fa, fb = a["font"]["includes"], b["font"]["includes"]
    assert set(_WIN_FONTS_BASE) <= set(fa), "base font Windows phải luôn có"
    assert fa != fb, "font set phải khác nhau giữa 2 profile (chống linkability)"
    assert fa == sorted(fa) and len(fa) == len(set(fa)), "list phải sorted + không trùng"
    assert all(f in (_WIN_FONTS_BASE + _WIN_FONTS_OPT) for f in fa), "font phải nằm trong pool hợp lệ"
    mac = generate(os_type="macOS")["font"]["includes"]
    assert mac and all(f in _MAC_FONTS for f in mac) and "Segoe UI" not in mac, "macOS không được lộ font Windows"
    n = parse_gpm(a, {})      # Camoufox lấy fonts từ font.includes
    assert n.fonts == fa, "NormalizedFingerprint.fonts phải = font.includes (Camoufox nhận)"
    assert to_camoufox(n).get("fonts") == fa, "to_camoufox phải truyền fonts cho Camoufox"
    r = randomize_fields(a, ["fonts"])
    assert r["font"]["includes"] != fa or len(_WIN_FONTS_OPT) == 0, "randomize fonts phải đổi set"
    print(f"OK - win={len(fa)} fonts (base {len(_WIN_FONTS_BASE)} + opt {len(fa)-len(_WIN_FONTS_BASE)}), "
          f"mac={len(mac)}, per-profile set differs - PASS")
