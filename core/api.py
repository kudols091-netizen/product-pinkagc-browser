"""Local REST API :19996 + Web UI — nhái hợp đồng GPM Login (_notes/05-full-spec.md §5).

Script viết cho GPM gọi được thẳng. Start trả endpoint:
  - camoufox  -> ws Playwright (firefox.connect)
  - botbrowser-> ws CDP (chromium, remote_debugging_address thật)
Kèm UI quản profile tại http://127.0.0.1:19996/ (phần B — dùng web shell thay Avalonia).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from . import brand, browser_profiles, engines, proxy_providers
from . import scheduler as scheduler_mod
from .db import Database
from .fingerprint import generate

DEFAULT_PORT = brand.DEFAULT_PORT
_UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _ok(data: Any = None, **extra):
    return jsonify({"success": True, "data": data, **extra})


def _err(msg: str, code: int = 400):
    return jsonify({"success": False, "message": msg}), code


def parse_cookies(data: Any) -> list[dict]:
    """Chuẩn hoá cookie về format Playwright [{name,value,domain,path,...}].
    Nhận: list dict JSON, chuỗi JSON, hoặc text Netscape (tab-separated)."""
    if isinstance(data, str):
        s = data.strip()
        if s.startswith("["):
            try:
                data = json.loads(s)
            except Exception:  # noqa: BLE001
                return []
        else:  # Netscape: domain \t flag \t path \t secure \t expiry \t name \t value
            out = []
            for line in s.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    out.append({"domain": parts[0], "path": parts[2],
                                "secure": parts[3].upper() == "TRUE",
                                "expires": int(parts[4]) if parts[4].lstrip("-").isdigit() else -1,
                                "name": parts[5], "value": parts[6]})
            return out
    if not isinstance(data, list):
        return []
    norm = []
    for c in data:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        ck = {"name": str(c["name"]), "value": str(c.get("value", "")),
              "domain": c.get("domain", ""), "path": c.get("path", "/")}
        if not ck["domain"]:
            continue
        for k in ("httpOnly", "secure"):
            if k in c:
                ck[k] = bool(c[k])
        exp = c.get("expires", c.get("expirationDate"))
        if isinstance(exp, (int, float)) and exp > 0:
            ck["expires"] = int(exp)
        ss = c.get("sameSite")
        if ss and str(ss).capitalize() in ("Lax", "Strict", "None"):
            ck["sameSite"] = str(ss).capitalize()
        norm.append(ck)
    return norm


def create_app(db_path: str | Path, profiles_root: str | Path) -> Flask:
    app = Flask(__name__)

    _ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}

    @app.before_request
    def _guard_host():                                # chặn DNS-rebinding: web ngoài trỏ domain -> 127.0.0.1
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if host not in _ALLOWED_HOSTS:
            return jsonify({"error": "forbidden host"}), 403

    db = Database(db_path)
    profiles_root = str(profiles_root)
    running: dict[str, tuple[Any, str, str]] = {}   # pid -> (handle, endpoint, engine)
    _rlock = threading.Lock()                        # Flask threaded=True -> khoá mọi đọc/ghi `running`
    _starting: set[str] = set()                      # pid đang serve() dở (chống start trùng -> mồ côi)

    # ---- settings (JSON cạnh DB) + log (ring buffer trong RAM) ----
    _settings_file = Path(db_path).parent / "settings.json"
    _DEFAULT_SETTINGS = {
        # chung
        "default_os": "Windows", "default_browser": "Chrome", "default_engine": "", "headless": False,
        "private_server_url": "", "team_token": "", "team_user": "",
        # trình duyệt — mode fingerprint mặc định khi tạo profile
        "canvas": "Noise", "client_rect": "Noise", "webgl": "Noise", "webgl_meta": "Masked",
        "audio": "Noise", "font": "Masked", "screen": "Real", "language": "Base on IP",
        "start_url": "", "chrome_params": "", "clear_cache": True, "limit_window": True,
        # AI dựng kịch bản (gap #3b) — provider openai-compatible hoặc gemini
        "ai_provider": "openai", "ai_base_url": "", "ai_key": "", "ai_model": "",
        # engine đa-version: URL manifest các bản Chrome/ovobrowser tải thêm
        "engines_url": "https://agency.pinkagc.com/browser/engines.json",
    }

    def _load_settings() -> dict:
        s = dict(_DEFAULT_SETTINGS)
        try:
            s.update(json.loads(_settings_file.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
        return s

    def _save_settings(patch: dict) -> dict:
        s = _load_settings()
        s.update({k: v for k, v in patch.items() if k in _DEFAULT_SETTINGS})
        try:
            _settings_file.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return s

    _log: list[dict] = []

    def log_event(kind: str, msg: str) -> None:
        from datetime import datetime, timezone
        _log.append({"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, "msg": msg})
        del _log[:-300]            # giữ tối đa 300 dòng gần nhất

    # ---- helpers dùng chung cho route lẻ + bulk ----
    def _start_one(pid: str, opts: dict) -> dict:
        p = db.get_profile(pid)
        if not p:
            return {"id": pid, "error": "not found"}
        with _rlock:                                  # check + giữ chỗ nguyên tử: chặn 2 lệnh Start cùng pid
            if pid in running:
                _, ep, eng = running[pid]
                return {"id": pid, "ws_endpoint": ep, "remote_debugging_address": ep,
                        "engine": eng, "already_running": True}
            if pid in _starting:
                return {"id": pid, "error": "profile đang được mở, thử lại sau"}
            _starting.add(pid)
        try:
            engine = engines.resolve_engine(p, opts.get("engine"))
            try:
                handle, ep = engines.serve(engine, p, profiles_root, headless=bool(opts.get("headless", False)))
            except Exception as e:  # noqa: BLE001
                return {"id": pid, "error": f"launch failed ({engine}): {e}"}
            with _rlock:
                running[pid] = (handle, ep, engine)
        finally:
            with _rlock:
                _starting.discard(pid)
        db.mark_run(pid)
        dyn = p.dynamic_data or {}
        pend = dyn.pop("cookies_pending", None)      # nạp cookie import vào trình duyệt vừa mở
        if pend and engine != "camoufox":
            try:
                from . import automation
                automation.inject_cookies(ep, pend, engine=engine)
                db.set_dynamic_data(pid, dyn)        # xoá pending (Chromium đã persist vào profile)
            except Exception:  # noqa: BLE001
                pass
        _btype = ((p.fingerprint_data or {}).get("browser", {}) or {}).get("browser_type", "Chrome")
        log_event("start", f"Đã mở {_btype} với profile {p.name}")
        return {"id": pid, "engine": engine, "ws_endpoint": ep, "remote_debugging_address": ep}

    def _stop_one(pid: str) -> dict:
        with _rlock:
            item = running.pop(pid, None)
        if item:
            engines.graceful_stop(item[0], item[1], item[2])   # đóng mềm Chromium rồi terminate
            _p = db.get_profile(pid)
            log_event("stop", f"Đã đóng profile {_p.name if _p else pid[:8]}")
        return {"id": pid, "stopped": bool(item)}

    def _prune_dead() -> None:
        """Gỡ profile mà tiến trình trình duyệt đã thoát (user bấm X đóng cửa sổ tay) khỏi `running`,
        để status quay về 'sẵn sàng' thay vì kẹt 'đang chạy'. Gọi trước mỗi lần liệt kê/báo status."""
        with _rlock:
            items = list(running.items())              # snapshot: tránh KeyError khi thread khác pop giữa chừng
        for pid, (h, _ep, _eng) in items:
            proc = getattr(h, "proc", h)   # RelayHandle/_CamoufoxHandle -> .proc; ovobrowser/botbrowser -> Popen
            try:
                dead = proc.poll() is not None
            except Exception:              # noqa: BLE001 — không poll được -> coi như còn chạy (an toàn)
                continue
            if dead:
                _stop_one(pid)             # dọn relay + ghi log "Đóng profile"

    def _run_profile_script(pid: str, steps: list, *, engine: str | None = None,
                            headless: bool = True, script_name: str = "",
                            source: str = "manual") -> dict:
        """Chạy 1 kịch bản trên 1 profile (mở nếu chưa mở) + ghi nhật ký run. Dùng chung endpoint+scheduler."""
        from . import automation
        p = db.get_profile(pid)
        if not p:
            return {"error": "profile not found"}
        errs = automation.validate_script(steps)
        if errs:
            return {"error": "script lỗi: " + "; ".join(errs)}
        rid = db.add_run(pid, p.name, script_name or "(inline)", source)
        r = _start_one(pid, {"engine": engine, "headless": headless})   # idempotent: đang mở -> already_running
        if r.get("error"):
            db.finish_run(rid, False, [r["error"]])
            return {"error": r["error"]}
        started = not r.get("already_running")     # CHỈ tự đóng nếu chính call này mở (tránh đóng nhầm của flow khác)
        rec = running.get(pid)
        if not rec:                                   # bị đóng tay/prune xen giữa -> dừng gọn, không KeyError 500
            db.finish_run(rid, False, ["profile không còn mở"])
            return {"error": "profile không còn mở"}
        ws, eng = rec[1], rec[2]
        try:
            workdir = str(Path(profiles_root) / (p.storage_path or pid))
            result = automation.run_script(ws, steps, engine=eng, workdir=workdir)
        finally:
            if started:
                _stop_one(pid)
        db.finish_run(rid, bool(result.get("ok")), result.get("log"), result.get("data"))
        result["run_id"] = rid
        return result

    # ---- UI ----
    @app.get("/")
    def ui_index():
        return send_from_directory(_UI_DIR, "index.html")

    @app.get("/<path:fname>")
    def ui_static(fname: str):
        # Phục vụ asset tĩnh trong ui/ (logo.svg...). API /api/v3/* là rule cụ thể nên không bị che.
        if (_UI_DIR / fname).is_file():
            return send_from_directory(_UI_DIR, fname)
        return _err("not found", 404)

    # ---- profiles ----
    @app.get("/api/v3/profiles")
    def list_profiles():
        _prune_dead()
        return _ok([{
            "id": p.id, "name": p.name, "group_id": p.group_id,
            "os": (p.fingerprint_data.get("os", {}) or {}).get("type"),
            "browser": (p.fingerprint_data.get("browser", {}) or {}).get("browser_type"),
            "proxy": (p.dynamic_data.get("proxy", {}) or {}).get("raw_proxy", ""),
            "engine": (p.dynamic_data or {}).get("engine", "auto"),
            "last_run_at": p.last_run_at,
            "status": "running" if p.id in running else "stopped",
            "note": (p.dynamic_data.get("meta", {}) or {}).get("note", ""),
            "color": (p.dynamic_data.get("meta", {}) or {}).get("color", ""),
            "pinned": (p.dynamic_data.get("meta", {}) or {}).get("pinned", False),
            "tags": (p.dynamic_data.get("meta", {}) or {}).get("tags", []),
            "timezone": ("" if (p.fingerprint_data.get("timezone", {}) or {}).get("auto_timezone", True)
                         else (p.fingerprint_data.get("timezone", {}) or {}).get("timezone", "")),
        } for p in sorted(db.list_profiles(),
                          key=lambda x: not (x.dynamic_data.get("meta", {}) or {}).get("pinned", False))])

    def _make_profile(b: dict, name: str):
        s = _load_settings()
        fp = b.get("fingerprint_data") or generate(
            os_type=b.get("os") or s["default_os"], browser_type=b.get("browser") or s["default_browser"])
        if not b.get("fingerprint_data"):            # áp dụng mode fingerprint mặc định từ Cài đặt
            fp.setdefault("canvas", {})["mode"] = s["canvas"]
            fp.setdefault("client_rect", {})["mode"] = s["client_rect"]
            fp.setdefault("webgl_image", {})["mode"] = s["webgl"]
            fp.setdefault("webgl_meta_data", {})["mode"] = s["webgl_meta"]
            fp.setdefault("audio_context", {})["mode"] = s["audio"]
            fp.setdefault("font", {})["mode"] = s["font"]
            fp.setdefault("navigator", {})["auto_language"] = (s["language"] != "Real")
            if s["screen"] == "Random":
                from .fingerprint import _SCREENS
                import random as _r
                w, h = _r.choice(_SCREENS)
                fp.setdefault("screen", {}).update({"name": "Random", "width": w, "height": h})
        dyn = b.get("dynamic_data") or {}
        eng = b.get("engine") if b.get("engine") is not None else s["default_engine"]
        if eng:
            dyn["engine"] = eng
        if s.get("start_url"):
            dyn["start_url"] = s["start_url"]
        if s.get("chrome_params"):
            dyn["chrome_params"] = s["chrome_params"]
        return db.create_profile(name, fp, group_id=b.get("group_id"), dynamic_data=dyn)

    @app.post("/api/v3/profiles/create")
    def create_profile():
        b = request.get_json(silent=True) or {}
        p = _make_profile(b, b.get("name") or "Profile")
        log_event("create", f"Tạo profile {p.name}")
        return _ok({"id": p.id, "name": p.name})

    @app.post("/api/v3/profiles/bulk-create")
    def bulk_create():
        """Tạo nhiều profile 1 lần (đa tài khoản). {count, name, ...} -> name #1..#N."""
        b = request.get_json(silent=True) or {}
        try:
            n = max(1, min(200, int(b.get("count", 1))))     # trần 200/lần
        except (TypeError, ValueError):
            n = 1
        base = (b.get("name") or "Profile").strip()
        out = []
        for i in range(1, n + 1):
            p = _make_profile(b, f"{base} {i}" if n > 1 else base)
            out.append({"id": p.id, "name": p.name})
        log_event("create", f"Tạo hàng loạt {n} profile ({base})")
        return _ok({"created": len(out), "profiles": out})

    @app.get("/api/v3/profiles/<pid>")
    def get_profile_full(pid: str):
        """Full profile (fingerprint_data + dynamic_data) cho màn sửa chi tiết."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        return _ok({"id": p.id, "name": p.name, "group_id": p.group_id,
                    "fingerprint_data": p.fingerprint_data, "dynamic_data": p.dynamic_data})

    @app.post("/api/v3/profiles/start/<pid>")
    def start_profile(pid: str):
        r = _start_one(pid, request.get_json(silent=True) or {})
        if r.get("error"):
            return _err(r["error"], 404 if r["error"] == "not found" else 500)
        return _ok(r)

    @app.post("/api/v3/profiles/stop/<pid>")
    def stop_profile(pid: str):
        return _ok(_stop_one(pid))

    # ---- Local API TƯƠNG THÍCH GPM (/api/v1) — để Selenium/Puppeteer & script GPM/AdsPower dùng sẵn.
    # GPM trả {success, data:{remote_debugging_address:"127.0.0.1:PORT", driver_path, ...}}. Dùng GET.
    def _debug_addr(ep: str) -> str:
        from urllib.parse import urlparse
        return urlparse(ep).netloc or ep        # ws://127.0.0.1:PORT/devtools/... -> 127.0.0.1:PORT

    def _driver_path() -> str:
        import glob
        import os
        bin_env = os.environ.get("OVOBROWSER_BIN") or os.environ.get("FPCHROMIUM_BIN") or ""
        if bin_env:
            hits = glob.glob(str(Path(bin_env).parent / "chromedriver*.exe"))
            if hits:
                return hits[0]
        return ""

    def _gpm_ok(data: dict):
        return jsonify({"success": True, "data": data})

    def _gpm_err(msg: str, code: int = 400):
        return jsonify({"success": False, "message": msg}), code

    @app.get("/api/v1/status")
    def gpm_status():
        _prune_dead()
        return _gpm_ok({"app": brand.APP_NAME, "version": brand.VERSION, "running": list(running)})

    @app.get("/api/v1/profiles")
    def gpm_profiles():
        _prune_dead()
        rows = [{"id": p.id, "name": p.name, "group": p.group_id,
                 "status": "running" if p.id in running else "stopped"} for p in db.list_profiles()]
        return _gpm_ok({"profiles": rows, "total": len(rows)})

    @app.route("/api/v1/profiles/start/<pid>", methods=["GET", "POST"])
    def gpm_start(pid: str):
        hl = request.args.get("headless") in ("1", "true", "yes")
        r = _start_one(pid, {"engine": request.args.get("engine"), "headless": hl})
        if r.get("error"):
            return _gpm_err(r["error"], 404 if "not found" in r["error"] else 500)
        return _gpm_ok({"profile_id": pid, "id": pid, "ws_endpoint": r["ws_endpoint"],
                        "remote_debugging_address": _debug_addr(r["ws_endpoint"]),
                        "driver_path": _driver_path(), "engine": r.get("engine", "")})

    @app.route("/api/v1/profiles/close/<pid>", methods=["GET", "POST"])
    def gpm_close(pid: str):
        _stop_one(pid)
        return _gpm_ok({"profile_id": pid, "id": pid})

    @app.delete("/api/v3/profiles/<pid>")
    def delete_profile(pid: str):
        _stop_one(pid)
        db.delete_profile(pid)
        return _ok({"id": pid, "deleted": True})

    # ---- lifecycle (Phase B) ----
    @app.post("/api/v3/profiles/update/<pid>")
    def update_profile(pid: str):
        if not db.get_profile(pid):
            return _err("profile not found", 404)
        b = request.get_json(silent=True) or {}
        db.update_profile(pid, name=b.get("name"),
                          group_id=b["group_id"] if "group_id" in b else ...,
                          fingerprint_data=b.get("fingerprint_data"),
                          dynamic_data=b.get("dynamic_data"))
        return _ok({"id": pid, "updated": True})

    @app.post("/api/v3/profiles/<pid>/clone")
    def clone_profile(pid: str):
        c = db.clone_profile(pid, (request.get_json(silent=True) or {}).get("name"))
        return _ok({"id": c.id, "name": c.name}) if c else _err("profile not found", 404)

    @app.post("/api/v3/profiles/<pid>/meta")
    def set_meta(pid: str):
        b = request.get_json(silent=True) or {}
        db.set_meta(pid, note=b.get("note"), color=b.get("color"),
                    pinned=b.get("pinned"), tags=b.get("tags"))
        return _ok({"id": pid})

    @app.post("/api/v3/profiles/<pid>/open-folder")
    def open_profile_folder(pid: str):
        """Mở thư mục dữ liệu của profile trong Explorer (Windows)."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        import os
        folder = Path(profiles_root) / (p.storage_path or pid)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder))            # noqa: S606 — mở Explorer, chỉ localhost/desktop
        except Exception as e:                   # noqa: BLE001
            return _err(f"không mở được thư mục: {e}", 500)
        return _ok({"id": pid, "folder": str(folder)})

    @app.post("/api/v3/profiles/<pid>/shortcut")
    def make_desktop_shortcut(pid: str):
        """Tạo file .bat ra Desktop: double-click là mở profile (cần PinkAgc đang chạy)."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        import os
        desktop = Path(os.path.join(os.path.expanduser("~"), "Desktop"))
        desktop.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in (p.name or "") if c.isalnum() or c in " -_").strip() or pid[:8]
        bat = desktop / f"PinkAgc - {safe}.bat"
        bat.write_text(
            "@echo off\r\n"
            f"curl -s -X POST \"http://127.0.0.1:19996/api/v3/profiles/start/{pid}\" >nul 2>&1\r\n"
            "if errorlevel 1 (echo Hay mo PinkAgc Browser truoc, roi chay lai shortcut. && pause)\r\n",
            encoding="utf-8")
        return _ok({"id": pid, "path": str(bat)})

    @app.post("/api/v3/profiles/tag")
    def bulk_tag():
        """Gán/gỡ tag cho nhiều profile. {ids[], add[], remove[]}"""
        b = request.get_json(silent=True) or {}
        add = [str(t).strip() for t in (b.get("add") or []) if str(t).strip()]
        remove = set(str(t).strip() for t in (b.get("remove") or []))
        n = 0
        for pid in (b.get("ids") or []):
            p = db.get_profile(pid)
            if not p:
                continue
            cur = (p.dynamic_data.get("meta", {}) or {}).get("tags", [])
            new = [t for t in cur if t not in remove] + [t for t in add if t not in cur]
            db.set_meta(pid, tags=new)
            n += 1
        return _ok({"updated": n})

    @app.post("/api/v3/profiles/<pid>/timezone")
    def set_timezone(pid: str):
        """Ép timezone thủ công (trống = auto theo IP proxy). Khớp checker dùng geo-DB khác ta."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        tz = ((request.get_json(silent=True) or {}).get("timezone") or "").strip()
        fp = p.fingerprint_data or {}
        fp.setdefault("timezone", {})
        fp["timezone"]["auto_timezone"] = not tz
        fp["timezone"]["timezone"] = tz
        db.update_profile(pid, fingerprint_data=fp)
        return _ok({"id": pid, "timezone": tz or "(auto)"})

    @app.post("/api/v3/profiles/<pid>/fingerprint/randomize")
    def randomize_fp(pid: str):
        from .fingerprint import randomize_fields
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        b = request.get_json(silent=True) or {}
        fp = randomize_fields(p.fingerprint_data, b.get("fields"))
        dyn = p.dynamic_data or {}
        dyn["fp_seed"] = __import__("uuid").uuid4().int % (2 ** 31)   # đổi luôn seed noise engine
        db.update_profile(pid, fingerprint_data=fp, dynamic_data=dyn)
        return _ok({"id": pid, "fingerprint_data": fp})

    @app.post("/api/v3/profiles/bulk")
    def bulk():
        b = request.get_json(silent=True) or {}
        ids, action = b.get("ids", []), b.get("action", "")
        fn = {"start": lambda i: _start_one(i, b), "stop": _stop_one,
              "delete": lambda i: (_stop_one(i), db.delete_profile(i), {"id": i, "deleted": True})[-1],
              }.get(action)
        if not fn:
            return _err(f"action không hỗ trợ: {action!r} (start|stop|delete)")
        return _ok([fn(i) for i in ids])

    @app.get("/api/v3/profiles/trash")
    def trash():
        return _ok([{
            "id": p.id, "name": p.name,
            "proxy": (p.dynamic_data.get("proxy", {}) or {}).get("raw_proxy", ""),
            "last_run_at": p.last_run_at,
        } for p in db.list_deleted()])

    @app.post("/api/v3/profiles/<pid>/restore")
    def restore(pid: str):
        db.restore_profile(pid)
        return _ok({"id": pid, "restored": True})

    @app.delete("/api/v3/profiles/<pid>/purge")
    def purge(pid: str):
        db.purge_profile(pid)
        return _ok({"id": pid, "purged": True})

    @app.get("/api/v3/profiles/export")
    def export_profiles():
        return _ok([p.to_dict() for p in db.list_profiles()])

    @app.post("/api/v3/profiles/import")
    def import_profiles():
        items = (request.get_json(silent=True) or {}).get("profiles", [])
        out = [db.create_profile(it.get("name") or "Imported",
                                 it.get("fingerprint_data") or {}, group_id=it.get("group_id"),
                                 dynamic_data=it.get("dynamic_data") or {}).id for it in items]
        return _ok({"imported": len(out), "ids": out})

    # ---- proxy providers (phần C) ----
    @app.get("/api/v3/proxy/providers")
    def proxy_list():
        return _ok(list(proxy_providers.PROVIDERS))

    @app.post("/api/v3/profiles/<pid>/proxy")
    def set_proxy(pid: str):
        """Gán proxy: từ provider (lấy current/rotate) hoặc raw trực tiếp."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        b = request.get_json(silent=True) or {}
        try:
            if b.get("provider"):
                fn = proxy_providers.rotate if b.get("rotate") else proxy_providers.get_current
                raw = fn(b["provider"], b.get("api_key", ""))
            else:
                raw = b.get("raw_proxy", "")
        except Exception as e:  # noqa: BLE001
            return _err(f"proxy error: {e}", 502)
        raw = proxy_providers.normalize_scheme(raw)     # gắn socks5://… nếu detect được
        dyn = p.dynamic_data or {}
        dyn.setdefault("proxy", {})["raw_proxy"] = raw
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "raw_proxy": raw})

    @app.post("/api/v3/automation/validate")
    def automation_validate():
        from . import automation
        steps = (request.get_json(silent=True) or {}).get("steps", [])
        errs = automation.validate_script(steps)
        return _ok({"valid": not errs, "errors": errs})

    @app.post("/api/v3/profiles/<pid>/run")
    def run_automation(pid: str):
        b = request.get_json(silent=True) or {}
        res = _run_profile_script(pid, b.get("steps", []), engine=b.get("engine"),
                                  headless=b.get("headless", True),
                                  script_name=b.get("script_name", ""))
        if res.get("error"):
            msg = res["error"]
            code = 404 if "not found" in msg else (400 if "script lỗi" in msg else 500)
            return _err(msg, code)
        return _ok(res)

    @app.post("/api/v3/profiles/<pid>/record/start")
    def record_start(pid: str):
        rec = running.get(pid)
        if not rec:
            return _err("profile chưa mở — mở profile trước khi ghi thao tác", 400)
        from . import automation
        ws, eng = rec[1], rec[2]
        try:
            automation.start_recording(ws, engine=eng)
        except Exception as e:  # noqa: BLE001
            return _err(f"không bật được ghi: {e}", 500)
        return _ok({"recording": True})

    @app.post("/api/v3/profiles/<pid>/record/fetch")
    def record_fetch(pid: str):
        rec = running.get(pid)
        if not rec:
            return _err("profile chưa mở", 400)
        from . import automation
        ws, eng = rec[1], rec[2]
        try:
            steps = automation.fetch_recording(ws, engine=eng)
        except Exception as e:  # noqa: BLE001
            return _err(str(e), 500)
        return _ok({"steps": steps})

    @app.post("/api/v3/profiles/<pid>/options")
    def profile_options(pid: str):
        """Merge cờ hành vi vào dynamic_data (vd save_bandwidth = chặn ảnh tiết kiệm băng thông)."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        b = request.get_json(silent=True) or {}
        dyn = p.dynamic_data or {}
        for k in ("save_bandwidth",):                 # whitelist cờ bool
            if k in b:
                dyn[k] = bool(b[k])
        for k in ("engine_version", "fake_camera", "fake_mic"):   # cờ chuỗi (version / camera .y4m / mic .wav)
            if k in b:
                dyn[k] = str(b[k] or "")
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "save_bandwidth": dyn.get("save_bandwidth", False),
                    "engine_version": dyn.get("engine_version", ""),
                    "fake_camera": dyn.get("fake_camera", ""), "fake_mic": dyn.get("fake_mic", "")})

    @app.post("/api/v3/pick-file")
    def pick_file():
        """Mở hộp chọn file native (Windows) → trả đường dẫn tuyệt đối. Cho nút Browse (web UI giấu path)."""
        import subprocess
        flt = str((request.get_json(silent=True) or {}).get("filter", "All files|*.*"))
        flt = flt.replace("'", "")                     # chặn phá chuỗi PS
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$f=New-Object System.Windows.Forms.OpenFileDialog;"
              f"$f.Filter='{flt}';$f.Title='Chon file';"
              "if($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){Write-Output $f.FileName}")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                                 capture_output=True, text=True, timeout=180)
            return _ok({"path": out.stdout.strip()})
        except Exception as e:  # noqa: BLE001
            return _err(f"không mở được hộp chọn file: {e}", 500)

    @app.post("/api/v3/pick-folder")
    def pick_folder():
        """Mở hộp chọn THƯ MỤC native (Windows) → trả đường dẫn (cho extension unpacked)."""
        import subprocess
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$f=New-Object System.Windows.Forms.FolderBrowserDialog;$f.Description='Chon thu muc';"
              "if($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){Write-Output $f.SelectedPath}")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                                 capture_output=True, text=True, timeout=180)
            return _ok({"path": out.stdout.strip()})
        except Exception as e:  # noqa: BLE001
            return _err(f"không mở được hộp chọn thư mục: {e}", 500)

    def _find_ffmpeg() -> str | None:
        import shutil
        f = shutil.which("ffmpeg")
        if f:
            return f
        for cand in ("ffmpeg.exe", "vendor/ffmpeg/ffmpeg.exe", "vendor/ffmpeg.exe"):
            if Path(cand).is_file():
                return str(Path(cand).resolve())
        return None

    @app.post("/api/v3/convert-media")
    def convert_media():
        """Convert video->.y4m hoặc audio->.wav bằng ffmpeg (cho camera/mic giả). Output vào asset/media/."""
        import subprocess
        b = request.get_json(silent=True) or {}
        src, to = b.get("path", ""), b.get("to", "y4m")
        if not src or not Path(src).is_file():
            return _err("file không tồn tại")
        if Path(src).suffix.lower().lstrip(".") == to.lower():
            return _ok({"path": src, "converted": False})       # đã đúng định dạng
        ff = _find_ffmpeg()
        if not ff:
            return _err("Chưa có ffmpeg để convert. Cài ffmpeg (ffmpeg.org) rồi thử lại, "
                        "hoặc tự convert sang .y4m/.wav.", 400)
        media = Path(profiles_root).parent / "media"
        media.mkdir(parents=True, exist_ok=True)
        out = media / (Path(src).stem + "." + to)
        cmd = ([ff, "-y", "-i", src, "-pix_fmt", "yuv420p", str(out)] if to == "y4m"
               else [ff, "-y", "-i", src, str(out)])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except Exception as e:  # noqa: BLE001
            return _err(f"convert lỗi: {e}", 500)
        if r.returncode != 0 or not out.is_file():
            return _err("convert thất bại: " + (r.stderr or "")[-300:], 500)
        return _ok({"path": str(out), "converted": True})

    @app.post("/api/v3/ai/workflow")
    def ai_workflow():
        """Sinh kịch bản automation từ lời. Đọc provider/key ở settings."""
        from . import ai
        task = (request.get_json(silent=True) or {}).get("task", "")
        s = _load_settings()
        if not s.get("ai_key"):
            return _err("Chưa cấu hình AI — vào Cài đặt → AI nhập API key", 400)
        res = ai.generate_workflow(task, lambda msgs: ai.call_llm_http(s, msgs))
        if res.get("error") and not res.get("steps"):
            return _err(res["error"])
        return _ok(res)

    # ---- Engines (đa-version: built-in + tải thêm theo yêu cầu) ----
    @app.get("/api/v3/engines")
    def engines_list():
        import os as _os
        from . import engine_store
        installed = engine_store.list_installed()
        iv = {e["version"] for e in installed}
        cat = engine_store.fetch_catalog(_load_settings().get("engines_url", ""))
        available = [c for c in cat if c.get("version") not in iv]
        def _cam_ok():
            try:
                import camoufox  # noqa: F401
                return True
            except Exception:  # noqa: BLE001
                return False
        engine_types = {                              # engine nào chạy được ngay (binary/thư viện đã có)
            "ovobrowser": bool(_os.environ.get("OVOBROWSER_BIN")),
            "fpchromium": bool(_os.environ.get("FPCHROMIUM_BIN")),
            "botbrowser": bool(_os.environ.get("BOTBROWSER_BIN")),
            "camoufox": _cam_ok(),
        }
        return _ok({"installed": installed, "available": available,
                    "engine_types": engine_types,
                    "status": engine_store.download_status()})

    @app.post("/api/v3/engines/download")
    def engines_download():
        from . import engine_store
        b = request.get_json(silent=True) or {}
        ver = b.get("version")
        if not ver:
            return _err("thiếu version")
        # Lấy url + sha256 TỪ CATALOG theo version (không tin url client -> chặn SSRF/gói lạ)
        cat = engine_store.fetch_catalog(_load_settings().get("engines_url", ""))
        entry = next((c for c in cat if c.get("version") == ver), None)
        if not entry or not entry.get("url"):
            return _err("version không có trong danh mục engine", 404)
        engine_store.download_async(ver, entry["url"], sha256=entry.get("sha256", ""))  # tải nền, poll /engines/status
        return _ok({"started": True, "version": ver})

    @app.get("/api/v3/engines/status")
    def engines_status():
        from . import engine_store
        return _ok(engine_store.download_status())

    @app.delete("/api/v3/engines/<version>")
    def engines_delete(version: str):
        from . import engine_store
        engine_store.delete_version(version)
        return _ok({"version": version, "deleted": True})

    # ---- Scripts (kịch bản lưu sẵn) ----
    @app.get("/api/v3/scripts")
    def scripts_list():
        return _ok(db.list_scripts())

    @app.post("/api/v3/scripts")
    def scripts_create():
        b = request.get_json(silent=True) or {}
        return _ok({"id": db.create_script(b.get("name", "Kịch bản"), b.get("steps") or [])})

    @app.put("/api/v3/scripts/<sid>")
    def scripts_update(sid: str):
        b = request.get_json(silent=True) or {}
        db.update_script(sid, name=b.get("name"), steps=b.get("steps"))
        return _ok({"id": sid})

    @app.delete("/api/v3/scripts/<sid>")
    def scripts_delete(sid: str):
        db.delete_script(sid)
        return _ok({"id": sid, "deleted": True})

    # ---- Runs (nhật ký chạy) ----
    @app.get("/api/v3/runs")
    def runs_list():
        return _ok(db.list_runs(int(request.args.get("limit", 100)),
                                request.args.get("profile_id")))

    @app.delete("/api/v3/runs")
    def runs_clear():
        db.clear_runs()
        return _ok({"cleared": True})

    # ---- Schedules (hẹn giờ) ----
    @app.get("/api/v3/schedules")
    def schedules_list():
        return _ok(db.list_schedules())

    @app.post("/api/v3/schedules")
    def schedules_create():
        b = request.get_json(silent=True) or {}
        b["next_run"] = scheduler_mod.compute_next(b).isoformat()   # không chạy ngay lúc tạo
        return _ok({"id": db.create_schedule(b)})

    @app.put("/api/v3/schedules/<sid>")
    def schedules_update(sid: str):
        b = request.get_json(silent=True) or {}
        if "enabled" in b and b["enabled"]:          # bật lại -> tính lại mốc kế
            b["next_run"] = scheduler_mod.compute_next(b).isoformat()
        db.update_schedule(sid, b)
        return _ok({"id": sid})

    @app.delete("/api/v3/schedules/<sid>")
    def schedules_delete(sid: str):
        db.delete_schedule(sid)
        return _ok({"id": sid, "deleted": True})

    @app.post("/api/v3/schedules/<sid>/run-now")
    def schedules_run_now(sid: str):
        s = next((x for x in db.list_schedules() if x["id"] == sid), None)
        if not s:
            return _err("schedule not found", 404)
        sc = db.get_script(s["script_id"]) if s.get("script_id") else None
        steps = (sc or {}).get("steps") or []
        fired = 0
        for ppid in s["profile_ids"]:
            _run_profile_script(ppid, steps, script_name=s["name"], source="manual")
            fired += 1
        return _ok({"fired": fired})

    @app.post("/api/v3/proxy/check")
    def proxy_check():
        raw = (request.get_json(silent=True) or {}).get("raw_proxy", "")
        return _ok(proxy_providers.check(raw))

    @app.get("/api/v3/proxies")
    def proxies_list():
        return _ok(db.list_proxies())

    @app.post("/api/v3/proxies")
    def proxies_create():
        b = request.get_json(silent=True) or {}
        return _ok({"id": db.create_proxy(b.get("raw_proxy", ""), b.get("meta"))})

    @app.delete("/api/v3/proxies/<prx>")
    def proxies_delete(prx: str):
        db.delete_proxy(prx)
        return _ok({"id": prx, "deleted": True})

    @app.post("/api/v3/proxies/<prx>/check")
    def proxy_row_check(prx: str):
        """Kiểm tra live 1 proxy trong bảng + LƯU kết quả vào meta (để dòng cập nhật, giữ qua refresh)."""
        row = next((x for x in db.list_proxies() if x["id"] == prx), None)
        if not row:
            return _err("proxy không tồn tại", 404)
        res = proxy_providers.check(row["raw_proxy"])
        from datetime import datetime, timezone
        meta = db.update_proxy_meta(prx, {
            "alive": res.get("alive"), "exit_ip": res.get("exit_ip"),
            "country": res.get("country"), "country_code": res.get("country_code", ""),
            "latency_ms": res.get("latency_ms"),
            "scheme": res.get("scheme"), "error": res.get("error"),
            "checked_at": datetime.now(timezone.utc).isoformat()})
        return _ok({**res, "id": prx, "meta": meta})

    @app.post("/api/v3/profiles/<pid>/proxy/from/<prx>")
    def assign_proxy_from_table(pid: str, prx: str):
        p = db.get_profile(pid)
        row = next((x for x in db.list_proxies() if x["id"] == prx), None)
        if not p or not row:
            return _err("profile hoặc proxy không tồn tại", 404)
        raw = proxy_providers.normalize_scheme(row["raw_proxy"])
        dyn = p.dynamic_data or {}
        dyn.setdefault("proxy", {})["raw_proxy"] = raw
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "raw_proxy": raw})

    # ---- groups (Nhóm) ----
    @app.get("/api/v3/groups")
    def groups_list():
        return _ok(db.list_groups())

    @app.post("/api/v3/groups")
    def groups_create():
        name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
        if not name:
            return _err("thiếu tên nhóm")
        return _ok({"id": db.create_group(name), "name": name})

    @app.post("/api/v3/groups/<gid>")
    def groups_rename(gid: str):
        name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
        if not name:
            return _err("thiếu tên nhóm")
        db.rename_group(gid, name)
        return _ok({"id": gid, "name": name})

    @app.delete("/api/v3/groups/<gid>")
    def groups_delete(gid: str):
        db.delete_group(gid)
        return _ok({"id": gid, "deleted": True})

    # ---- cookies ----
    @app.get("/api/v3/profiles/<pid>/cookies")
    def cookies_get(pid: str):
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        return _ok((p.dynamic_data or {}).get("cookies") or [])

    @app.post("/api/v3/profiles/<pid>/cookies")
    def cookies_set(pid: str):
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        b = request.get_json(silent=True) or {}
        cookies = parse_cookies(b.get("cookies", []))
        dyn = p.dynamic_data or {}
        dyn["cookies"] = cookies
        dyn["cookies_pending"] = cookies            # nạp vào trình duyệt ở lần Start tới
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "count": len(cookies)})

    # ---- extensions ----
    @app.get("/api/v3/profiles/<pid>/extensions")
    def ext_get(pid: str):
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        return _ok((p.dynamic_data or {}).get("extensions") or [])

    @app.post("/api/v3/profiles/<pid>/extensions")
    def ext_add(pid: str):
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        path = ((request.get_json(silent=True) or {}).get("path") or "").strip()
        if not path or not Path(path).is_dir():
            return _err("đường dẫn extension (thư mục unpacked) không tồn tại")
        dyn = p.dynamic_data or {}
        exts = dyn.get("extensions") or []
        if path not in exts:
            exts.append(path)
        dyn["extensions"] = exts
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "extensions": exts})

    @app.delete("/api/v3/profiles/<pid>/extensions")
    def ext_del(pid: str):
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        path = request.args.get("path", "")
        dyn = p.dynamic_data or {}
        dyn["extensions"] = [e for e in (dyn.get("extensions") or []) if e != path]
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "extensions": dyn["extensions"]})

    @app.post("/api/v3/profiles/<pid>/extensions/from-archive")
    def ext_from_archive(pid: str):
        """Nạp extension từ file .crx/.zip (path) hoặc URL -> giải nén ra asset/extensions/<pid>/<name> rồi đăng ký."""
        p = db.get_profile(pid)
        if not p:
            return _err("profile not found", 404)
        import io
        import ipaddress
        import shutil
        import socket
        import urllib.request
        import zipfile
        from urllib.parse import urlparse
        _MAX_DL = 100 * 1024 * 1024        # trần tải về 100MB
        _MAX_UNZIP = 300 * 1024 * 1024     # trần tổng dung lượng sau giải nén (chống zip-bomb)
        b = request.get_json(silent=True) or {}
        src = (b.get("path") or "").strip()
        url = (b.get("url") or "").strip()
        try:
            if url:
                u = urlparse(url)                              # chống SSRF: chỉ http/https, host không nội bộ
                if u.scheme not in ("http", "https") or not u.hostname:
                    return _err("URL không hợp lệ (chỉ http/https)")
                try:
                    _ips = {ai[4][0] for ai in socket.getaddrinfo(u.hostname, None)}
                except Exception:  # noqa: BLE001
                    return _err("không phân giải được tên miền")
                for _ip in _ips:
                    _a = ipaddress.ip_address(_ip)
                    if (_a.is_private or _a.is_loopback or _a.is_link_local
                            or _a.is_reserved or _a.is_multicast or _a.is_unspecified):
                        return _err("URL trỏ vào địa chỉ nội bộ — từ chối (chống SSRF)")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as _r:        # noqa: S310 — đã lọc host nội bộ
                    data = _r.read(_MAX_DL + 1)
                if len(data) > _MAX_DL:
                    return _err("file tải về quá lớn (>100MB)")
                name = (url.rstrip("/").split("/")[-1] or "ext").split("?")[0]
            elif src:
                if not Path(src).is_file():
                    return _err("file không tồn tại")
                data = Path(src).read_bytes()
                name = Path(src).stem
            else:
                return _err("thiếu path hoặc url")
        except Exception as e:  # noqa: BLE001
            return _err(f"không tải/đọc được: {e}")
        i = data.find(b"PK\x03\x04")                 # .crx = header + zip; tìm điểm bắt đầu zip
        if i < 0:
            return _err("không phải file .crx/.zip hợp lệ")
        name = "".join(c for c in name if c.isalnum() or c in "-_") or "ext"
        dest = Path(profiles_root).parent / "extensions" / pid / name
        try:
            zf = zipfile.ZipFile(io.BytesIO(data[i:]))
            if sum(zi.file_size for zi in zf.infolist()) > _MAX_UNZIP:   # chống zip-bomb
                return _err("gói giải nén quá lớn (>300MB) — nghi zip-bomb")
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True, exist_ok=True)
            zf.extractall(dest)
        except Exception as e:  # noqa: BLE001
            return _err(f"giải nén lỗi: {e}")
        if not (dest / "manifest.json").is_file():   # có khi lồng 1 cấp
            subs = [d for d in dest.iterdir() if d.is_dir() and (d / "manifest.json").is_file()]
            if subs:
                dest = subs[0]
            else:
                return _err("gói thiếu manifest.json (không phải extension hợp lệ)")
        dyn = p.dynamic_data or {}
        exts = dyn.get("extensions") or []
        ds = str(dest)
        if ds not in exts:
            exts.append(ds)
        dyn["extensions"] = exts
        db.set_dynamic_data(pid, dyn)
        return _ok({"id": pid, "extensions": exts, "folder": ds})

    @app.get("/api/v3/browsers")
    def browser_options():
        """5 skin cho dropdown Trình duyệt (Chrome/Edge/Opera/Brave/Firefox)."""
        return _ok(browser_profiles.options())

    # ---- settings (Cài đặt) ----
    @app.get("/api/v3/settings")
    def settings_get():
        return _ok({**_load_settings(), "profiles_root": profiles_root, "db": str(db_path)})

    @app.post("/api/v3/settings")
    def settings_set():
        s = _save_settings(request.get_json(silent=True) or {})
        log_event("settings", "Cập nhật cài đặt mặc định")
        return _ok(s)

    # ---- log ----
    @app.get("/api/v3/log")
    def log_get():
        return _ok(list(reversed(_log)))     # mới nhất lên đầu

    # ---- MCP (cho AI agent: Claude / Cursor) ----
    @app.get("/api/v3/mcp/tools")
    def mcp_tools():
        from .mcp_server import TOOLS
        return _ok([{"name": t["name"], "description": t["description"],
                     "params": list((t.get("inputSchema", {}).get("properties") or {}).keys()),
                     "required": t.get("inputSchema", {}).get("required") or []} for t in TOOLS])

    @app.get("/api/v3/mcp/config")
    def mcp_config():
        import os
        import sys
        cwd = str(Path(__file__).resolve().parent.parent)   # thư mục PinkAgc-Browser
        env = {"PINKAGC_DB": str(db_path), "PINKAGC_PROFILES": profiles_root}
        if os.environ.get("OVOBROWSER_BIN"):
            env["OVOBROWSER_BIN"] = os.environ["OVOBROWSER_BIN"]
        cfg = {"mcpServers": {"pinkagc-browser": {
            "command": sys.executable, "args": ["-m", "core.mcp_server"], "cwd": cwd, "env": env}}}
        return _ok({"config": cfg, "cwd": cwd, "python": sys.executable,
                    "add_cmd": f'claude mcp add pinkagc -- "{sys.executable}" -m core.mcp_server'})

    @app.get("/api/v3/endpoints")
    def endpoints():
        """Tự liệt kê mọi route /api/v3 (cho trang tài liệu Developer)."""
        out = []
        for r in app.url_map.iter_rules():
            if not str(r).startswith("/api/v3"):
                continue
            methods = sorted(m for m in r.methods if m in ("GET", "POST", "DELETE", "PUT", "PATCH"))
            out.append({"path": str(r), "methods": methods})
        out.sort(key=lambda x: x["path"])
        return _ok(out)

    @app.get("/api/v3/health")
    def health():
        return _ok({"app": brand.APP_NAME, "running": list(running),
                    "engines": engines.ENGINES, "profiles": len(db.list_profiles())})

    @app.get("/api/v3/version")
    def version():
        return _ok({"name": brand.APP_NAME, "version": brand.VERSION})

    @app.get("/api/v3/check-update")
    def check_update():
        """So phiên bản với manifest brand.UPDATE_URL (JSON {version,url,notes})."""
        from . import updater
        d = updater.check()
        d["frozen"] = updater.is_frozen()           # bản .exe mới self-update được
        return _ok(d)

    @app.post("/api/v3/update/apply")
    def update_apply():
        """Tải & cài bản mới (bản .exe). Nếu ok -> hẹn thoát app 1.5s để .bat thay exe rồi mở lại."""
        from . import updater
        info = updater.check()
        if not info.get("has_update"):
            return _err("Không có bản mới (hoặc chưa cấu hình UPDATE_URL).")
        ok, msg = updater.apply_update(info.get("url", ""), info.get("sha256", ""))
        if ok:
            import os as _os
            import threading
            threading.Timer(1.5, lambda: _os._exit(0)).start()   # thoát để _update.bat thay exe
            return _ok({"ok": True, "message": msg, "latest": info.get("latest")})
        return _err(msg)

    # ---- Cloud / Team sync (dùng team_server tự host làm "private server") ----
    def _team():
        """Trả (TeamClient, settings). Raise nếu chưa cấu hình URL."""
        s = _load_settings()
        url = (s.get("private_server_url") or "").strip()
        if not url:
            raise RuntimeError("Chưa cấu hình Private server URL ở Cài đặt.")
        from .team_client import TeamClient
        return TeamClient(url, s.get("team_token") or None), s

    @app.get("/api/v3/team/status")
    def team_status():
        s = _load_settings()
        return _ok({"url": s.get("private_server_url", ""), "logged_in": bool(s.get("team_token")),
                    "username": s.get("team_user", "")})

    @app.post("/api/v3/team/login")
    def team_login():
        b = request.get_json(silent=True) or {}
        if b.get("url"):
            _save_settings({"private_server_url": str(b["url"]).strip()})
        try:
            c, _ = _team()
        except RuntimeError as e:
            return _err(str(e))
        try:
            r = c.login(b.get("username", ""), b.get("password", ""))
        except Exception as e:  # noqa: BLE001
            return _err(f"Không kết nối server: {e}")
        if not r.get("success"):
            return _err(r.get("message", "Sai tài khoản/mật khẩu"), 401)
        _save_settings({"team_token": c.token, "team_user": b.get("username", "")})
        return _ok({"username": b.get("username", ""), "role": (r.get("data") or {}).get("role")})

    @app.post("/api/v3/team/register")
    def team_register():
        b = request.get_json(silent=True) or {}
        if b.get("url"):
            _save_settings({"private_server_url": str(b["url"]).strip()})
        try:
            c, _ = _team()
        except RuntimeError as e:
            return _err(str(e))
        try:
            r = c.register(b.get("username", ""), b.get("password", ""))
        except Exception as e:  # noqa: BLE001
            return _err(f"Không kết nối server: {e}")
        return _ok(r.get("data")) if r.get("success") else _err(r.get("message", "Đăng ký lỗi"))

    @app.post("/api/v3/team/logout")
    def team_logout():
        _save_settings({"team_token": "", "team_user": ""})
        return _ok({"logged_out": True})

    @app.post("/api/v3/team/sync")
    def team_sync():
        try:
            c, _ = _team()
        except RuntimeError as e:
            return _err(str(e))
        if not c.token:
            return _err("Chưa đăng nhập team.", 401)
        from .team_client import sync_down, sync_up
        try:
            up = sync_up(db, c)
            down = sync_down(db, c)
        except Exception as e:  # noqa: BLE001
            return _err(f"Sync lỗi: {e}")
        log_event("team", f"sync up {up.get('pushed',0)} / down {down}")
        return _ok({"pushed": up.get("pushed", 0), "pulled": down})

    @app.post("/api/v3/team/share")
    def team_share():
        b = request.get_json(silent=True) or {}
        try:
            c, _ = _team()
        except RuntimeError as e:
            return _err(str(e))
        if not c.token:
            return _err("Chưa đăng nhập team.", 401)
        try:
            r = c.share(b.get("profile_id", ""), b.get("username", ""), b.get("permission", "read"))
        except Exception as e:  # noqa: BLE001
            return _err(f"Không kết nối server: {e}")
        return _ok(r.get("data")) if r.get("success") else _err(r.get("message", "Share lỗi"), 403)

    # Scheduler nền: chạy kịch bản đã lưu theo lịch (daemon, tự tắt khi thoát process).
    _scheduler = scheduler_mod.Scheduler(
        db, lambda pid, steps, name, src: _run_profile_script(
            pid, steps, script_name=name, source=src))
    _scheduler.start()
    app.config["scheduler"] = _scheduler

    return app


def main():
    import argparse
    ap = argparse.ArgumentParser(description=f"{brand.APP_NAME} local API + UI")
    ap.add_argument("--db", default=brand.DEFAULT_DB)
    ap.add_argument("--profiles-root", default="asset/profiles")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    a = ap.parse_args()
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    Path(a.profiles_root).mkdir(parents=True, exist_ok=True)
    engines.cleanup_orphans(a.profiles_root)        # dọn browser mồ côi lần chạy trước (tránh kẹt khoá)
    print(f"{brand.APP_NAME}\nUI:  http://127.0.0.1:{a.port}/\nAPI: http://127.0.0.1:{a.port}/api/v3/")
    create_app(a.db, a.profiles_root).run(host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
