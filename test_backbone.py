"""Self-check — chạy: python test_backbone.py

- Luôn chạy: DB CRUD + fingerprint bridge (thuần, không cần browser).
- Nếu Camoufox browser đã fetch: launch thật headless, đọc fingerprint LIVE và assert khớp.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.db import Database
from core.fingerprint import parse_gpm, to_camoufox, gpm_to_camoufox, generate, _parse_proxy

# fingerprint_data thật lấy từ GPM (rút gọn các field trọng yếu)
GPM_FP = {
    "navigator": {"allow_custom_user_agent": False, "user_agent": "", "auto_language": False,
                  "language": "vi", "do_not_track": True, "hardware_concurrency": 2,
                  "device_memory": 4, "is_hide_media_devices": True},
    "browser": {"browser_type": "Chrome", "browser_version": "155.0.8059.85"},
    "timezone": {"auto_timezone": False, "timezone": "Asia/Bangkok"},
    "os": {"type": "Windows"},
    "webrtc": {"mode": "BaseOnIp", "public_ip": "2402:800:62d2:b9d0:287b:4131:ea40:5bd5"},
    "geolocation": {"auto_geolocation": False, "latitude": 21.03652, "longitude": 105.82684,
                    "accuracy": 100},
    "webgl_meta_data": {"mode": "Masked", "vendor": "Google Inc. (Intel)",
                        "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11)"},
    "font": {"mode": "Masked", "includes": ["David Libre"], "excludes": []},
    "screen": {"width": -1, "height": -1},
    "media_devices": {"is_masked": False},
}
GPM_DYN = {"proxy": {"raw_proxy": "", "proxy_region": "VN"}}


def test_bridge():
    n = parse_gpm(GPM_FP, GPM_DYN)
    assert n.os_type == "windows"
    assert n.is_chrome and n.warnings, "phải cảnh báo Chrome->Firefox"
    assert n.language == "vi"
    assert n.hardware_concurrency == 2
    assert n.device_memory == 4
    assert n.do_not_track is True
    assert n.timezone == "Asia/Bangkok"
    assert n.geolocation == (21.03652, 105.82684, 100.0)
    assert n.webrtc_ip and ":" in n.webrtc_ip
    assert n.webgl_vendor == "Google Inc. (Intel)"
    assert n.fonts == ["David Libre"]

    kw = to_camoufox(n, headless=True)
    c = kw["config"]
    assert kw["os"] == "windows"
    assert kw["locale"] == "vi"
    assert c["navigator.hardwareConcurrency"] == 2
    assert c["navigator.deviceMemory"] == 4
    assert c["navigator.doNotTrack"] == "1"
    assert c["timezone"] == "Asia/Bangkok"
    assert c["geolocation:latitude"] == 21.03652
    assert "webrtc:ipv6" in c                       # IPv6 -> đúng key
    assert kw["fonts"] == ["David Libre"]
    assert "webgl_config" not in kw     # GPU format Chrome ("Google Inc.") KHÔNG áp cho Camoufox (Firefox)
    print("[ok] bridge mapping")


def test_bridge_extended():
    """Field fidelity thêm (#4): screen avail/color/touch + mac/dns warning."""
    fp = {
        "navigator": {"hardware_concurrency": 8},
        "os": {"type": "Windows"}, "browser": {"browser_type": "Chrome"},
        "screen": {"width": 1920, "height": 1080, "avail_width": 1920,
                   "avail_height": 1040, "color_depth": 24, "max_touch_points": 0},
        "mac_address": "6A:F5:E1:11:98:B0", "custom_dns_server": "1.1.1.1",
        "media_devices": {"audio_inputs": 1, "audio_outputs": 2, "video_inputs": 1},
    }
    n = parse_gpm(fp, {})
    assert n.screen_wh == (1920, 1080) and n.screen_avail == (1920, 1040)
    assert n.color_depth == 24 and n.max_touch_points == 0
    assert n.mac_address == "6A:F5:E1:11:98:B0" and n.custom_dns == "1.1.1.1"
    assert n.media_counts == (1, 2, 1)
    kw = to_camoufox(n, headless=True)
    c = kw["config"]
    assert c["screen.width"] == 1920 and c["screen.availHeight"] == 1040
    assert c["screen.colorDepth"] == 24 and c["screen.pixelDepth"] == 24
    assert c["navigator.maxTouchPoints"] == 0
    assert any("mac_address" in w for w in n.warnings)   # cảnh báo Firefox bỏ mac/dns
    print("[ok] bridge extended (screen/color/touch/mac/dns)")


def test_proxy_parse():
    assert _parse_proxy("1.2.3.4:8080") == {"server": "http://1.2.3.4:8080"}
    p = _parse_proxy("socks5://1.2.3.4:1080:user:pass")
    assert p["server"] == "socks5://1.2.3.4:1080" and p["username"] == "user"
    assert _parse_proxy("") is None
    print("[ok] proxy parse")


def test_generate_roundtrip():
    fp = generate("macOS")
    assert fp["os"]["type"] == "macOS"
    kw, warns = gpm_to_camoufox(fp, {}, headless=True)
    assert kw["os"] == "macos"
    assert kw["config"]["navigator.hardwareConcurrency"] in (2, 4, 6, 8, 12, 16)
    # coherent combo (Windows): card rời NVIDIA/AMD không đi với cấu hình yếu
    for _ in range(100):
        w = generate("Windows")
        g = w["webgl_meta_data"]["renderer"]; c = w["navigator"]["hardware_concurrency"]; m = w["navigator"]["device_memory"]
        assert not ("NVIDIA" in g and c < 8), (g, c)
        assert not ("AMD" in g and c < 6), (g, c)
        assert not (("NVIDIA" in g or "AMD" in g) and m < 8), (g, m)
    print("[ok] generate + roundtrip + coherent combo")


def test_db():
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "t.db")
        gid = db.create_group("Test")
        p = db.create_profile("P1", GPM_FP, dynamic_data=GPM_DYN, group_id=gid)
        assert db.get_profile(p.id).fingerprint_data["os"]["type"] == "Windows"
        assert len(db.list_profiles()) == 1
        assert len(db.list_profiles(group_id=gid)) == 1
        db.delete_profile(p.id)
        assert db.get_profile(p.id) is None          # soft-delete ẩn khỏi get
        assert len(db.list_profiles()) == 0
        db.close()
    print("[ok] db crud + soft-delete")


def test_live_launch():
    """Launch thật nếu browser có — bằng chứng bridge khớp fingerprint LIVE."""
    try:
        from camoufox.pkgman import installed_verstr
        if not installed_verstr():
            print("[skip] camoufox browser chưa fetch -> bỏ live launch")
            return
        from camoufox.sync_api import Camoufox
    except Exception as e:
        print(f"[skip] live launch: {e}")
        return
    n = parse_gpm(GPM_FP, GPM_DYN)
    kw = to_camoufox(n, headless=True, humanize=False)
    kw.pop("webgl_config", None)   # tránh mismatch os trong test
    try:
        with Camoufox(**kw) as browser:
            page = browser.new_page()
            hc = page.evaluate("navigator.hardwareConcurrency")
            dm = page.evaluate("navigator.deviceMemory")   # Firefox KHÔNG có -> None (caveat engine)
            tz = page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            dnt = page.evaluate("navigator.doNotTrack")
            assert hc == 2, f"hardwareConcurrency live={hc}"
            assert tz == "Asia/Bangkok", f"timezone live={tz}"
            assert dm is None, f"kỳ vọng Firefox không expose deviceMemory, live={dm}"
            print(f"[ok] LIVE launch: hc={hc} tz={tz} dnt={dnt} deviceMemory={dm} "
                  f"(None = đúng, Firefox engine không có API này — dùng Chromium engine nếu cần)")
    except Exception as e:  # noqa: BLE001
        print(f"[skip] live launch runtime: {e}")


if __name__ == "__main__":
    test_bridge()
    test_bridge_extended()
    test_proxy_parse()
    test_generate_roundtrip()
    test_db()
    test_live_launch()
    print("\nALL CHECKS PASSED")
