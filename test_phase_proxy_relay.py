"""Smoke-test auth-relay + wiring engine + dispatch automation — KHÔNG cần browser binary thật.

Dùng fake upstream proxy (http + socks5 tối giản) và monkeypatch Popen/_read_cdp_ws để chứng minh:
  1. relay HTTP: forward absolute-form + chèn Proxy-Authorization
  2. relay HTTP: CONNECT tunnel (pipe 2 chiều)
  3. relay SOCKS5: nối target qua PySocks (skip nếu thiếu PySocks)
  4. ovobrowser/fpchromium.serve: proxy có auth -> RelayHandle, args trỏ relay, terminate dọn cả hai
  5. automation._connect: camoufox -> firefox.connect, còn lại -> chromium.connect_over_cdp

Chạy:  python test_phase_proxy_relay.py
"""
import base64
import os
import socket
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8")       # console Windows cp1252 không in nổi dấu tiếng Việt
except (AttributeError, ValueError):
    pass

from core.proxy_relay import ProxyRelay, RelayHandle, maybe_relay


def _recvn(c: socket.socket, n: int) -> bytes:
    b = b""
    while len(b) < n:
        d = c.recv(n - len(b))
        if not d:
            raise OSError("closed")
        b += d
    return b


# ---------- fake upstream HTTP proxy (xử lý cả absolute-form lẫn CONNECT, echo khi tunnel) ----------
def fake_http_proxy(auth_token: str | None):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(8)
    port = srv.getsockname()[1]
    cap: dict = {}

    def handle(c):
        head = b""
        while b"\r\n\r\n" not in head:
            d = c.recv(4096)
            if not d:
                c.close(); return
            head += d
        cap["req"] = head
        if auth_token and auth_token.encode() not in head:
            c.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"); c.close(); return
        if head.split(b"\r\n", 1)[0].upper().startswith(b"CONNECT"):
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            while True:                               # đóng vai target: echo
                d = c.recv(4096)
                if not d:
                    break
                c.sendall(d)
        else:
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nHELLO")
        c.close()

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return srv, port, cap


# ---------- fake SOCKS5 server (user/pass, CONNECT); echo hoặc forward tới target thật ----------
def fake_socks5(user: str, pwd: str, target: tuple | None = None):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(8)
    port = srv.getsockname()[1]

    def handle(c):
        try:
            ver_n = _recvn(c, 2)                       # ver, nmethods
            methods = _recvn(c, ver_n[1])
            if 0x02 in methods:
                c.sendall(b"\x05\x02")                 # chọn user/pass
                _recvn(c, 1)                           # auth ver = 1
                ul = _recvn(c, 1)[0]; u = _recvn(c, ul)
                pl = _recvn(c, 1)[0]; p = _recvn(c, pl)
                ok = (u.decode() == user and p.decode() == pwd)
                c.sendall(b"\x01\x00" if ok else b"\x01\x01")
                if not ok:
                    c.close(); return
            else:
                c.sendall(b"\x05\x00")
            req = _recvn(c, 4)                          # ver cmd rsv atyp
            atyp = req[3]
            if atyp == 1:
                _recvn(c, 4)
            elif atyp == 3:
                _recvn(c, _recvn(c, 1)[0])
            elif atyp == 4:
                _recvn(c, 16)
            _recvn(c, 2)                                # port
            c.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            if target:                                  # forward thật tới target (cho test check())
                import select
                dst = socket.create_connection(target, timeout=5)
                conns = [c, dst]
                while True:
                    r, _, _ = select.select(conns, [], [], 10)
                    if not r:
                        break
                    done = False
                    for s in r:
                        d = s.recv(4096)
                        if not d:
                            done = True; break
                        (dst if s is c else c).sendall(d)
                    if done:
                        break
                dst.close()
            else:
                while True:                             # echo target
                    d = c.recv(4096)
                    if not d:
                        break
                    c.sendall(d)
        except OSError:
            pass
        finally:
            c.close()

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return srv, port


# ---------- test 1: relay HTTP forward + auth inject ----------
def test_http_forward():
    srv, up_port, cap = fake_http_proxy(auth_token="Proxy-Authorization: Basic")
    r = ProxyRelay({"server": f"http://127.0.0.1:{up_port}", "username": "bob", "password": "s3cr3t"})
    port = r.start()
    cli = socket.create_connection(("127.0.0.1", port), timeout=5)
    cli.sendall(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
    resp = b""
    while b"HELLO" not in resp:
        b = cli.recv(4096)
        if not b:
            break
        resp += b
    cli.close(); r.terminate(); srv.close()
    tok = base64.b64encode(b"bob:s3cr3t").decode()
    assert b"HELLO" in resp, resp
    assert f"Proxy-Authorization: Basic {tok}".encode() in cap["req"], cap["req"]
    assert cap["req"].startswith(b"GET http://example.com/"), cap["req"]
    print("[ok] relay HTTP forward + auth inject")


# ---------- test 2: relay HTTP CONNECT tunnel ----------
def test_http_connect():
    srv, up_port, cap = fake_http_proxy(auth_token="Proxy-Authorization: Basic")
    r = ProxyRelay({"server": f"http://127.0.0.1:{up_port}", "username": "u", "password": "p"})
    port = r.start()
    cli = socket.create_connection(("127.0.0.1", port), timeout=5)
    cli.sendall(b"CONNECT echo.test:9999 HTTP/1.1\r\nHost: echo.test:9999\r\n\r\n")
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += cli.recv(4096)
    assert b"200" in buf, buf
    cli.sendall(b"ping-through-tunnel")
    got = _recvn(cli, len(b"ping-through-tunnel"))
    cli.close(); r.terminate(); srv.close()
    assert got == b"ping-through-tunnel", got
    assert cap["req"].upper().startswith(b"CONNECT"), cap["req"]
    print("[ok] relay HTTP CONNECT tunnel (pipe 2 chiều)")


# ---------- test 3: relay SOCKS5 (skip nếu thiếu PySocks) ----------
def test_socks5():
    try:
        import socks  # noqa: F401
    except ImportError:
        print("[skip] relay SOCKS5: thiếu PySocks (pip install PySocks)")
        return
    srv, sport = fake_socks5("alice", "pw5")
    r = ProxyRelay({"server": f"socks5://127.0.0.1:{sport}", "username": "alice", "password": "pw5"})
    port = r.start()
    cli = socket.create_connection(("127.0.0.1", port), timeout=5)
    cli.sendall(b"CONNECT echo.test:9999 HTTP/1.1\r\nHost: echo.test:9999\r\n\r\n")
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += cli.recv(4096)
    assert b"200" in buf, buf
    cli.sendall(b"socks-ping")
    got = _recvn(cli, len(b"socks-ping"))
    cli.close(); r.terminate(); srv.close()
    assert got == b"socks-ping", got
    print("[ok] relay SOCKS5 CONNECT qua PySocks")


# ---------- fake HTTP target (giả ip-api.com) ----------
def fake_http_target(body: bytes):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(8)
    port = srv.getsockname()[1]

    def handle(c):
        while b"\r\n\r\n" not in c.recv(4096):
            pass
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        c.close()

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return srv, port


# ---------- test 3b: proxy_providers.check() qua socks5 (vá "unknown url type") ----------
def test_socks_check():
    try:
        import socks  # noqa: F401
        import sockshandler  # noqa: F401
    except ImportError:
        print("[skip] check() socks5: thiếu PySocks")
        return
    from core import proxy_providers
    tsrv, tport = fake_http_target(b'{"query":"9.9.9.9","countryCode":"VN"}')
    ssrv, sport = fake_socks5("alice", "pw5", target=("127.0.0.1", tport))
    r = proxy_providers.check(f"socks5://alice:pw5@127.0.0.1:{sport}",
                              test_url=f"http://127.0.0.1:{tport}/json")
    tsrv.close(); ssrv.close()
    assert r["alive"] is True, r
    assert r["exit_ip"] == "9.9.9.9", r
    assert r["country"] == "VN", r
    print("[ok] check() socks5 qua PySocks (hết 'unknown url type')")


# ---------- test 3c: check() auto-detect scheme (http -> socks5) ----------
def test_autodetect_scheme():
    from core import proxy_providers as pp
    tried = []

    def fetcher(url, tgt):
        tried.append(url.split("://")[0])
        if url.startswith("socks5"):
            return {"query": "9.9.9.9"}
        raise RuntimeError("http closed")              # http luôn hỏng -> buộc fallback

    r = pp.check("1.2.3.4:1080:u:p", _fetcher=fetcher)     # trần (không scheme)
    assert r["alive"] and r["scheme"] == "socks5", r
    assert tried == ["http", "socks5"], tried             # thử http trước rồi mới socks5
    tried.clear()
    r2 = pp.check("socks5://1.2.3.4:1080:u:p", _fetcher=fetcher)  # scheme tường minh
    assert r2["alive"] and tried == ["socks5"], (r2, tried)
    print("[ok] check() auto-detect scheme (http->socks5), scheme tường minh chỉ thử đúng nó")


# ---------- test 3d: normalize_scheme (gán proxy tự chuẩn hoá scheme) ----------
def test_normalize_scheme():
    from core import proxy_providers as pp
    from core.fingerprint import _parse_proxy
    orig = pp.check
    pp.check = lambda raw, **k: {"alive": True, "scheme": "socks5", "exit_ip": "9.9.9.9"}
    try:
        got = pp.normalize_scheme("1.2.3.4:1080:u:p")
        assert got == "socks5://1.2.3.4:1080:u:p", got                 # trần -> gắn socks5://
        assert pp.normalize_scheme("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"  # đã có -> giữ
        pp.check = lambda raw, **k: {"alive": False, "error": "x"}
        assert pp.normalize_scheme("1.2.3.4:1080") == "1.2.3.4:1080"   # chết -> giữ nguyên, không chặn
    finally:
        pp.check = orig
    # form sau chuẩn hoá phải parse đúng lúc launch
    px = _parse_proxy("socks5://1.2.3.4:1080:u:p")
    assert px == {"server": "socks5://1.2.3.4:1080", "username": "u", "password": "p"}, px
    print("[ok] normalize_scheme: gắn scheme khi detect, giữ nguyên khi đã có/chết; launch parse đúng")


# ---------- test 3e: geo_timezone (khớp giờ theo exit IP) ----------
def test_geo_timezone():
    from core import proxy_providers as pp
    orig = pp._fetch_through
    pp._fetch_through = lambda url, tgt, to: {"timezone": "America/New_York", "query": "1.2.3.4"}
    try:
        px = {"server": "socks5://1.2.3.4:1080", "username": "u", "password": "p"}
        assert pp.geo_timezone(px) == "America/New_York"
        assert pp.geo_timezone(None) is None
        assert pp.geo_timezone({"server": ""}) is None
        pp._fetch_through = lambda url, tgt, to: {"query": "1.2.3.4"}   # thiếu timezone
        assert pp.geo_timezone(px) is None
    finally:
        pp._fetch_through = orig
    print("[ok] geo_timezone: lấy timezone exit IP, None khi thiếu/không proxy")


# ---------- test 4: wiring engine serve -> RelayHandle ----------
class _FakePopen:
    last_args: list | None = None

    def __init__(self, argv, **kw):
        _FakePopen.last_args = argv
        self.killed = False

    def terminate(self):
        self.killed = True


def _check_engine(mod, binenv):
    from core import proxy_providers as pp
    os.environ[binenv] = sys.executable           # Path(binary).exists() -> True
    orig_popen, orig_read = mod.subprocess.Popen, mod._read_cdp_ws
    orig_geo = pp.geo_timezone
    mod.subprocess.Popen = _FakePopen
    mod._read_cdp_ws = lambda port, **k: "ws://fake"
    pp.geo_timezone = lambda proxy, **k: "America/New_York"   # khỏi gọi mạng; verify wiring timezone
    try:
        fp = {"browser": {"browser_type": "Chrome", "browser_version": "155"}}
        dyn = {"proxy": {"raw_proxy": "http://user:pw@1.2.3.4:8080"}}
        handle, ws = mod.serve(fp, dyn, "asset/_test_relay", storage_name="w1", headless=True)
        assert ws == "ws://fake"
        assert isinstance(handle, RelayHandle), type(handle)
        assert isinstance(handle.relay, ProxyRelay)
        rport = handle.relay.port
        argv = _FakePopen.last_args
        assert any(f"--proxy-server=http://127.0.0.1:{rport}" in a for a in argv), argv
        assert not any("user:pw" in a or "@1.2.3.4" in a for a in argv), argv   # cred KHÔNG lọt vào CLI
        assert any(a == "--timezone=America/New_York" for a in argv), argv       # auto-tz theo proxy
        handle.terminate()
        assert handle.relay._srv is None               # relay đã tắt theo
    finally:
        mod.subprocess.Popen, mod._read_cdp_ws = orig_popen, orig_read
        pp.geo_timezone = orig_geo


def test_engine_wiring():
    from core import fpchromium, ovobrowser
    _check_engine(ovobrowser, "OVOBROWSER_BIN")
    _check_engine(fpchromium, "FPCHROMIUM_BIN")
    print("[ok] ovobrowser+fpchromium serve -> relay cục bộ, cred không lọt CLI, terminate dọn cả hai")


# ---------- test 5: automation dispatch engine ----------
def test_automation_connect():
    from core.automation import _connect

    class _FF:
        def __init__(self, p): self.p = p
        def connect(self, ws): self.p.calls.append(("firefox.connect", ws)); return "FF"

    class _CR:
        def __init__(self, p): self.p = p
        def connect_over_cdp(self, ws): self.p.calls.append(("chromium.cdp", ws)); return "CR"

    class _PW:
        def __init__(self): self.calls = []
        firefox = property(lambda s: _FF(s))
        chromium = property(lambda s: _CR(s))

    pw = _PW()
    assert _connect(pw, "camoufox", "ws://a") == "FF" and pw.calls[-1] == ("firefox.connect", "ws://a")
    assert _connect(pw, "ovobrowser", "ws://b") == "CR" and pw.calls[-1] == ("chromium.cdp", "ws://b")
    assert _connect(pw, "chromium", "ws://c") == "CR"
    print("[ok] automation._connect: camoufox->firefox, Chromium->CDP")


if __name__ == "__main__":
    test_http_forward()
    test_http_connect()
    test_socks5()
    test_socks_check()
    test_autodetect_scheme()
    test_normalize_scheme()
    test_geo_timezone()
    test_engine_wiring()
    test_automation_connect()
    print("\nALL PROXY-RELAY CHECKS PASSED")
