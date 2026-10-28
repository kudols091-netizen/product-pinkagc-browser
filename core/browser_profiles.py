"""5 danh tính trình duyệt cho dropdown "Trình duyệt" (giống GPM): Chrome/Edge/Opera/Brave/Firefox.

SỰ THẬT: 4 cái đầu là CÙNG MỘT lõi Chromium (engine BotBrowser). Chúng chỉ khác nhau ở
    User-Agent + Sec-CH-UA brands (navigator.userAgentData) + navigator.vendor + bề mặt JS
        (Brave có navigator.brave.isBrave()).
Firefox là engine Gecko THẬT (engine Camoufox) — không phải UA giả trên ruột Chromium.

Đây là lớp dịch `browser_type` -> BrowserIdentity mà engine ghi ra, để một site nhìn thấy
một trình duyệt NHẤT QUÁN (UA, brands, vendor, platform khớp nhau). Giả UA mà brands không
khớp là tự lộ ở CreepJS/Pixelscan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CHROMIUM_KINDS = ("chrome", "edge", "opera", "brave")
ALL_KINDS = CHROMIUM_KINDS + ("firefox",)
LABELS = {"chrome": "Chrome", "edge": "Edge", "opera": "Opera",
          "brave": "Brave", "firefox": "Firefox"}

# os_type -> (token trong UA Chromium, navigator.platform, Sec-CH-UA-Platform)
_PLATFORM = {
    "windows": ("Windows NT 10.0; Win64; x64", "Win32", "Windows"),
    "macos":   ("Macintosh; Intel Mac OS X 10_15_7", "MacIntel", "macOS"),
    "linux":   ("X11; Linux x86_64", "Linux x86_64", "Linux"),
}
# navigator.vendor theo trình duyệt (mọi Chromium = "Google Inc."; Firefox = chuỗi rỗng)
_VENDOR = {"chrome": "Google Inc.", "edge": "Google Inc.", "opera": "Google Inc.",
           "brave": "Google Inc.", "firefox": ""}


@dataclass
class BrowserIdentity:
    kind: str                       # chrome|edge|opera|brave|firefox
    engine: str                     # botbrowser | camoufox
    user_agent: Optional[str]       # None cho firefox (để Camoufox tự sinh UA Firefox đúng)
    vendor: str
    platform: str                   # navigator.platform
    ua_platform: str                # Sec-CH-UA-Platform
    brands: Optional[list]          # userAgentData.brands; None cho firefox (FF không có API này)
    has_brave_api: bool = False


def _chromium_ua(os_tok: str, major: str, *, suffix: str = "") -> str:
    return (f"Mozilla/5.0 ({os_tok}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36{suffix}")


def _brands(kind: str, major: str, opr: str) -> list:
    # Not=A?Brand = giá trị GREASE (đổi theo bản Chromium); giữ một giá trị hợp lệ.
    grease = {"brand": "Not=A?Brand", "version": "24"}
    chromium = {"brand": "Chromium", "version": major}
    if kind == "edge":
        return [chromium, {"brand": "Microsoft Edge", "version": major}, grease]
    if kind == "opera":
        return [chromium, {"brand": "Opera", "version": opr}, grease]
    # chrome + brave: Brave cố tình giả brands của Chrome (ẩn mình)
    return [chromium, {"brand": "Google Chrome", "version": major}, grease]


def identity(browser_type: str | None, os_type: str = "windows", *,
             chrome_major: str = "155", opera_version: str | None = None) -> BrowserIdentity:
    """browser_type (Chrome/Edge/Opera/Brave/Firefox) -> BrowserIdentity khớp os."""
    kind = (browser_type or "chrome").strip().lower()
    if kind not in ALL_KINDS:
        kind = "chrome"
    os_type = (os_type or "windows").lower()
    if os_type not in _PLATFORM:
        os_type = "windows"
    ua_os, platform, ua_platform = _PLATFORM[os_type]
    major = str(chrome_major).split(".")[0] or "155"
    # Opera đánh version riêng, trễ hơn Chromium ~39 bản (vd Chromium 155 ≈ Opera 116).
    # ponytail: heuristic offset; truyền opera_version nếu cần khớp chính xác bản Opera thật.
    opr = str(opera_version) if opera_version else str(max(int(major) - 39, 1))

    if kind == "firefox":
        return BrowserIdentity(kind, "camoufox", None, _VENDOR[kind], platform,
                               ua_platform, None)

    suffix = {"chrome": "", "brave": "", "edge": f" Edg/{major}.0.0.0",
              "opera": f" OPR/{opr}.0.0.0"}[kind]
    return BrowserIdentity(
        kind=kind, engine="botbrowser",
        user_agent=_chromium_ua(ua_os, major, suffix=suffix),
        vendor=_VENDOR[kind], platform=platform, ua_platform=ua_platform,
        brands=_brands(kind, major, opr), has_brave_api=(kind == "brave"))


def options() -> list[dict]:
    """Cho UI dropdown: [{value, label, engine}] đúng thứ tự GPM."""
    return [{"value": k, "label": LABELS[k],
             "engine": "camoufox" if k == "firefox" else "chromium"} for k in ALL_KINDS]
