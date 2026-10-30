"""SQLite layer — schema tương thích 1:1 với GPM Login (asset/database.db).

Có thể trỏ thẳng vào DB của GPM để đọc/di cư profile, hoặc tạo DB mới cho clone.
Schema lấy từ RE: _notes/03-client-re.md §3C.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, "order" INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, group_id TEXT,
  storage_path TEXT NOT NULL, fingerprint_data TEXT NOT NULL, dynamic_data TEXT NOT NULL,
  last_run_by TEXT, last_run_at TEXT,
  is_deleted INTEGER NOT NULL DEFAULT 0, deleted_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT,
  FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS proxies (
  id TEXT PRIMARY KEY, raw_proxy TEXT NOT NULL DEFAULT '', meta_data TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  created_by INTEGER NOT NULL DEFAULT 0, updated_by INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tags (
  id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'proxy'
);
CREATE TABLE IF NOT EXISTS profile_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT, tag_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
  FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS proxy_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT, proxy_id TEXT, tag_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE,
  FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS scripts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, steps TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, profile_id TEXT, profile_name TEXT, script_name TEXT,
  ok INTEGER, source TEXT NOT NULL DEFAULT 'manual',
  started_at TEXT NOT NULL, finished_at TEXT, log TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, script_id TEXT,
  profile_ids TEXT NOT NULL DEFAULT '[]', kind TEXT NOT NULL DEFAULT 'interval',
  interval_min INTEGER NOT NULL DEFAULT 60, at_time TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1, last_run TEXT, next_run TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_started   ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_profiles_group_id   ON profiles(group_id);
CREATE INDEX IF NOT EXISTS idx_profiles_is_deleted ON profiles(is_deleted);
CREATE INDEX IF NOT EXISTS idx_profile_tags_pid    ON profile_tags(profile_id);
CREATE INDEX IF NOT EXISTS idx_profile_tags_tid    ON profile_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_proxy_tags_pid      ON proxy_tags(proxy_id);
CREATE INDEX IF NOT EXISTS idx_proxy_tags_tid      ON proxy_tags(tag_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class Profile:
    id: str
    name: str
    fingerprint_data: dict[str, Any]
    dynamic_data: dict[str, Any] = field(default_factory=dict)
    group_id: Optional[str] = None
    storage_path: str = ""          # thư mục user-data-dir của profile (relative tới profiles root)
    last_run_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def _from_row(cls, r: sqlite3.Row) -> "Profile":
        return cls(
            id=r["id"], name=r["name"], group_id=r["group_id"],
            storage_path=r["storage_path"],
            fingerprint_data=json.loads(r["fingerprint_data"] or "{}"),
            dynamic_data=json.loads(r["dynamic_data"] or "{}"),
            last_run_at=r["last_run_at"],
            updated_at=r["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "group_id": self.group_id,
                "fingerprint_data": self.fingerprint_data, "dynamic_data": self.dynamic_data,
                "updated_at": self.updated_at}


class Database:
    """Pool connection theo thread + WAL: đọc song song, ghi serialize ở mức SQLite (busy_timeout tự chờ).

    Mỗi thread (Flask xử lý request đa luồng + launch nhiều profile) có connection RIÊNG qua
    threading.local -> bỏ nút cổ chai 1-connection+global-lock cũ. WAL cho reader không bị chặn khi
    có writer; busy_timeout=5s để ghi tranh chấp tự chờ thay vì "database is locked".
    `self.conn` là property trả connection của thread hiện tại (giữ API cũ cho team_server).
    `self._lock` vẫn còn cho team_server dùng `with db._lock:` (op nội bộ db KHÔNG cần nữa).
    """
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        self._lock = threading.Lock()          # giữ cho team_server (with db._lock); db nội bộ không dùng
        boot = self._new_conn()                # bootstrap: tạo schema + bật WAL (persistent) 1 lần
        boot.executescript(SCHEMA)
        boot.commit()
        self._local.conn = boot

    def _new_conn(self) -> sqlite3.Connection:
        # timeout=30: fallback ngoài busy_timeout. check_same_thread=False: an toàn vì conn thuộc riêng 1 thread.
        c = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")       # reader không bị writer chặn (persistent theo file DB)
        c.execute("PRAGMA synchronous=NORMAL")     # nhanh hơn, vẫn an toàn dưới WAL (chỉ mất txn cuối khi mất điện)
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=5000")      # ghi tranh chấp: chờ tới 5s rồi mới báo lock
        return c

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self._new_conn()
        return c

    # --- profiles ---
    def create_profile(self, name: str, fingerprint_data: dict, *,
                        dynamic_data: dict | None = None, group_id: str | None = None,
                        storage_path: str | None = None, created_by: str = "clone") -> Profile:
        pid = _uuid()
        sp = storage_path or pid           # GPM dùng chính uuid làm tên thư mục
        now = _now()
        self.conn.execute(
            "INSERT INTO profiles (id,name,group_id,storage_path,fingerprint_data,dynamic_data,"
            "is_deleted,created_at,updated_at,created_by,updated_by) VALUES (?,?,?,?,?,?,0,?,?,?,?)",
            (pid, name, group_id, sp, json.dumps(fingerprint_data, ensure_ascii=False),
             json.dumps(dynamic_data or {}, ensure_ascii=False), now, now, created_by, created_by),
        )
        self.conn.commit()
        return self.get_profile(pid)  # type: ignore[return-value]

    def upsert_profile(self, pid: str, name: str, fingerprint_data: dict, dynamic_data: dict,
                       *, owner: str, group_id: str | None = None, updated_at: str | None = None) -> None:
        """Ghi/đè profile theo id cho sẵn (dùng cho sync team). Giữ created_by (owner) khi update."""
        now = updated_at or _now()
        self.conn.execute(
            "INSERT INTO profiles (id,name,group_id,storage_path,fingerprint_data,dynamic_data,"
            "is_deleted,created_at,updated_at,created_by,updated_by) VALUES (?,?,?,?,?,?,0,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, group_id=excluded.group_id, "
            "fingerprint_data=excluded.fingerprint_data, dynamic_data=excluded.dynamic_data, "
            "updated_at=excluded.updated_at, is_deleted=0",
            (pid, name, group_id, pid, json.dumps(fingerprint_data, ensure_ascii=False),
             json.dumps(dynamic_data, ensure_ascii=False), now, now, owner, owner))
        self.conn.commit()

    def get_profile(self, pid: str) -> Optional[Profile]:
        r = self.conn.execute(
            "SELECT * FROM profiles WHERE id=? AND is_deleted=0", (pid,)).fetchone()
        return Profile._from_row(r) if r else None

    def list_profiles(self, group_id: str | None = None) -> list[Profile]:
        if group_id:
            rows = self.conn.execute(
                "SELECT * FROM profiles WHERE is_deleted=0 AND group_id=? ORDER BY created_at",
                (group_id,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM profiles WHERE is_deleted=0 ORDER BY created_at").fetchall()
        return [Profile._from_row(r) for r in rows]

    def update_fingerprint(self, pid: str, fingerprint_data: dict) -> None:
        self.conn.execute(
            "UPDATE profiles SET fingerprint_data=?, updated_at=? WHERE id=?",
            (json.dumps(fingerprint_data, ensure_ascii=False), _now(), pid))
        self.conn.commit()

    def set_dynamic_data(self, pid: str, dynamic_data: dict) -> None:
        self.conn.execute(
            "UPDATE profiles SET dynamic_data=?, updated_at=? WHERE id=?",
            (json.dumps(dynamic_data, ensure_ascii=False), _now(), pid))
        self.conn.commit()

    def mark_run(self, pid: str, by: str = "clone") -> None:
        self.conn.execute("UPDATE profiles SET last_run_at=?, last_run_by=? WHERE id=?",
                          (_now(), by, pid))
        self.conn.commit()

    def delete_profile(self, pid: str) -> None:
        self.conn.execute(
            "UPDATE profiles SET is_deleted=1, deleted_at=? WHERE id=?", (_now(), pid))
        self.conn.commit()

    # --- lifecycle (Phase B) ---
    def update_profile(self, pid: str, *, name: str | None = None, group_id: str | None = ...,
                       fingerprint_data: dict | None = None, dynamic_data: dict | None = None) -> None:
        sets, vals = [], []
        if name is not None:
            sets.append("name=?"); vals.append(name)
        if group_id is not ...:                       # ... = không đụng; None = bỏ group
            sets.append("group_id=?"); vals.append(group_id)
        if fingerprint_data is not None:
            sets.append("fingerprint_data=?"); vals.append(json.dumps(fingerprint_data, ensure_ascii=False))
        if dynamic_data is not None:
            sets.append("dynamic_data=?"); vals.append(json.dumps(dynamic_data, ensure_ascii=False))
        if not sets:
            return
        sets.append("updated_at=?"); vals.append(_now()); vals.append(pid)
        self.conn.execute(f"UPDATE profiles SET {','.join(sets)} WHERE id=?", vals)
        self.conn.commit()

    def clone_profile(self, pid: str, new_name: str | None = None) -> Optional[Profile]:
        src = self.get_profile(pid)
        if not src:
            return None
        import copy
        dyn = copy.deepcopy(src.dynamic_data or {})
        dyn["fp_seed"] = uuid.uuid4().int % (2 ** 31)   # clone = cấu hình giống, FINGERPRINT MỚI (tránh linkable)
        return self.create_profile(new_name or f"{src.name} copy",
                                   copy.deepcopy(src.fingerprint_data), dynamic_data=dyn,
                                   group_id=src.group_id)

    def set_meta(self, pid: str, *, note: str | None = None, color: str | None = None,
                 pinned: bool | None = None, tags: list | None = None) -> None:
        p = self.get_profile(pid)
        if not p:
            return
        meta = (p.dynamic_data or {}).get("meta", {})
        if note is not None: meta["note"] = note
        if color is not None: meta["color"] = color
        if pinned is not None: meta["pinned"] = pinned
        if tags is not None: meta["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        dyn = p.dynamic_data or {}; dyn["meta"] = meta
        self.set_dynamic_data(pid, dyn)

    def list_deleted(self) -> list[Profile]:
        rows = self.conn.execute(
            "SELECT * FROM profiles WHERE is_deleted=1 ORDER BY deleted_at DESC").fetchall()
        return [Profile._from_row(r) for r in rows]

    def restore_profile(self, pid: str) -> None:
        self.conn.execute(
            "UPDATE profiles SET is_deleted=0, deleted_at=NULL, updated_at=? WHERE id=?",
            (_now(), pid))
        self.conn.commit()

    def purge_profile(self, pid: str) -> None:
        self.conn.execute("DELETE FROM profiles WHERE id=?", (pid,))
        self.conn.commit()

    # --- proxies table (Phase B) ---
    def create_proxy(self, raw_proxy: str, meta: dict | None = None) -> str:
        prx, now = _uuid(), _now()
        self.conn.execute(
            "INSERT INTO proxies (id,raw_proxy,meta_data,created_at,updated_at) VALUES (?,?,?,?,?)",
            (prx, raw_proxy, json.dumps(meta or {}, ensure_ascii=False), now, now))
        self.conn.commit()
        return prx

    def list_proxies(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM proxies ORDER BY created_at").fetchall()
        return [{"id": r["id"], "raw_proxy": r["raw_proxy"],
                 "meta": json.loads(r["meta_data"] or "{}")} for r in rows]

    def delete_proxy(self, prx: str) -> None:
        self.conn.execute("DELETE FROM proxies WHERE id=?", (prx,))
        self.conn.commit()

    def update_proxy_meta(self, prx: str, meta: dict) -> dict:
        """Merge meta (kết quả kiểm tra: alive/exit_ip/country/latency_ms/checked_at) vào proxy -> persist."""
        row = self.conn.execute("SELECT meta_data FROM proxies WHERE id=?", (prx,)).fetchone()
        base = json.loads((row["meta_data"] if row else None) or "{}")
        base.update(meta)
        self.conn.execute("UPDATE proxies SET meta_data=?, updated_at=? WHERE id=?",
                          (json.dumps(base, ensure_ascii=False), _now(), prx))
        self.conn.commit()
        return base

    # --- groups ---
    def create_group(self, name: str) -> str:
        gid, now = _uuid(), _now()
        self.conn.execute(
            "INSERT INTO groups (id,name,\"order\",created_at,updated_at) VALUES (?,?,0,?,?)",
            (gid, name, now, now))
        self.conn.commit()
        return gid

    def list_groups(self) -> list[dict]:
        """Danh sách nhóm + số profile mỗi nhóm."""
        rows = self.conn.execute(
            "SELECT g.id, g.name, "
            "(SELECT COUNT(*) FROM profiles p WHERE p.group_id=g.id AND p.is_deleted=0) AS count "
            "FROM groups g ORDER BY g.\"order\", g.created_at").fetchall()
        return [{"id": r["id"], "name": r["name"], "count": r["count"]} for r in rows]

    def rename_group(self, gid: str, name: str) -> None:
        self.conn.execute("UPDATE groups SET name=?, updated_at=? WHERE id=?", (name, _now(), gid))
        self.conn.commit()

    def delete_group(self, gid: str) -> None:
        """Xoá nhóm; profile trong nhóm về group_id=NULL (FK ON DELETE SET NULL)."""
        self.conn.execute("DELETE FROM groups WHERE id=?", (gid,))
        self.conn.commit()

    # --- scripts (kịch bản automation lưu sẵn) ---
    def create_script(self, name: str, steps: list) -> str:
        sid, now = _uuid(), _now()
        self.conn.execute(
            "INSERT INTO scripts (id,name,steps,created_at,updated_at) VALUES (?,?,?,?,?)",
            (sid, name, json.dumps(steps, ensure_ascii=False), now, now))
        self.conn.commit()
        return sid

    def list_scripts(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM scripts ORDER BY updated_at DESC").fetchall()
        return [{"id": r["id"], "name": r["name"], "steps": json.loads(r["steps"] or "[]"),
                 "updated_at": r["updated_at"]} for r in rows]

    def get_script(self, sid: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        return {"id": r["id"], "name": r["name"], "steps": json.loads(r["steps"] or "[]"),
                "updated_at": r["updated_at"]} if r else None

    def update_script(self, sid: str, *, name: str | None = None, steps: list | None = None) -> None:
        sets, vals = [], []
        if name is not None:
            sets.append("name=?"); vals.append(name)
        if steps is not None:
            sets.append("steps=?"); vals.append(json.dumps(steps, ensure_ascii=False))
        if not sets:
            return
        sets.append("updated_at=?"); vals.append(_now()); vals.append(sid)
        self.conn.execute(f"UPDATE scripts SET {','.join(sets)} WHERE id=?", vals)
        self.conn.commit()

    def delete_script(self, sid: str) -> None:
        self.conn.execute("DELETE FROM scripts WHERE id=?", (sid,))
        self.conn.commit()

    # --- runs (nhật ký chạy automation) ---
    def add_run(self, profile_id: str, profile_name: str, script_name: str,
                source: str = "manual") -> str:
        rid = _uuid()
        self.conn.execute(
            "INSERT INTO runs (id,profile_id,profile_name,script_name,source,started_at) "
            "VALUES (?,?,?,?,?,?)", (rid, profile_id, profile_name, script_name, source, _now()))
        self.conn.commit()
        return rid

    def finish_run(self, rid: str, ok: bool, log: list | None = None, data: dict | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET ok=?, finished_at=?, log=?, data=? WHERE id=?",
            (1 if ok else 0, _now(), json.dumps(log or [], ensure_ascii=False),
             json.dumps(data or {}, ensure_ascii=False), rid))
        self.conn.commit()

    def list_runs(self, limit: int = 100, profile_id: str | None = None) -> list[dict]:
        if profile_id:
            rows = self.conn.execute(
                "SELECT * FROM runs WHERE profile_id=? ORDER BY started_at DESC LIMIT ?",
                (profile_id, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "profile_id": r["profile_id"], "profile_name": r["profile_name"],
                 "script_name": r["script_name"], "source": r["source"],
                 "ok": None if r["ok"] is None else bool(r["ok"]),
                 "started_at": r["started_at"], "finished_at": r["finished_at"],
                 "log": json.loads(r["log"] or "[]")} for r in rows]

    def clear_runs(self) -> None:
        self.conn.execute("DELETE FROM runs"); self.conn.commit()

    # --- schedules (hẹn giờ chạy kịch bản) ---
    def create_schedule(self, d: dict) -> str:
        sid, now = _uuid(), _now()
        self.conn.execute(
            "INSERT INTO schedules (id,name,script_id,profile_ids,kind,interval_min,at_time,"
            "enabled,next_run,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sid, d.get("name", "Lịch"), d.get("script_id"),
             json.dumps(d.get("profile_ids") or [], ensure_ascii=False),
             d.get("kind", "interval"), int(d.get("interval_min", 60) or 60),
             d.get("at_time", ""), 1 if d.get("enabled", True) else 0,
             d.get("next_run"), now, now))
        self.conn.commit()
        return sid

    def list_schedules(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM schedules ORDER BY created_at").fetchall()
        return [self._sched_row(r) for r in rows]

    @staticmethod
    def _sched_row(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "name": r["name"], "script_id": r["script_id"],
                "profile_ids": json.loads(r["profile_ids"] or "[]"), "kind": r["kind"],
                "interval_min": r["interval_min"], "at_time": r["at_time"],
                "enabled": bool(r["enabled"]), "last_run": r["last_run"], "next_run": r["next_run"]}

    def update_schedule(self, sid: str, d: dict) -> None:
        cols = {"name": "name", "script_id": "script_id", "kind": "kind",
                "interval_min": "interval_min", "at_time": "at_time", "next_run": "next_run"}
        sets, vals = [], []
        for k, col in cols.items():
            if k in d:
                sets.append(f"{col}=?"); vals.append(d[k])
        if "profile_ids" in d:
            sets.append("profile_ids=?"); vals.append(json.dumps(d["profile_ids"], ensure_ascii=False))
        if "enabled" in d:
            sets.append("enabled=?"); vals.append(1 if d["enabled"] else 0)
        if not sets:
            return
        sets.append("updated_at=?"); vals.append(_now()); vals.append(sid)
        self.conn.execute(f"UPDATE schedules SET {','.join(sets)} WHERE id=?", vals)
        self.conn.commit()

    def mark_schedule_run(self, sid: str, last_run: str, next_run: str) -> None:
        self.conn.execute("UPDATE schedules SET last_run=?, next_run=? WHERE id=?",
                          (last_run, next_run, sid))
        self.conn.commit()

    def delete_schedule(self, sid: str) -> None:
        self.conn.execute("DELETE FROM schedules WHERE id=?", (sid,))
        self.conn.commit()

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close(); self._local.conn = None


if __name__ == "__main__":
    # Self-check: WAL bật + pool connection đa thread ghi/đọc song song không lỗi, không mất dữ liệu.
    import tempfile
    from core.fingerprint import generate   # noqa: E402

    dbp = str(Path(tempfile.mkdtemp()) / "scale.db")
    db = Database(dbp)
    assert db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal", "WAL phải bật"

    N_THREADS, PER = 8, 25
    errors: list[str] = []

    def worker(tid: int):
        try:
            for i in range(PER):
                p = db.create_profile(f"t{tid}-{i}", generate())   # ghi (mỗi thread conn riêng)
                assert db.get_profile(p.id) is not None             # đọc lại
                db.set_dynamic_data(p.id, {"n": i})                 # update
        except Exception as e:  # noqa: BLE001
            errors.append(f"thread {tid}: {e!r}")

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert not errors, f"pool lỗi khi chạy song song: {errors}"
    total = len(db.list_profiles())
    assert total == N_THREADS * PER, f"mất dữ liệu: {total} != {N_THREADS * PER}"
    print(f"OK - WAL on, {N_THREADS} threads x {PER} create/read/update concurrent, "
          f"total={total}, no error, no data loss - PASS")
