"""Self-check Pha A — lớp 5 skin trình duyệt + routing engine + fidelity botbrowser.
Chạy: python test_browser_profiles.py  (không cần browser/binary)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import browser_profiles as bp
from core import botbrowser, engines
from core.fingerprint import parse_gpm, generate


def test_identities():
    # 4 skin Chromium -> engine botbrowser; Firefox -> camoufox
    for k in ("chrome", "edge", "opera", "brave"):
        assert bp.identity(k).engine == "botbrowser", k
    assert bp.identity("Firefox").engine == "camoufox"
    assert bp.identity("khong-biet").kind == "chrome"          # fallback an toàn

    chrome = bp.identity("Chrome", "windows", chrome_major="155")
    assert "Chrome/155.0.0.0" in chrome.user_agent and "Edg/" not in chrome.user_agent
    assert chrome.vendor == "Google Inc." and chrome.platform == "Win32"

    edge = bp.identity("Edge", "windows", chrome_major="155")
    assert "Edg/155.0.0.0" in edge.user_agent
    assert any(b["brand"] == "Microsoft Edge" for b in edge.brands)

    opera = bp.identity("Opera", "windows", chrome_major="155")
    assert "OPR/" in opera.user_agent
    assert any(b["brand"] == "Opera" for b in opera.brands)

    brave = bp.identity("Brave", "windows", chrome_major="155")
    # Brave giả Chrome: UA = Chrome, brands = Chrome, nhưng cờ brave API bật
    assert brave.user_agent == chrome.user_agent and brave.has_brave_api
    assert not any(b["brand"] == "Brave" for b in brave.brands)

    ff = bp.identity("Firefox")
    assert ff.user_agent is None and ff.brands is None and ff.vendor == ""  # FF để Camoufox lo
    print("[ok] 5 identities (chrome/edge/opera/brave/firefox)")


def test_os_tokens():
    assert "Macintosh" in bp.identity("Chrome", "macos").user_agent
    assert bp.identity("Chrome", "macos").platform == "MacIntel"
    assert "Linux" in bp.identity("Chrome", "linux").user_agent
    print("[ok] os tokens win/mac/linux")


def test_parse_wires_skin():
    # Edge profile -> parse_gpm gắn đúng skin + brands + is_chrome
    fp = generate("Windows", browser_type="Edge")
    n = parse_gpm(fp, {})
    assert n.browser_kind == "edge" and n.is_chrome and n.engine_hint == "botbrowser"
    assert "Edg/" in (n.skin_user_agent or "")
    assert any(b["brand"] == "Microsoft Edge" for b in (n.ua_brands or []))
    assert n.warnings, "skin Chromium phải cảnh báo cần botbrowser"

    # Firefox profile -> không là chrome, không warning-chromium, engine camoufox
    nff = parse_gpm(generate("Windows", browser_type="Firefox"), {})
    assert not nff.is_chrome and nff.engine_hint == "camoufox"
    assert not any("Chromium" in w for w in nff.warnings)
    print("[ok] parse_gpm wires skin + brands + routing")


def test_botbrowser_emits_skin():
    n = parse_gpm(generate("Windows", browser_type="Edge"), {})
    cfg = botbrowser.to_botbrowser_configs(n)
    assert "Edg/" in cfg["userAgent"]
    assert cfg["userAgentData"]["platform"] == "Windows"
    assert any(b["brand"] == "Microsoft Edge" for b in cfg["userAgentData"]["brands"])
    assert cfg["vendor"] == "Google Inc." and cfg["platform"] == "Win32"
    # Brave -> cờ brave bật
    assert botbrowser.to_botbrowser_configs(parse_gpm(generate(browser_type="Brave"), {}))["brave"]
    print("[ok] botbrowser configs carry UA+brands+vendor+platform per skin")


def test_engine_routing():
    import os
    os.environ.pop("BOTBROWSER_BIN", None)

    class P:  # Firefox -> luôn camoufox, kể cả khi có binary
        fingerprint_data = generate(browser_type="Firefox"); dynamic_data = {}
    os.environ["BOTBROWSER_BIN"] = "x"
    assert engines.resolve_engine(P(), None) == "camoufox"

    class C:  # Edge + binary -> botbrowser
        fingerprint_data = generate(browser_type="Edge"); dynamic_data = {}
    assert engines.resolve_engine(C(), None) == "botbrowser"
    os.environ.pop("BOTBROWSER_BIN", None)
    assert engines.resolve_engine(C(), None) == "camoufox"       # chưa binary -> fallback
    print("[ok] engine routing firefox/chromium")


if __name__ == "__main__":
    test_identities()
    test_os_tokens()
    test_parse_wires_skin()
    test_botbrowser_emits_skin()
    test_engine_routing()
    print("\nALL BROWSER-PROFILE CHECKS PASSED")
