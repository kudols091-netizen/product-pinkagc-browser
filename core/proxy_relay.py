"""Auth-relay cục bộ — giải bài Chromium `--proxy-server` không nhận user:pass.

Chromium cắm thẳng vào 127.0.0.1:<port> của relay (KHÔNG auth, không modal). Relay chèn
credential rồi forward lên upstream proxy (http/https: chèn Proxy-Authorization; socks5: PySocks).
Dùng cho ovobrowser + fingerprint-chromium (BotBrowser tự nhúng cred trong URL nên không cần).

ponytail: thread-per-conn + blind byte-pipe, chỉ Basic-auth, upstream http/https/socks5. Đủ cho
antidetect single-user; cần scale / SOCKS4 / UDP thì thay bằng gost|mitmproxy.
"""
from __future__ import annotations

import base64
import select
import socket
import threading
import time
from typing import Optional


def _retry(fn, attempts: int = 3, backoff: float = 0.3):
    """Thử lại fn() khi upstream proxy chớp tắt (lỗi mạng tạm). Backoff tăng dần, raise lỗi cuối."""
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except OSError as e:                 # gồm cả socks.ProxyError (IOError=OSError)
            last = e
            if i < attempts - 1:
                time.sleep(backoff * (i + 1))
    raise last                               # type: ignore[misc]


def _nodelay(s: socket.socket) -> None:
    """Tắt Nagle + nới buffer -> gói nhỏ (TLS handshake, click, AJAX) đi ngay, bớt giật/trễ."""
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        try:
            s.setsockopt(socket.SOL_SOCKET, opt, 262144)      # 256KB: throughput tốt hơn cho ảnh/video
        except OSError:
            pass


def _pipe(a: socket.socket, b: socket.socket) -> None:
    _nodelay(a); _nodelay(b)
    conns = [a, b]
    try:
        while True:
            r, _, x = select.select(conns, [], conns, 60)
            if x or not r:
                break
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass
    finally:
        for s in conns:
            try: s.close()
            except OSError: pass


class ProxyRelay:
    def __init__(self, upstream: dict):
        """upstream = Playwright proxy dict {server: scheme://host:port, username?, password?}."""
        server = upstream["server"]
        self.scheme, rest = (server.split("://", 1) if "://" in server else ("http", server))
        self.scheme = self.scheme.lower()
        self.up_host, _, up_port = rest.partition(":")
        self.up_port = int(up_port or ("1080" if "socks" in self.scheme else "8080"))
        self.user = upstream.get("username") or ""
        self.pwd = upstream.get("password") or ""
        self._srv: Optional[socket.socket] = None
        self.port = 0

    def start(self) -> int:
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(128)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def terminate(self) -> None:         # interface như Popen.terminate() để engine stop đồng nhất
        s, self._srv = self._srv, None
        if s:
            try: s.close()
            except OSError: pass
    stop = terminate

    # ---- internals ----
    def _accept_loop(self) -> None:
        srv = self._srv
        while self._srv:
            try:
                cli, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(cli,), daemon=True).start()

    def _handle(self, cli: socket.socket) -> None:
        _nodelay(cli)
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = cli.recv(4096)
                if not chunk:
                    cli.close(); return
                head += chunk
                if len(head) > 65536:            # header bất thường -> cắt
                    cli.close(); return
            header_block, _, leftover = head.partition(b"\r\n\r\n")
            first_line = header_block.split(b"\r\n", 1)[0].decode("latin1")
            if "socks" in self.scheme:
                self._relay_socks(cli, first_line, header_block, leftover)
            else:
                self._relay_http(cli, header_block, leftover)
        except Exception:                        # noqa: BLE001  — relay không được chết, chỉ đóng conn
            try: cli.close()
            except OSError: pass

    def _relay_http(self, cli: socket.socket, header_block: bytes, leftover: bytes) -> None:
        """Upstream là HTTP proxy: forward nguyên request (CONNECT hoặc absolute-form) + chèn auth."""
        up = _retry(lambda: socket.create_connection((self.up_host, self.up_port), timeout=30))
        lines = [l for l in header_block.split(b"\r\n")
                 if not l.lower().startswith(b"proxy-authorization:")]
        if self.user:
            tok = base64.b64encode(f"{self.user}:{self.pwd}".encode()).decode()
            lines.insert(1, f"Proxy-Authorization: Basic {tok}".encode())
        up.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + leftover)
        _pipe(cli, up)

    def _relay_socks(self, cli: socket.socket, first_line: str,
                     header_block: bytes, leftover: bytes) -> None:
        """Upstream là SOCKS5: nối target qua PySocks rồi pipe (best-effort)."""
        import socks  # PySocks
        parts = (first_line.split(" ") + ["", ""])[:3]
        method, url = parts[0].upper(), parts[1]
        if method == "CONNECT":
            host, _, port = url.partition(":")
            port = int(port or "443")
        else:                                    # absolute-form GET http://host:port/path
            rest = url.split("://", 1)[-1]
            hostport, _, path = rest.partition("/")
            host, _, port = hostport.partition(":")
            port = int(port or "80")
        def _dial():                         # socket mới mỗi lần thử (socksocket fail không tái dùng được)
            t = socks.socksocket()
            t.set_proxy(socks.SOCKS5, self.up_host, self.up_port,
                        username=self.user or None, password=self.pwd or None)
            t.connect((host, port))
            return t
        tgt = _retry(_dial)
        if method == "CONNECT":
            cli.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:                                    # viết lại origin-form rồi gửi thẳng tới target
            rest_headers = header_block.split(b"\r\n", 1)[1] if b"\r\n" in header_block else b""
            tgt.sendall(f"{method} /{path} HTTP/1.1".encode() + b"\r\n" +
                        rest_headers + b"\r\n\r\n" + leftover)
        _pipe(cli, tgt)


class RelayHandle:
    """Gói proc trình duyệt + relay -> .terminate() tắt cả hai (interface như Popen)."""
    def __init__(self, proc, relay: Optional[ProxyRelay] = None):
        self.proc, self.relay = proc, relay

    def terminate(self) -> None:
        try:
            self.proc.terminate()
        finally:
            if self.relay:
                self.relay.terminate()


def maybe_relay(proxy: Optional[dict]) -> tuple[Optional[dict], Optional[ProxyRelay]]:
    """Proxy có auth -> dựng relay, trả (proxy-không-auth trỏ 127.0.0.1:relay, relay).
    Proxy không auth hoặc None -> (proxy giữ nguyên, None)."""
    if not proxy or not proxy.get("username"):
        return proxy, None
    r = ProxyRelay(proxy)
    port = r.start()
    return {"server": f"http://127.0.0.1:{port}"}, r


if __name__ == "__main__":
    # Self-check _retry: thành công sau vài lần fail (proxy chớp tắt); raise sau khi hết lượt.
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("proxy chớp tắt")
        return "ok"
    assert _retry(flaky, attempts=3, backoff=0.01) == "ok" and calls["n"] == 3, "phải retry rồi thành công"
    try:
        _retry(lambda: (_ for _ in ()).throw(OSError("chết hẳn")), attempts=2, backoff=0.01)
        raise AssertionError("phải raise khi hết lượt")
    except OSError:
        pass
    print("OK - _retry: thanh cong sau fail tam thoi, raise khi het luot - PASS")
