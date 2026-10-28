"""MCP server cho PinkAgc Browser — expose profile/proxy/automation làm MCP tools.

Khớp tính năng MCP của GPM (mcp_enabled/mcp_token). Giao thức MCP qua stdio = JSON-RPC 2.0
newline-delimited; viết tay (không thêm dep). Có thể thay bằng SDK `mcp` chính thức sau.

Chạy (cho client MCP như Claude):  python -m core.mcp_server
Đăng ký:  claude mcp add pinkagc -- python -m core.mcp_server
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

from . import automation, engines, proxy_providers
from .db import Database
from .fingerprint import generate, randomize_fields

PROTOCOL = "2024-11-05"


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Server:
    def __init__(self, db_path: str, profiles_root: str):
        self.db = Database(db_path)
        self.root = profiles_root
        self.running: dict[str, tuple] = {}
        Path(profiles_root).mkdir(parents=True, exist_ok=True)
        engines.cleanup_orphans(profiles_root)        # dọn browser mồ côi lần chạy trước

    # ---- tool impls ----
    def list_profiles(self) -> Any:
        return [{"id": p.id, "name": p.name,
                 "browser": (p.fingerprint_data.get("browser", {}) or {}).get("browser_type"),
                 "running": p.id in self.running} for p in self.db.list_profiles()]

    def create_profile(self, name="Profile", os="Windows", browser="Chrome", engine=None) -> Any:
        dyn = {"engine": engine} if engine else {}
        p = self.db.create_profile(name, generate(os_type=os, browser_type=browser), dynamic_data=dyn)
        return {"id": p.id, "name": p.name}

    def start_profile(self, id, headless=False) -> Any:
        p = self.db.get_profile(id)
        if not p: return {"error": "not found"}
        if id in self.running: return {"id": id, "ws_endpoint": self.running[id][1], "already_running": True}
        eng = engines.resolve_engine(p, None)
        handle, ws = engines.serve(eng, p, self.root, headless=headless)
        self.running[id] = (handle, ws, eng)
        self.db.mark_run(id)
        return {"id": id, "engine": eng, "ws_endpoint": ws}

    def stop_profile(self, id) -> Any:
        it = self.running.pop(id, None)
        if it:
            engines.graceful_stop(it[0], it[1], it[2])   # đóng mềm Chromium rồi terminate
        return {"id": id, "stopped": bool(it)}

    def clone_profile(self, id, name=None) -> Any:
        c = self.db.clone_profile(id, name)
        return {"id": c.id, "name": c.name} if c else {"error": "not found"}

    def randomize_fingerprint(self, id, fields=None) -> Any:
        p = self.db.get_profile(id)
        if not p: return {"error": "not found"}
        fp = randomize_fields(p.fingerprint_data, fields)
        dyn = p.dynamic_data or {}; dyn["fp_seed"] = __import__("uuid").uuid4().int % (2 ** 31)
        self.db.update_profile(id, fingerprint_data=fp, dynamic_data=dyn)
        return {"id": id, "randomized": True}

    def set_proxy(self, id, raw_proxy=None, provider=None, api_key="", rotate=False) -> Any:
        p = self.db.get_profile(id)
        if not p: return {"error": "not found"}
        raw = raw_proxy or ""
        if provider:
            raw = (proxy_providers.rotate if rotate else proxy_providers.get_current)(provider, api_key)
        raw = proxy_providers.normalize_scheme(raw)     # gắn socks5://… nếu detect được
        dyn = p.dynamic_data or {}; dyn.setdefault("proxy", {})["raw_proxy"] = raw
        self.db.set_dynamic_data(id, dyn)
        return {"id": id, "raw_proxy": raw}

    def check_proxy(self, raw_proxy) -> Any:
        return proxy_providers.check(raw_proxy)

    def run_script(self, id, steps, headless=True) -> Any:
        errs = automation.validate_script(steps)
        if errs: return {"ok": False, "log": errs}
        started = id not in self.running
        if started:
            r = self.start_profile(id, headless=headless)
            if r.get("error"): return r
        ws, eng = self.running[id][1], self.running[id][2]
        try:
            return automation.run_script(ws, steps, engine=eng, workdir=str(Path(self.root) / (self.db.get_profile(id).storage_path or id)))
        finally:
            if started: self.stop_profile(id)

    # ---- MCP dispatch ----
    def dispatch(self, name: str, args: dict) -> Any:
        fn = getattr(self, name, None)
        if not callable(fn) or name.startswith("_") or name in ("dispatch", "handle"):
            raise ValueError(f"tool không tồn tại: {name}")
        return fn(**args)

    def handle(self, msg: dict) -> dict | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            res = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "pinkagc-browser", "version": "1.0"}}
        elif method in ("notifications/initialized", "notifications/cancelled"):
            return None                                   # notification -> không trả
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            try:
                out = self.dispatch(name, args)
                res = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
            except Exception as e:  # noqa: BLE001
                return {"jsonrpc": "2.0", "id": mid,
                        "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method lạ: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}


def _tool(name, desc, props, required=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": list(required)}}


TOOLS = [
    _tool("list_profiles", "Liệt kê profile", {}),
    _tool("create_profile", "Tạo profile mới",
          {"name": {"type": "string"}, "os": {"type": "string"}, "browser": {"type": "string"},
           "engine": {"type": "string"}}),
    _tool("start_profile", "Mở profile, trả ws CDP",
          {"id": {"type": "string"}, "headless": {"type": "boolean"}}, ("id",)),
    _tool("stop_profile", "Đóng profile", {"id": {"type": "string"}}, ("id",)),
    _tool("clone_profile", "Nhân bản profile (fingerprint mới)",
          {"id": {"type": "string"}, "name": {"type": "string"}}, ("id",)),
    _tool("randomize_fingerprint", "Random lại fingerprint",
          {"id": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}}, ("id",)),
    _tool("set_proxy", "Gán proxy (raw hoặc provider)",
          {"id": {"type": "string"}, "raw_proxy": {"type": "string"}, "provider": {"type": "string"},
           "api_key": {"type": "string"}, "rotate": {"type": "boolean"}}, ("id",)),
    _tool("check_proxy", "Kiểm tra proxy sống/trễ/exit IP", {"raw_proxy": {"type": "string"}}, ("raw_proxy",)),
    _tool("run_script", "Chạy kịch bản automation trên profile",
          {"id": {"type": "string"}, "steps": {"type": "array"}, "headless": {"type": "boolean"}}, ("id", "steps")),
]


def serve_stdio(db_path: str, profiles_root: str) -> None:
    # Ép UTF-8: client (Claude Code...) chạy không set PYTHONIOENCODING -> stdout cp1252 trên Windows
    # sẽ crash khi ghi mô tả tool tiếng Việt (charmap). Reconfigure đảm bảo chạy mọi nơi.
    for _s in (sys.stdout, sys.stdin):
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    srv = Server(db_path, profiles_root)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = srv.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    serve_stdio(os.environ.get("PINKAGC_DB", "asset/pinkagc.db"),
                os.environ.get("PINKAGC_PROFILES", "asset/profiles"))


if __name__ == "__main__":
    main()
