"""Proxy provider layer — lấy/đổi IP tự động.

Endpoint là endpoint THẬT trích từ binary GPMLoginGlobal.exe (Phase 1, _notes/01-identify.md §proxy).
Mỗi provider: current_url (IP hiện tại) + rotate_url (xin IP mới). Trả proxy string chuẩn
"scheme://ip:port[:user:pass]" để nhét vào dynamic_data.proxy.raw_proxy.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

_PROXY_RE = re.compile(
    r"(?:(?P<scheme>socks5|socks4|http|https)://)?"
    r"(?P<host>\d{1,3}(?:\.\d{1,3}){3}|[a-z0-9.-]+):(?P<port>\d{2,5})"
    r"(?::(?P<user>[^:\s]+):(?P<pwd>[^:\s]+))?", re.I)


def _extract_proxy(obj: Any) -> Optional[str]:
    """Dò chuỗi proxy trong JSON response bất kể schema provider."""
    if isinstance(obj, str):
        m = _PROXY_RE.search(obj)
        return m.group(0) if m else None
    if isinstance(obj, dict):
        # ưu tiên key hay gặp
        for k in ("proxy", "proxyhttp", "proxy_http", "https", "http", "socks5",
                  "data", "result", "ip", "server"):
            if k in obj:
                r = _extract_proxy(obj[k])
                if r:
                    return r
        for v in obj.values():
            r = _extract_proxy(v)
            if r:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = _extract_proxy(v)
            if r:
                return r
    return None


@dataclass
class Provider:
    name: str
    current_url: str          # {key} được thay bằng api_key
    rotate_url: str
    scheme: str = "http"      # scheme mặc định nếu response thiếu


# Endpoint thật (trích binary GPM, Phase 1)
PROVIDERS: dict[str, Provider] = {
    "tinproxy":  Provider("tinproxy",
                          "https://api.tinproxy.com/proxy/get-current-proxy?api_key={key}",
                          "https://api.tinproxy.com/proxy/get-new-proxy?api_key={key}"),
    "kiotproxy": Provider("kiotproxy",
                          "https://api.kiotproxy.com/api/public/proxies/get-current?key={key}",
                          "https://api.kiotproxy.com/api/public/proxies/get-new?key={key}"),
    "proxyxoay": Provider("proxyxoay",
                          "https://api.proxyxoay.org/api/current.php?key={key}",
                          "https://api.proxyxoay.org/api/available.php?key={key}"),
    "1ip":       Provider("1ip",
                          "https://api.1ip.vn/user/package/get_proxy_info?api_key={key}",
                          "https://api.1ip.vn/user/package/changeip?api_key={key}"),
    "m2proxy":   Provider("m2proxy",
                          "https://api.m2proxy.com/user/package/get_proxy_info?api_key={key}",
                          "https://api.m2proxy.com/user/package/changeip?api_key={key}"),
    "rotaproxy": Provider("rotaproxy",
                          "https://api.rotaproxy.com/user/package/get_proxy_info?api_key={key}",
                          "https://api.rotaproxy.com/user/package/changeip?api_key={key}"),
    "vnproxy":   Provider("vnproxy",
                          "https://api.vnproxy.com/webservice/statusIP?key={key}",
                          "https://api.vnproxy.com/webservice/changeIP?key={key}"),
    "cloudcheap": Provider("cloudcheap",
                          "https://app.cloud-cheap.com/api/proxy-access/{key}/current",
                          "https://app.cloud-cheap.com/api/proxy-access/{key}/new"),
}


def _fetch(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "clone-gpm/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def get_current(provider: str, api_key: str, *, _fetcher: Callable[[str], Any] = _fetch) -> str:
    p = _require(provider)
    proxy = _extract_proxy(_fetcher(p.current_url.format(key=api_key)))
    if not proxy:
        raise RuntimeError(f"{provider}: không parse được proxy từ current")
    return _normalize(proxy, p.scheme)


def rotate(provider: str, api_key: str, *, _fetcher: Callable[[str], Any] = _fetch) -> str:
    p = _require(provider)
    proxy = _extract_proxy(_fetcher(p.rotate_url.format(key=api_key)))
    if not proxy:
        raise RuntimeError(f"{provider}: không parse được proxy từ rotate")
    return _normalize(proxy, p.scheme)


def _require(provider: str) -> Provider:
    p = PROVIDERS.get(provider.lower())
    if not p:
        raise ValueError(f"provider không hỗ trợ: {provider!r} ({list(PROVIDERS)})")
    return p


def _normalize(proxy: str, default_scheme: str) -> str:
    return proxy if "://" in proxy else f"{default_scheme}://{proxy}"


def to_url(raw_proxy: str) -> Optional[str]:
    """raw_proxy -> URL nhúng cred. Nhận cả 3 dạng:
    'scheme://host:port[:user:pass]', 'host:port[:user:pass]', 'scheme://user:pass@host:port'."""
    raw = (raw_proxy or "").strip()
    if not raw:
        return None
    scheme = "http"
    if "://" in raw:
        scheme, raw = raw.split("://", 1)
        scheme = scheme.lower()
    if "@" in raw:                                   # user:pass@host:port (như _parse_proxy)
        creds, hostport = raw.rsplit("@", 1)
        user, _, pwd = creds.partition(":")
        host, _, port = hostport.partition(":")
        return f"{scheme}://{user}:{pwd}@{host}:{port}" if host and port else None
    m = _PROXY_RE.search(raw)
    if not m:
        return None
    scheme = (m.group("scheme") or scheme).lower()
    host, port = m.group("host"), m.group("port")
    user, pwd = m.group("user"), m.group("pwd")
    cred = f"{user}:{pwd}@" if user else ""
    return f"{scheme}://{cred}{host}:{port}"


def normalize_scheme(raw_proxy: str, *, timeout: float = 8.0) -> str:
    """Raw_proxy chưa ghi scheme -> check() để detect rồi gắn scheme đúng (http/socks5),
    giúp lúc launch engine không mặc định nhầm http cho proxy socks5. Proxy chết / không
    detect được -> trả nguyên raw (không chặn việc gán)."""
    raw = (raw_proxy or "").strip()
    if not raw or "://" in raw:
        return raw
    try:
        res = check(raw, timeout=timeout)
    except Exception:  # noqa: BLE001
        return raw
    sch = res.get("scheme")
    return f"{sch}://{raw}" if res.get("alive") and sch else raw


def _fetch_through(proxy_url: str, target: str, timeout: float) -> Any:
    """GET `target` qua proxy_url (http/https dùng ProxyHandler, socks dùng PySocks). Trả JSON đã parse."""
    import socket as _s
    if proxy_url.startswith(("socks5", "socks4")):
        try:
            import socks
            from sockshandler import SocksiPyHandler
        except ImportError:
            raise RuntimeError("socks cần PySocks (pip install PySocks)")
        from urllib.parse import urlparse
        u = urlparse(proxy_url)
        ptype = socks.SOCKS4 if proxy_url.startswith("socks4") else socks.SOCKS5
        opener = urllib.request.build_opener(
            SocksiPyHandler(ptype, u.hostname, u.port, username=u.username, password=u.password))
    else:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    _old = _s.getdefaulttimeout(); _s.setdefaulttimeout(timeout)
    try:
        with opener.open(target, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    finally:
        _s.setdefaulttimeout(_old)


def geo_timezone(proxy: dict | None, *, timeout: float = 8.0) -> Optional[str]:
    """Timezone IANA của exit IP (query ip-api qua proxy), để engine Chromium khớp giờ với IP
    proxy (chống rò 'IP/Browser time mismatch'). proxy = Playwright dict. None nếu lỗi/không có."""
    if not proxy or not proxy.get("server"):
        return None
    server = proxy["server"]
    if proxy.get("username") and "://" in server:          # nhúng cred vào URL
        sch, rest = server.split("://", 1)
        url = f"{sch}://{proxy['username']}:{proxy.get('password', '')}@{rest}"
    else:
        url = server
    try:
        d = _fetch_through(url, "http://ip-api.com/json", timeout)
    except Exception:  # noqa: BLE001
        return None
    return (d or {}).get("timezone") or None


def check(raw_proxy: str, *, timeout: float = 10.0,
          test_url: str = "http://ip-api.com/json", _fetcher: Callable[[str, str], Any] | None = None) -> dict:
    """Test proxy: sống không, trễ bao nhiêu (ms), exit IP + quốc gia + scheme nào chạy.

    Proxy KHÔNG ghi scheme -> auto-detect: thử http rồi socks5 (nhiều proxy VN là socks5 trần).
    Có ghi scheme -> chỉ thử đúng scheme đó. socks cần PySocks. Trả dict:
    {alive, latency_ms, exit_ip, country, scheme?, error?}.
    """
    import time as _t
    url = to_url(raw_proxy)
    if not url:
        return {"alive": False, "error": "proxy không hợp lệ"}
    explicit = "://" in (raw_proxy or "")
    scheme0, _, base = url.partition("://")          # to_url luôn trả "<scheme>://<[cred@]host:port>"
    candidates = [scheme0] if explicit else ["http", "socks5"]

    fetch = _fetcher or (lambda purl, tgt: _fetch_through(purl, tgt, timeout))
    last_err = "proxy không phản hồi"
    for sch in candidates:
        t0 = _t.perf_counter()
        try:
            data = fetch(f"{sch}://{base}", test_url)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:120]; continue
        latency = int((_t.perf_counter() - t0) * 1000)
        ip = (data or {}).get("query") or (data or {}).get("ip") or _extract_proxy(data)
        if ip:
            return {"alive": True, "latency_ms": latency, "exit_ip": ip,
                    "country": (data or {}).get("country") or (data or {}).get("countryCode", ""),
                    "country_code": (data or {}).get("countryCode", ""),
                    "scheme": sch}
        last_err = "không đọc được exit IP"
    return {"alive": False, "error": last_err}
