"""Scheduler nền — chạy kịch bản đã lưu theo lịch.

kind='interval': mỗi N phút. kind='daily': mỗi ngày lúc HH:MM.
Luồng daemon kiểm mỗi `tick` giây; schedule đến hạn -> chạy script trên các profile của nó,
ghi next_run TRƯỚC khi chạy (tránh chạy trùng nếu run lâu). run_fn do api.py cấp
(start profile nếu cần -> run_script -> log run -> stop).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable


def _parse(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def compute_next(sched: dict, now: datetime | None = None) -> datetime:
    """Mốc chạy kế tiếp. daily -> HH:MM hôm nay/mai; interval -> now + N phút."""
    now = now or datetime.now()
    if sched.get("kind") == "daily" and sched.get("at_time"):
        try:
            hh, mm = (int(x) for x in str(sched["at_time"]).split(":"))
            nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return nxt + timedelta(days=1) if nxt <= now else nxt
        except (ValueError, TypeError):
            pass
    return now + timedelta(minutes=max(1, int(sched.get("interval_min", 60) or 60)))


class Scheduler:
    def __init__(self, db: Any, run_fn: Callable[[str, list, str, str], Any], tick: float = 20.0):
        self.db, self.run_fn, self.tick = db, run_fn, tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.tick):
            try:
                self.check()
            except Exception:  # noqa: BLE001  (lịch lỗi không được làm chết luồng)
                pass

    def check(self, now: datetime | None = None) -> int:
        """Chạy mọi schedule đến hạn. Trả số lần (profile×schedule) đã kích hoạt."""
        now = now or datetime.now()
        fired = 0
        for s in self.db.list_schedules():
            if not s["enabled"]:
                continue
            nr = _parse(s.get("next_run"))
            if nr is not None and nr > now:
                continue
            nxt = compute_next(s, now)
            self.db.mark_schedule_run(s["id"], now.isoformat(), nxt.isoformat())
            script = self.db.get_script(s["script_id"]) if s.get("script_id") else None
            steps = (script or {}).get("steps") or []
            if not steps:
                continue
            for pid in s["profile_ids"]:
                try:
                    self.run_fn(pid, steps, s["name"], "schedule")
                    fired += 1
                except Exception:  # noqa: BLE001
                    pass
        return fired


if __name__ == "__main__":
    # Self-check: compute_next + check() kích hoạt đúng schedule đến hạn (db giả, run_fn giả).
    base = datetime(2026, 1, 1, 10, 0, 0)
    assert compute_next({"kind": "interval", "interval_min": 30}, base) == base + timedelta(minutes=30)
    d = compute_next({"kind": "daily", "at_time": "09:00"}, base)   # 9h đã qua -> mai
    assert d == datetime(2026, 1, 2, 9, 0, 0), d
    d2 = compute_next({"kind": "daily", "at_time": "15:30"}, base)  # 15h30 chưa tới -> hôm nay
    assert d2 == datetime(2026, 1, 1, 15, 30, 0), d2

    class _FakeDB:
        def __init__(self):
            self.sched = [{"id": "s1", "enabled": True, "next_run": None, "kind": "interval",
                           "interval_min": 10, "script_id": "sc1", "profile_ids": ["p1", "p2"],
                           "name": "L1"},
                          {"id": "s2", "enabled": False, "next_run": None, "kind": "interval",
                           "interval_min": 10, "script_id": "sc1", "profile_ids": ["p9"], "name": "off"}]
            self.marked = []
        def list_schedules(self): return self.sched
        def get_script(self, sid): return {"steps": [{"action": "goto", "url": "x"}]}
        def mark_schedule_run(self, sid, last, nxt):
            self.marked.append(sid)
            for s in self.sched:
                if s["id"] == sid:
                    s["next_run"] = nxt

    calls = []
    db = _FakeDB()
    sch = Scheduler(db, lambda pid, steps, name, src: calls.append((pid, name, src)))
    n = sch.check(base)
    assert n == 2 and {c[0] for c in calls} == {"p1", "p2"}, (n, calls)   # chỉ s1 (enabled) × 2 profile
    assert db.marked == ["s1"] and "s2" not in db.marked
    n2 = sch.check(base)                                                  # ngay sau: chưa tới next_run -> 0
    assert n2 == 0, n2
    print("OK - compute_next + scheduler.check (due/disabled/next_run) - PASS")
