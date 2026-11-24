"""Self-check phần A (botbrowser + engine) + C (proxy providers) + API smoke.
Chạy: python test_extras.py  (không cần browser/binary ngoài)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import botbrowser, engines, proxy_providers
from core.fingerprint import parse_gpm

FP = {
    "navigator": {"hardware_concurrency": 8, "device_memory": 16},
    "browser": {"browser_type": "Chrome", "browser_version": "155.0.8059.85"},
    "os": {"type": "Windows"},
    "timezone": {"auto_timezone": False, "timezone": "Asia/Bangkok"},
    "geolocation": {"auto_geolocation": False, "latitude": 21.0, "longitude": 105.8, "accuracy": 50},
    "webrtc": {"public_ip": "1.2.3.4", "port_protect": "3389;5900;19995"},
    "mac_address": "6A:F5:E1:11:98:B0", "custom_dns_server": "1.1.1.1",
}


def test_botbrowser_configs():
    n = parse_gpm(FP, {})
    cfg = botbrowser.to_botbrowser_configs(n)
    assert cfg["timezone"] == "Asia/Bangkok"
    assert cfg["geolocation"]["latitude"] == 21.0
    assert cfg["portProtection"] == [3389, 5900, 19995]
    assert cfg["hardwareConcurrency"] == 8 and cfg["deviceMemory"] == 16
    assert cfg["macAddress"] == "6A:F5:E1:11:98:B0" and cfg["dnsServer"] == "1.1.1.1"
    assert cfg["webrtcIp"] == "1.2.3.4"
    args = botbrowser.build_args(n, bot_profile="x.enc", user_data_dir="d", port=9333, headless=True)
    assert "--bot-profile=x.enc" in args
    assert "--remote-debugging-port=9333" in args
    assert "--headless=new" in args
    # proxy vào CLI: BotBrowser nhúng credential trong URL (không có --proxy-username rời)
    n.proxy = {"server": "http://1.2.3.4:8080", "username": "u", "password": "p"}
    a2 = botbrowser.build_args(n, bot_profile="x.enc", user_data_dir="d", port=1, headless=False)
    assert "--proxy-server=http://u:p@1.2.3.4:8080" in a2
    assert not any(x.startswith("--proxy-username") for x in a2)
    from core import ovobrowser
    n.user_agent = "CustomAgent/2.0"
    ovo_args = ovobrowser.build_args(n, seed=123, user_data_dir="d", port=9222, headless=True)
    assert "--user-agent=CustomAgent/2.0" in ovo_args
    print("[ok] botbrowser + ovobrowser configs + args")


def test_pick_profile():
    with tempfile.TemporaryDirectory() as d:
        for f in ("chrome155_win11_x64.enc", "chrome155_mac_x64.enc", "chrome150_win11_x64.enc"):
            (Path(d) / f).write_bytes(b"x")
        n = parse_gpm(FP, {})
        picked = botbrowser.pick_profile(n, d, chrome_major="155")
        assert picked and "win" in picked.lower() and "155" in picked
        assert botbrowser.pick_profile(n, "/nonexistent") is None
    print("[ok] botbrowser pick .enc")


def test_engine_resolve():
    import os
    class P:
        fingerprint_data = FP; dynamic_data = {}
    os.environ.pop("BOTBROWSER_BIN", None)
    assert engines.resolve_engine(P(), None) == "camoufox"       # Chrome nhưng chưa có binary
    assert engines.resolve_engine(P(), "botbrowser") == "botbrowser"
    P.dynamic_data = {"engine": "camoufox"}
    assert engines.resolve_engine(P(), None) == "camoufox"
    os.environ["BOTBROWSER_BIN"] = "x"
    P.dynamic_data = {}
    assert engines.resolve_engine(P(), None) == "botbrowser"     # Chrome + binary -> botbrowser
    os.environ.pop("BOTBROWSER_BIN", None)
    print("[ok] engine resolve")


def test_proxy_parse_shapes():
    ex = proxy_providers._extract_proxy
    assert ex({"proxy": "1.2.3.4:8080"}) == "1.2.3.4:8080"
    assert ex({"data": {"proxyhttp": "5.6.7.8:3128:u:p"}}) == "5.6.7.8:3128:u:p"
    assert ex("socks5://9.9.9.9:1080") == "socks5://9.9.9.9:1080"
    assert ex({"status": "ok", "result": ["10.0.0.1:9000"]}) == "10.0.0.1:9000"
    assert ex({"msg": "no proxy"}) is None
    # get_current/rotate với fetcher giả
    fake = lambda url: {"proxy": "11.22.33.44:8000"}
    assert proxy_providers.get_current("tinproxy", "k", _fetcher=fake) == "http://11.22.33.44:8000"
    assert proxy_providers.rotate("kiotproxy", "k", _fetcher=lambda u: "socks5://1.1.1.1:1080") \
        == "socks5://1.1.1.1:1080"
    print("[ok] proxy parse + providers")


def test_api_smoke():
    from core.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        app = create_app(Path(d) / "db.sqlite", Path(d) / "profiles")
        c = app.test_client()
        assert c.get("/").status_code == 200                     # UI phục vụ
        r = c.post("/api/v3/profiles/create", json={"name": "acc1", "os": "Windows", "engine": "camoufox"})
        pid = r.get_json()["data"]["id"]
        assert any(p["name"] == "acc1" for p in c.get("/api/v3/profiles").get_json()["data"])
        # gán proxy raw (không gọi mạng)
        pr = c.post(f"/api/v3/profiles/{pid}/proxy", json={"raw_proxy": "http://9.9.9.9:8080"})
        assert pr.get_json()["data"]["raw_proxy"] == "http://9.9.9.9:8080"
        assert "tinproxy" in c.get("/api/v3/proxy/providers").get_json()["data"]
        assert c.delete(f"/api/v3/profiles/{pid}").get_json()["data"]["deleted"]
        assert c.get("/api/v3/profiles").get_json()["data"] == []

        # IPv6 _guard_host (có & không port) + chặn DNS-rebinding
        assert c.get("/api/v3/health", headers={"Host": "[::1]"}).status_code == 200
        assert c.get("/api/v3/health", headers={"Host": "[::1]:19996"}).status_code == 200
        assert c.get("/api/v3/health", headers={"Host": "evil.com:19996"}).status_code == 403
        assert c.get("/api/v3/health", headers={"Host": "[::1].evil.com"}).status_code == 403

        # create với fp_overrides + start_url (khớp các tab Tạo profile)
        r2 = c.post("/api/v3/profiles/create", json={
            "name": "custom1", "os": "Windows", "start_url": "https://example.org",
            "fp_overrides": {
                "webrtc": {"mode": "Disable"},
                "screen": {"name": "Custom", "width": 1920, "height": 1080},
                "canvas": {"mode": "Real"},
                "navigator": {"allow_custom_user_agent": True, "user_agent": "CustomUA/1.0",
                              "auto_language": False, "language": "vi-VN", "do_not_track": True},
            },
        }).get_json()["data"]
        full = c.get(f"/api/v3/profiles/{r2['id']}").get_json()["data"]
        assert full["dynamic_data"]["start_url"] == "https://example.org"
        assert full["fingerprint_data"]["webrtc"]["mode"] == "Disable"
        assert full["fingerprint_data"]["screen"]["width"] == 1920
        assert full["fingerprint_data"]["canvas"]["mode"] == "Real"
        assert full["fingerprint_data"]["navigator"]["user_agent"] == "CustomUA/1.0"
        assert full["fingerprint_data"]["navigator"]["language"] == "vi-VN"
    print("[ok] API smoke (create/list/proxy/delete/UI/guard/fp_overrides)")


if __name__ == "__main__":
    test_botbrowser_configs()
    test_pick_profile()
    test_engine_resolve()
    test_proxy_parse_shapes()
    test_api_smoke()
    print("\nALL EXTRA CHECKS PASSED")
