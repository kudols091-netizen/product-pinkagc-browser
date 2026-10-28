"""Self-check Phase Team — auth/role/share/visibility + client sync roundtrip.
Chạy: python test_phase_team.py  (không cần mạng — transport qua Flask test_client)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.db import Database
from core.fingerprint import generate
from core.team_client import TeamClient, sync_down
from core.team_server import TeamStore, create_team_app


def test_auth_roles_share():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        db = Database(Path(d) / "team.db")
        st = TeamStore(db)
        admin = st.register("alice", "pw1")          # user đầu -> admin
        member = st.register("bob", "pw2")           # kế -> member
        assert admin["role"] == "admin" and member["role"] == "member"
        try:
            st.register("alice", "x"); assert False
        except ValueError: pass

        a = st.login("alice", "pw1"); b = st.login("bob", "pw2")
        assert a and b and st.login("bob", "sai") is None
        assert st.user_for_token(a["token"])["role"] == "admin"

        au, bu = st.user_for_token(a["token"]), st.user_for_token(b["token"])
        pA = st.push(au, [{"name": "A", "fingerprint_data": generate()}])[0]  # alice sở hữu A
        pB = st.push(bu, [{"name": "B", "fingerprint_data": generate()}])[0]  # bob sở hữu B

        # visibility: admin thấy hết; member chỉ thấy của mình
        assert {x["id"] for x in st.list_visible(au)} == {pA, pB}
        assert {x["id"] for x in st.list_visible(bu)} == {pB}

        # bob KHÔNG được đè A của alice
        assert st.push(bu, [{"id": pA, "name": "hack", "fingerprint_data": {}}]) == []
        assert st.db.get_profile(pA).name == "A"

        # alice share A cho bob quyền run
        st.share(au, pA, "bob", "run")
        assert {x["id"] for x in st.list_visible(bu)} == {pA, pB}
        assert st.can_access(bu, pA, "run") and not st.can_access(bu, pA, "write")
        assert st.can_access(bu, pB, "write")       # chủ sở hữu

        # member không được share profile không phải của mình
        try:
            st.share(bu, pB, "alice", "write")      # ok (bob sở hữu B)
        except Exception: assert False
        try:
            member2 = st.register("carol", "pw3")
            c = st.login("carol", "pw3"); cu = st.user_for_token(c["token"])
            st.share(cu, pA, "bob", "read"); assert False   # carol không có quyền A
        except PermissionError: pass
        db.close()
    print("[ok] team auth + role + share + visibility")


def test_client_sync():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        app = create_team_app(Path(d) / "srv.db")
        tc = app.test_client()

        def transport(method, path, body, token):
            h = {"Authorization": f"Bearer {token}"} if token else {}
            return getattr(tc, method.lower())(path, json=body, headers=h).get_json()

        client = TeamClient(_transport=transport)
        client.register("alice", "pw")
        assert client.login("alice", "pw")["success"]
        # push 2 profile local lên server
        up = client.push([{"name": "P1", "fingerprint_data": generate()},
                          {"name": "P2", "fingerprint_data": generate()}])
        assert up["pushed"] == 2
        assert len(client.pull()) == 2

        # sync_down về DB local mới
        local = Database(Path(d) / "local.db")
        n = sync_down(local, client)
        assert n == 2 and len(local.list_profiles()) == 2
        assert {p.name for p in local.list_profiles()} == {"P1", "P2"}
        local.close()
    print("[ok] team client sync (register/login/push/pull/sync_down)")


if __name__ == "__main__":
    test_auth_roles_share()
    test_client_sync()
    print("\nALL PHASE-TEAM CHECKS PASSED")
