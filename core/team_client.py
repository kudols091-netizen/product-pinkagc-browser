"""Team client — đồng bộ DB local ↔ team server. Transport tiêm được (test không cần mạng).

sync_down: pull profile visible từ server -> upsert vào DB local.
sync_up  : push profile local -> server (owner = user đang đăng nhập).
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Optional

from .db import Database

Transport = Callable[[str, str, Optional[dict], Optional[str]], dict]


def _http_transport(base_url: str) -> Transport:
    base = base_url.rstrip("/")

    def t(method: str, path: str, body: dict | None, token: str | None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    return t


class TeamClient:
    def __init__(self, base_url: str = "", token: str | None = None, *, _transport: Transport | None = None):
        self.t = _transport or _http_transport(base_url)
        self.token = token

    def register(self, username: str, password: str) -> dict:
        return self.t("POST", "/team/register", {"username": username, "password": password}, None)

    def login(self, username: str, password: str) -> dict:
        r = self.t("POST", "/team/login", {"username": username, "password": password}, None)
        if r.get("success"):
            self.token = r["data"]["token"]
        return r

    def pull(self, since: str | None = None) -> list[dict]:
        path = "/team/profiles" + (f"?since={since}" if since else "")
        return self.t("GET", path, None, self.token).get("data", [])

    def push(self, profiles: list[dict]) -> dict:
        return self.t("POST", "/team/profiles/push", {"profiles": profiles}, self.token).get("data", {})

    def share(self, pid: str, username: str, permission: str = "read") -> dict:
        return self.t("POST", f"/team/profiles/{pid}/share",
                      {"username": username, "permission": permission}, self.token)


def sync_down(local: Database, client: TeamClient, user_id: str = "cloud", since: str | None = None) -> int:
    """Pull profile từ server về local (upsert). Trả số profile đồng bộ."""
    n = 0
    for p in client.pull(since):
        local.upsert_profile(p["id"], p.get("name") or "Profile",
                             p.get("fingerprint_data") or {}, p.get("dynamic_data") or {},
                             owner=p.get("owner", user_id), group_id=p.get("group_id"),
                             updated_at=p.get("updated_at"))
        n += 1
    return n


def sync_up(local: Database, client: TeamClient) -> dict:
    """Push toàn bộ profile local lên server."""
    return client.push([p.to_dict() for p in local.list_profiles()])   # to_dict đã mang updated_at thật
