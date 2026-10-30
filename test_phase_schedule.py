"""Self-check Phase Schedule — scripts/runs/schedules API + db. Chạy: python test_phase_schedule.py (thuần)."""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import scheduler as S
from core.api import create_app


def test_scripts_schedules_api():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        c = create_app(Path(d) / "db.sqlite", Path(d) / "profiles").test_client()
        pid = c.post("/api/v3/profiles/create", json={"name": "a"}).get_json()["data"]["id"]
        # scripts CRUD
        sid = c.post("/api/v3/scripts", json={"name": "s1", "steps": [{"action": "goto", "url": "x"}]}
                     ).get_json()["data"]["id"]
        lst = c.get("/api/v3/scripts").get_json()["data"]
        assert len(lst) == 1 and lst[0]["name"] == "s1" and len(lst[0]["steps"]) == 1
        c.put(f"/api/v3/scripts/{sid}", json={"name": "s1b"})
        assert c.get("/api/v3/scripts").get_json()["data"][0]["name"] == "s1b"
        # schedules: tạo -> next_run ở TƯƠNG LAI (không chạy ngay)
        schid = c.post("/api/v3/schedules", json={"name": "L1", "script_id": sid,
                       "profile_ids": [pid], "kind": "interval", "interval_min": 30}
                       ).get_json()["data"]["id"]
        sch = c.get("/api/v3/schedules").get_json()["data"]
        assert len(sch) == 1 and sch[0]["enabled"] and sch[0]["next_run"]
        assert datetime.fromisoformat(sch[0]["next_run"]) > datetime.now()
        # toggle off
        c.put(f"/api/v3/schedules/{schid}", json={"enabled": False})
        assert c.get("/api/v3/schedules").get_json()["data"][0]["enabled"] is False
        # runs rỗng ban đầu
        assert c.get("/api/v3/runs").get_json()["data"] == []
        # delete
        c.delete(f"/api/v3/scripts/{sid}"); c.delete(f"/api/v3/schedules/{schid}")
        assert c.get("/api/v3/scripts").get_json()["data"] == []
        assert c.get("/api/v3/schedules").get_json()["data"] == []
    print("[ok] scripts/runs/schedules API (CRUD + next_run tương lai + toggle)")


def test_scheduler_check():
    # dùng run_fn giả: schedule đến hạn -> kích hoạt đúng số profile; disabled -> bỏ
    calls = []

    class _DB:
        def __init__(s):
            s.sched = [{"id": "s1", "enabled": True, "next_run": None, "kind": "interval",
                        "interval_min": 10, "script_id": "sc", "profile_ids": ["p1", "p2"], "name": "L"}]
        def list_schedules(s): return s.sched
        def get_script(s, i): return {"steps": [{"action": "goto", "url": "x"}]}
        def mark_schedule_run(s, sid, last, nxt):
            for x in s.sched:
                if x["id"] == sid: x["next_run"] = nxt
    db = _DB()
    sch = S.Scheduler(db, lambda pid, steps, name, src: calls.append(pid))
    assert sch.check(datetime(2026, 1, 1, 10, 0)) == 2 and set(calls) == {"p1", "p2"}
    assert sch.check(datetime(2026, 1, 1, 10, 0)) == 0        # chưa tới next_run
    print("[ok] scheduler.check (đến hạn / next_run chặn chạy lại)")


if __name__ == "__main__":
    test_scripts_schedules_api()
    test_scheduler_check()
    print("\nALL PHASE-SCHEDULE CHECKS PASSED")
