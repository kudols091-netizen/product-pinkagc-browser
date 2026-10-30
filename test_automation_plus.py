"""Self-check engine automation mở rộng (biến, control-flow, 2FA, validate lồng).
Chạy: python test_automation_plus.py  (thuần, không cần browser)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import automation as A


def test_pure_helpers():
    assert A._subst("{{a}}-{{b}}-{{miss}}", {"a": 1, "b": "x"}) == "1-x-"
    # TOTP RFC-6238 (SHA1) test vector: seed "12345678901234567890", t=59 -> 94287082
    assert A._totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", t=59, digits=8) == "94287082"
    assert A._compare("6", "==", "6") and A._compare("7", ">", "6") and A._compare("ab", "contains", "abc") is False
    assert A._compare("abc", "contains", "b") and A._compare("", "empty", "") and A._compare("x", "notempty", "")
    assert "@" in A._random_data("email") and len(A._random_data("password", "20")) == 20
    assert A._json_path({"a": {"b": [10, {"c": 9}]}}, "a.b.1.c") == 9
    import ast
    import operator as op
    assert A._safe_math("2*3+1", ast, op) == 7.0
    try:
        A._safe_math("__import__('os')", ast, op); assert False
    except Exception:
        pass
    print("[ok] pure helpers (subst/totp/compare/random/jsonpath/math)")


def test_validate_nested():
    # backward-compat với test_phase_c
    assert A.validate_script([{"action": "goto", "url": "https://x"}]) == []
    errs = A.validate_script([{"action": "goto"}, {"action": "nope"}, {"selector": "#x"}])
    assert len(errs) == 3 and any("url" in e for e in errs) and any("nope" in e for e in errs)
    assert "list" in A.validate_script({"action": "goto"})[0]
    # lồng nhau: lỗi trong body của loop phải bắt được
    nested = [{"action": "loop", "times": 2, "body": [{"action": "click"}]}]  # click thiếu selector
    e2 = A.validate_script(nested)
    assert any("selector" in e and "body" in e for e in e2), e2
    # action mới hợp lệ
    assert A.validate_script([{"action": "gen_2fa", "secret": "X"},
                              {"action": "http_request", "url": "http://x"},
                              {"action": "foreach", "var": "a", "body": [{"action": "log", "message": "hi"}]}]) == []
    print("[ok] validate_script (lồng body/then/else + action mới)")


class _FakePage:
    """Page giả tối thiểu cho các action KHÔNG đụng trình duyệt (set_var/inc/if/loop/foreach/log)."""
    def set_default_timeout(self, *_a): pass


def test_control_flow():
    with tempfile.TemporaryDirectory() as d:
        ctx = A._Ctx(browser=None, page=_FakePage(), workdir=Path(d), timeout=1000)
        script = [
            {"action": "set_var", "var": "total", "value": "0"},
            {"action": "loop", "times": "3", "var": "i",
             "body": [{"action": "inc_var", "var": "total", "by": "2"}]},
            {"action": "foreach", "list": "a\nb\nc", "var": "x",
             "body": [{"action": "log", "message": "item {{x}}"}]},
            {"action": "if", "left": "{{total}}", "op": "==", "right": "6",
             "then": [{"action": "set_var", "var": "ok", "value": "yes"}],
             "else": [{"action": "set_var", "var": "ok", "value": "no"}]},
            {"action": "math", "expr": "{{total}}*10", "as": "big"},
            {"action": "stop"},
            {"action": "set_var", "var": "after", "value": "NOPE"},
        ]
        try:
            A._run_steps(script, ctx)
        except A._Stop:
            pass
        assert ctx.vars["total"] == 6.0, ctx.vars
        assert ctx.vars["ok"] == "yes"
        assert ctx.data["big"] == 60.0
        assert "after" not in ctx.vars, "stop phải chặn step sau"
        assert "item a" in ctx.log and sum(1 for x in ctx.log if x.startswith("item ")) == 3
    print("[ok] control-flow (loop/foreach/if/stop + biến)")


if __name__ == "__main__":
    test_pure_helpers()
    test_validate_nested()
    test_control_flow()
    print("\nALL AUTOMATION-PLUS CHECKS PASSED")
