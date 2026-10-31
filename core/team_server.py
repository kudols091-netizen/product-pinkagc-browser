"""Team server — đồng bộ profile đa máy/đa người, tự host (như "private server" của GPM).

Xây trên schema SQLite sẵn (profiles.created_by = owner) + 3 bảng team: users/sessions/shares.
Auth bearer token (pbkdf2), role admin/member, share theo quyền read<run<write, sync push/pull.

Chạy:  python -m core.team_server --db team.db --port 8787
Client trỏ tới server qua core/team_client.py.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from flask import Flask, g, jsonify, request

from .db import Database, _now, _uuid

_TEAM_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, pwd_hash TEXT NOT NULL,
  salt TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, user_id TEXT NOT NULL,
  permission TEXT NOT NULL DEFAULT 'read', created_at TEXT NOT NULL,
  UNIQUE(profile_id, user_id));
"""
_PERM_RANK = {"read": 1, "run": 2, "write": 3}
_SESSION_TTL = 30 * 86400          # token sống 30 ngày


def _hash(pwd: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), 100_000).hex()


class TeamStore:
    def __init__(self, db: Database):
        self.db = db
        with db._lock:
            db.conn.executescript(_TEAM_SCHEMA)
            db.conn.commit()

    def _q(self, sql: str, args=()):
        with self.db._lock:
            return self.db.conn.execute(sql, args).fetchall()

    def _x(self, sql: str, args=()):
        with self.db._lock:
            self.db.conn.execute(sql, args); self.db.conn.commit()

    # ---- auth ----
    def register(self, username: str, password: str) -> dict:
        if self._q("SELECT 1 FROM users WHERE username=?", (username,)):
            raise ValueError("username đã tồn tại")
        first = not self._q("SELECT 1 FROM users LIMIT 1")
        uid, salt = _uuid(), secrets.token_hex(16)
        role = "admin" if first else "member"          # user đầu tiên = admin
        self._x("INSERT INTO users (id,username,pwd_hash,salt,role,created_at) VALUES (?,?,?,?,?,?)",
                (uid, username, _hash(password, salt), salt, role, _now()))
        return {"id": uid, "username": username, "role": role}

    def login(self, username: str, password: str) -> Optional[dict]:
        r = self._q("SELECT * FROM users WHERE username=?", (username,))
        if not r or _hash(password, r[0]["salt"]) != r[0]["pwd_hash"]:
            return None
        token = secrets.token_urlsafe(32)
        self._x("INSERT INTO sessions (token,user_id,created_at) VALUES (?,?,?)",
                (token, r[0]["id"], _now()))
        return {"token": token, "role": r[0]["role"], "username": username, "id": r[0]["id"]}

    def user_for_token(self, token: str) -> Optional[dict]:
        r = self._q("SELECT u.*, s.created_at AS _sc FROM sessions s JOIN users u ON u.id=s.user_id "
                    "WHERE s.token=?", (token,))
        if not r:
            return None
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(r[0]["_sc"])).total_seconds()
        except (ValueError, TypeError):
            age = 0
        if age > _SESSION_TTL:                           # token hết hạn -> xoá, buộc login lại
            self._x("DELETE FROM sessions WHERE token=?", (token,))
            return None
        return {"id": r[0]["id"], "username": r[0]["username"], "role": r[0]["role"]}

    # ---- visibility / share ----
    def can_access(self, user: dict, pid: str, need: str = "read") -> bool:
        if user["role"] == "admin":
            return True
        owner = self._q("SELECT created_by FROM profiles WHERE id=?", (pid,))
        if owner and owner[0]["created_by"] == user["id"]:
            return True
        sh = self._q("SELECT permission FROM shares WHERE profile_id=? AND user_id=?", (pid, user["id"]))
        return bool(sh) and _PERM_RANK.get(sh[0]["permission"], 0) >= _PERM_RANK[need]

    def list_visible(self, user: dict, since: str | None = None) -> list[dict]:
        if user["role"] == "admin":
            rows = self._q("SELECT * FROM profiles WHERE is_deleted=0" +
                           (" AND updated_at>?" if since else ""), ((since,) if since else ()))
        else:
            rows = self._q(
                "SELECT DISTINCT p.* FROM profiles p LEFT JOIN shares s ON s.profile_id=p.id "
                "WHERE p.is_deleted=0 AND (p.created_by=? OR s.user_id=?)" +
                (" AND p.updated_at>?" if since else ""),
                (user["id"], user["id"]) + ((since,) if since else ()))
        from .db import Profile
        return [Profile._from_row(r).to_dict() | {"owner": r["created_by"], "updated_at": r["updated_at"]}
                for r in rows]

    def push(self, user: dict, profiles: list[dict]) -> list[str]:
        out = []
        for p in profiles:
            pid = p.get("id") or _uuid()
            # chỉ owner/admin được đè profile đã tồn tại
            if not self.can_access(user, pid, "write") and self._q("SELECT 1 FROM profiles WHERE id=?", (pid,)):
                continue
            self.db.upsert_profile(pid, p.get("name") or "Profile",
                                   p.get("fingerprint_data") or {}, p.get("dynamic_data") or {},
                                   owner=user["id"], group_id=p.get("group_id"),
                                   updated_at=p.get("updated_at"))
            out.append(pid)
        return out

    def share(self, owner: dict, pid: str, to_username: str, permission: str) -> dict:
        if permission not in _PERM_RANK:
            raise ValueError(f"permission không hợp lệ: {permission} ({list(_PERM_RANK)})")
        if not self.can_access(owner, pid, "write"):
            raise PermissionError("không có quyền share profile này")
        u = self._q("SELECT id FROM users WHERE username=?", (to_username,))
        if not u:
            raise ValueError("user nhận không tồn tại")
        self._x("INSERT INTO shares (profile_id,user_id,permission,created_at) VALUES (?,?,?,?) "
                "ON CONFLICT(profile_id,user_id) DO UPDATE SET permission=excluded.permission",
                (pid, u[0]["id"], permission, _now()))
        return {"profile_id": pid, "shared_with": to_username, "permission": permission}


def create_team_app(db_path: str | Path) -> Flask:
    app = Flask(__name__)
    store = TeamStore(Database(db_path))

    def _ok(d=None, **e): return jsonify({"success": True, "data": d, **e})
    def _err(m, c=400): return jsonify({"success": False, "message": m}), c

    def auth(fn):
        @wraps(fn)
        def w(*a, **k):
            tok = request.headers.get("Authorization", "").replace("Bearer ", "")  # chỉ Bearer header (token qua query -> lọt log)
            u = store.user_for_token(tok)
            if not u:
                return _err("unauthorized", 401)
            g.user = u
            return fn(*a, **k)
        return w

    @app.post("/team/register")
    def register():
        b = request.get_json(silent=True) or {}
        try:
            return _ok(store.register(b.get("username", ""), b.get("password", "")))
        except ValueError as e:
            return _err(str(e))

    @app.post("/team/login")
    def login():
        b = request.get_json(silent=True) or {}
        s = store.login(b.get("username", ""), b.get("password", ""))
        return _ok(s) if s else _err("sai tài khoản/mật khẩu", 401)

    @app.get("/team/me")
    @auth
    def me():
        return _ok(g.user)

    @app.get("/team/profiles")
    @auth
    def list_profiles():
        return _ok(store.list_visible(g.user, request.args.get("since")))

    @app.post("/team/profiles/push")
    @auth
    def push():
        ids = store.push(g.user, (request.get_json(silent=True) or {}).get("profiles", []))
        return _ok({"pushed": len(ids), "ids": ids})

    @app.post("/team/profiles/<pid>/share")
    @auth
    def share(pid: str):
        b = request.get_json(silent=True) or {}
        try:
            return _ok(store.share(g.user, pid, b.get("username", ""), b.get("permission", "read")))
        except (ValueError, PermissionError) as e:
            return _err(str(e), 403 if isinstance(e, PermissionError) else 400)

    @app.get("/team/profiles/<pid>")
    @auth
    def get_one(pid: str):
        if not store.can_access(g.user, pid, "read"):
            return _err("không có quyền", 403)
        p = store.db.get_profile(pid)
        return _ok(p.to_dict()) if p else _err("not found", 404)

    return app


def main():
    import argparse
    ap = argparse.ArgumentParser(description="PinkAgc Team Server (self-host sync)")
    ap.add_argument("--db", default="asset/team.db")
    ap.add_argument("--host", default="127.0.0.1")   # mở LAN thì --host 0.0.0.0 + reverse-proxy TLS
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    print(f"PinkAgc Team Server → http://{a.host}:{a.port}/team/")
    create_team_app(a.db).run(host=a.host, port=a.port)


if __name__ == "__main__":
    main()
