"""Self-check Phase C — automation validator + MCP server dispatch + API automation route.
Chạy: python test_phase_c.py  (không cần browser/mạng — chỉ phần thuần)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import automation
from core.mcp_server import Server, TOOLS


def test_validate_script():
    good = [{"action": "goto", "url": "https://x.com"},
            {"action": "type", "selector": "#u", "text": "a"},
            {"action": "image_click", "template": "btn.png", "threshold": 0.9},
            {"action": "extract", "selector": ".bal", "as": "bal"}]
    assert automation.validate_script(good) == []
    bad = [{"action": "goto"},                       # thiếu url
           {"action": "nope"},                       # action lạ
           {"selector": "#x"}]                        # thiếu action
    errs = automation.validate_script(bad)
    assert len(errs) == 3 and any("url" in e for e in errs) and any("nope" in e for e in errs)
    assert "list" in automation.validate_script({"action": "goto"})[0]
    print("[ok] automation validate_script")


def test_mcp_dispatch():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        srv = Server(str(Path(d) / "m.db"), str(Path(d) / "p"))
        # initialize
        init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init["result"]["serverInfo"]["name"] == "pinkagc-browser"
        assert init["result"]["protocolVersion"]
        # notification -> không trả
        assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
        # tools/list khớp TOOLS
        tl = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in tl["result"]["tools"]}
        assert {"list_profiles", "create_profile", "start_profile", "run_script",
                "check_proxy", "clone_profile"} <= names
        assert len(TOOLS) == len(names)
        # tools/call create_profile -> rồi list_profiles thấy nó
        import json as _j
        c = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "create_profile", "arguments": {"name": "mcp1"}}})
        pid = _j.loads(c["result"]["content"][0]["text"])["id"]
        lp = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                         "params": {"name": "list_profiles", "arguments": {}}})
        assert any(p["id"] == pid and p["name"] == "mcp1"
                   for p in _j.loads(lp["result"]["content"][0]["text"]))
        # tool lạ -> isError
        err = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                          "params": {"name": "khong_co", "arguments": {}}})
        assert err["result"]["isError"]
        # check_proxy qua MCP (proxy chết -> alive False, không cần mạng cho proxy sai định dạng)
        cp = srv.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                         "params": {"name": "check_proxy", "arguments": {"raw_proxy": "bad"}}})
        assert _j.loads(cp["result"]["content"][0]["text"])["alive"] is False
        # method lạ -> error -32601
        assert srv.handle({"jsonrpc": "2.0", "id": 7, "method": "wat"})["error"]["code"] == -32601
        srv.db.close()
    print("[ok] MCP server dispatch (initialize/tools/call/error)")


def test_api_automation():
    from core.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        c = create_app(Path(d) / "db.sqlite", Path(d) / "profiles").test_client()
        pid = c.post("/api/v3/profiles/create", json={"name": "a"}).get_json()["data"]["id"]
        # validate route
        v = c.post("/api/v3/automation/validate",
                   json={"steps": [{"action": "goto", "url": "https://x"}]}).get_json()["data"]
        assert v["valid"] and v["errors"] == []
        bad = c.post("/api/v3/automation/validate", json={"steps": [{"action": "x"}]}).get_json()["data"]
        assert not bad["valid"]
        # run với script lỗi -> 400 (không launch browser)
        r = c.post(f"/api/v3/profiles/{pid}/run", json={"steps": [{"action": "nope"}]})
        assert r.status_code == 400
    print("[ok] API automation (validate + run guard)")


if __name__ == "__main__":
    test_validate_script()
    test_mcp_dispatch()
    test_api_automation()
    print("\nALL PHASE-C CHECKS PASSED")
