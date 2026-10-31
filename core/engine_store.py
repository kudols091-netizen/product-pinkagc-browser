"""Quản lý nhiều phiên bản engine (ovobrowser/chromium): built-in bundle + tải thêm theo yêu cầu.

Vì sao đa-version:
  - Mỗi profile KHOÁ 1 version (dynamic_data.engine_version) -> fingerprint ổn định theo đời nick
    (đổi version giữa chừng = UA/feature đổi = tell). Đa dạng version tránh pattern "cùng 1 phần mềm".
  - Tải lẻ từ manifest engines.json thay vì gói cứng -> bộ cài nhẹ, thêm version khi cần.

Tải/giải nén tách khỏi mạng (`_opener` injectable) -> test được. Dùng stdlib (urllib+zipfile).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

ENGINES_DIR = Path("engines")           # cạnh app (cwd = BASE sau app.py chdir). Test có thể gán lại.
DEFAULT_CATALOG_URL = "https://agency.pinkagc.com/browser/engines.json"

_progress: dict[str, dict] = {}         # version -> {pct, state(downloading|extracting|done|error), msg}
_VER_RE = re.compile(r"^[\w.\-]+$")     # chặn path traversal: version chỉ chữ/số/._- (không có / hay ..)


def _find_chrome(d: str | Path) -> str | None:
    hits = glob.glob(str(Path(d) / "**" / "chrome.exe"), recursive=True)
    return hits[0] if hits else None


def _builtin() -> dict | None:
    """Engine gói sẵn (OVOBROWSER_BIN) = version mặc định, không xoá được."""
    b = os.environ.get("OVOBROWSER_BIN")
    if b and Path(b).exists():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", str(b))
        return {"version": m.group(1) if m else "builtin", "path": b, "builtin": True}
    return None


def list_installed() -> list[dict]:
    """Version đã có: built-in + mọi engines/<version>/ có chrome.exe."""
    out: list[dict] = []
    bi = _builtin()
    if bi:
        out.append(bi)
    seen = {e["version"] for e in out}
    if ENGINES_DIR.exists():
        for sub in sorted(ENGINES_DIR.iterdir()):
            if sub.is_dir() and sub.name not in seen:
                c = _find_chrome(sub)
                if c:
                    out.append({"version": sub.name, "path": c, "builtin": False})
    return out


def resolve_binary(version: str | None) -> str | None:
    """chrome.exe cho version (rỗng/không thấy -> built-in default)."""
    if version:
        for e in list_installed():
            if e["version"] == version:
                return e["path"]
    bi = _builtin()
    return bi["path"] if bi else os.environ.get("OVOBROWSER_BIN")


def download_status() -> dict:
    return _progress


def download_version(version: str, url: str, *, sha256: str = "",
                     _opener: Callable[..., Any] = urllib.request.urlopen) -> dict:
    """Tải zip -> (verify sha256 nếu có) -> giải nén vào engines/<version>/. Cập nhật _progress. Ném nếu lỗi."""
    if not _VER_RE.match(version or ""):
        raise ValueError(f"version không hợp lệ: {version!r}")
    ENGINES_DIR.mkdir(parents=True, exist_ok=True)
    dest = ENGINES_DIR / version
    tmp = ENGINES_DIR / (version + ".zip")
    _progress[version] = {"pct": 0, "state": "downloading", "msg": ""}
    try:
        with _opener(url, timeout=120) as r:  # noqa: S310 (URL do user chọn từ catalog)
            total = int((r.headers.get("Content-Length") if r.headers else 0) or 0)
            done = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        _progress[version]["pct"] = min(99, int(done * 100 / total))
        if sha256:                                    # verify toàn vẹn trước khi giải nén/chạy (chống gói bị can thiệp)
            h = hashlib.sha256()
            with open(tmp, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest().lower() != sha256.strip().lower():
                raise RuntimeError("sha256 không khớp — gói tải về có thể bị can thiệp, đã huỷ")
        _progress[version] = {"pct": 100, "state": "extracting", "msg": ""}
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dest)
        tmp.unlink(missing_ok=True)
        c = _find_chrome(dest)
        if not c:
            raise RuntimeError("không thấy chrome.exe trong gói tải về")
        _progress[version] = {"pct": 100, "state": "done", "msg": ""}
        return {"version": version, "path": c}
    except Exception as e:  # noqa: BLE001
        _progress[version] = {"pct": 0, "state": "error", "msg": str(e)}
        tmp.unlink(missing_ok=True)
        raise


def download_async(version: str, url: str, *, sha256: str = "") -> None:
    def run() -> None:
        try:
            download_version(version, url, sha256=sha256)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()


def delete_version(version: str) -> None:
    if not _VER_RE.match(version or ""):              # chặn traversal trên rmtree
        return
    d = ENGINES_DIR / version
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    _progress.pop(version, None)


def fetch_catalog(url: str, *, _opener: Callable[..., Any] = urllib.request.urlopen) -> list[dict]:
    """Manifest {engines:[{version,url,size,sha256?}]} hoặc mảng thẳng. Lỗi -> []."""
    try:
        with _opener(url, timeout=20) as r:  # noqa: S310
            data = json.loads(r.read())
    except Exception:  # noqa: BLE001
        return []
    engines = data.get("engines") if isinstance(data, dict) else data
    return engines if isinstance(engines, list) else []


if __name__ == "__main__":
    import io
    import tempfile

    tmpd = Path(tempfile.mkdtemp())
    globals()["ENGINES_DIR"] = tmpd / "engines"
    os.environ.pop("OVOBROWSER_BIN", None)              # không có built-in cho test sạch

    # tạo 1 zip có chrome.exe lồng thư mục -> _find_chrome phải thấy
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ovo-156/chrome.exe", b"MZ fake")
        z.writestr("ovo-156/icudtl.dat", b"x")
    payload = buf.getvalue()

    class _FakeResp:
        def __init__(self, data): self._b = io.BytesIO(data); self.headers = {"Content-Length": str(len(data))}
        def read(self, n=-1): return self._b.read(n)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(url, timeout=0): return _FakeResp(payload)

    r = download_version("156.0.8078.12", "http://x/pkg.zip", _opener=fake_open)
    assert Path(r["path"]).name == "chrome.exe" and Path(r["path"]).exists(), r
    inst = list_installed()
    assert any(e["version"] == "156.0.8078.12" and not e["builtin"] for e in inst), inst
    assert resolve_binary("156.0.8078.12") == r["path"]
    assert resolve_binary("nope") is None                # không version + không built-in
    assert _progress["156.0.8078.12"]["state"] == "done"
    # catalog parse (fake)
    cat = fetch_catalog("http://x/engines.json",
                        _opener=lambda u, timeout=0: _FakeResp(json.dumps(
                            {"engines": [{"version": "153", "url": "u", "size": 1}]}).encode()))
    assert cat and cat[0]["version"] == "153", cat
    delete_version("156.0.8078.12")
    assert not any(e["version"] == "156.0.8078.12" for e in list_installed())
    print("OK - engine_store download/extract/list/resolve/catalog/delete - PASS")
