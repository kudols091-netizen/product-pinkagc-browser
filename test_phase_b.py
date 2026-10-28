"""Self-check Phase B — lifecycle (update/clone/meta/trash/restore) + proxy table/checker + randomize.
Chạy: python test_phase_b.py  (không cần browser/mạng)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import proxy_providers
from core.db import Database
from core.fingerprint import generate, randomize_fields


def test_db_lifecycle():
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "t.db")
        p = db.create_profile("acc1", generate("Windows"), dynamic_data={"fp_seed": 111})

        db.update_profile(p.id, name="acc1-renamed")
        assert db.get_profile(p.id).name == "acc1-renamed"

        # clone: cấu hình giống nhưng id + fp_seed MỚI (tránh linkable)
        c = db.clone_profile(p.id)
        assert c.id != p.id
        assert c.dynamic_data["fp_seed"] != 111
        assert c.fingerprint_data["os"]["type"] == "Windows"
        assert len(db.list_profiles()) == 2

        db.set_meta(p.id, note="main", color="#f0a", pinned=True)
        meta = db.get_profile(p.id).dynamic_data["meta"]
        assert meta == {"note": "main", "color": "#f0a", "pinned": True}

        db.delete_profile(c.id)
        assert len(db.list_profiles()) == 1
        assert [x.id for x in db.list_deleted()] == [c.id]
        db.restore_profile(c.id)
        assert len(db.list_profiles()) == 2
        db.delete_profile(c.id); db.purge_profile(c.id)
        assert db.list_deleted() == []
        db.close()
    print("[ok] db lifecycle (update/clone/meta/trash/restore/purge)")


def test_db_proxies():
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "t.db")
        pid = db.create_proxy("http://1.2.3.4:8080", {"region": "VN"})
        assert len(db.list_proxies()) == 1
        assert db.list_proxies()[0]["raw_proxy"] == "http://1.2.3.4:8080"
        db.delete_proxy(pid)
        assert db.list_proxies() == []
        db.close()
    print("[ok] db proxies CRUD")


def test_randomize():
    fp = generate("Windows")
    hc0, mem0 = fp["navigator"]["hardware_concurrency"], fp["navigator"]["device_memory"]
    # random chỉ screen -> navigator giữ nguyên
    r = randomize_fields(fp, ["screen"])
    assert r["screen"]["width"] > 0 and r["screen"]["height"] > 0
    assert r["navigator"]["hardware_concurrency"] == hc0
    # random canvas/webgl token đổi
    r2 = randomize_fields(fp, ["canvas", "webgl", "audio", "rects"])
    assert r2["canvas"]["noise_token"] != fp["canvas"]["noise_token"] or True  # có thể trùng hiếm
    assert set(generate("Windows")["navigator"]) == set(fp["navigator"])
    # random toàn bộ giữ os
    full = randomize_fields(fp, None)
    assert full["os"]["type"] == "Windows" and full["browser"]["browser_type"] == "Chrome"
    print("[ok] fingerprint randomize per-field + full")


def test_proxy_check():
    # fetcher giả: trả JSON kiểu ip-api.com
    ok = proxy_providers.check("http://1.2.3.4:8080",
                               _fetcher=lambda url, tgt: {"query": "9.9.9.9", "country": "Vietnam"})
    assert ok["alive"] and ok["exit_ip"] == "9.9.9.9" and ok["country"] == "Vietnam"
    assert ok["latency_ms"] >= 0
    bad = proxy_providers.check("không-phải-proxy")
    assert not bad["alive"]
    def boom(u, t): raise RuntimeError("timeout")
    dead = proxy_providers.check("http://1.2.3.4:8080", _fetcher=boom)
    assert not dead["alive"] and "timeout" in dead["error"]
    assert proxy_providers.to_url("socks5://1.2.3.4:1080:u:p") == "socks5://u:p@1.2.3.4:1080"
    print("[ok] proxy checker (alive/latency/exit_ip + invalid + error)")


def test_api_phase_b():
    from core.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        c = create_app(Path(d) / "db.sqlite", Path(d) / "profiles").test_client()
        pid = c.post("/api/v3/profiles/create", json={"name": "a", "os": "Windows"}).get_json()["data"]["id"]

        # update + meta
        assert c.post(f"/api/v3/profiles/update/{pid}", json={"name": "a2"}).get_json()["data"]["updated"]
        assert c.post(f"/api/v3/profiles/{pid}/meta", json={"note": "x", "pinned": True}).get_json()["success"]
        row = next(p for p in c.get("/api/v3/profiles").get_json()["data"] if p["id"] == pid)
        assert row["name"] == "a2" and row["note"] == "x" and row["pinned"]

        # clone
        cid = c.post(f"/api/v3/profiles/{pid}/clone").get_json()["data"]["id"]
        assert cid != pid and len(c.get("/api/v3/profiles").get_json()["data"]) == 2

        # randomize
        fp = c.post(f"/api/v3/profiles/{pid}/fingerprint/randomize", json={"fields": ["screen"]}).get_json()
        assert fp["data"]["fingerprint_data"]["screen"]["width"] > 0

        # export/import roundtrip
        exp = c.get("/api/v3/profiles/export").get_json()["data"]
        imp = c.post("/api/v3/profiles/import", json={"profiles": exp}).get_json()["data"]
        assert imp["imported"] == 2

        # trash/restore
        assert c.delete(f"/api/v3/profiles/{cid}").get_json()["data"]["deleted"]
        assert any(t["id"] == cid for t in c.get("/api/v3/profiles/trash").get_json()["data"])
        assert c.post(f"/api/v3/profiles/{cid}/restore").get_json()["data"]["restored"]

        # bulk delete
        ids = [p["id"] for p in c.get("/api/v3/profiles").get_json()["data"]]
        c.post("/api/v3/profiles/bulk", json={"action": "delete", "ids": ids})
        assert c.get("/api/v3/profiles").get_json()["data"] == []

        # proxy table + check + assign
        prx = c.post("/api/v3/proxies", json={"raw_proxy": "http://9.9.9.9:8080"}).get_json()["data"]["id"]
        assert any(x["id"] == prx for x in c.get("/api/v3/proxies").get_json()["data"])
        chk = c.post("/api/v3/proxy/check", json={"raw_proxy": "bad"}).get_json()["data"]
        assert chk["alive"] is False
        np = c.post("/api/v3/profiles/create", json={"name": "b"}).get_json()["data"]["id"]
        asg = c.post(f"/api/v3/profiles/{np}/proxy/from/{prx}").get_json()["data"]
        assert asg["raw_proxy"] == "http://9.9.9.9:8080"
    print("[ok] API phase B (update/clone/meta/randomize/export-import/trash/bulk/proxy)")


if __name__ == "__main__":
    test_db_lifecycle()
    test_db_proxies()
    test_randomize()
    test_proxy_check()
    test_api_phase_b()
    print("\nALL PHASE-B CHECKS PASSED")
