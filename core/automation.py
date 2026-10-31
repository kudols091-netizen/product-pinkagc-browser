"""Automation runner — chạy kịch bản no-code trên profile qua CDP (+ OpenCV image-match).

Kịch bản = list step dict (JSON). Mỗi step có "action" + tham số. Hỗ trợ:
  - Biến {{var}}: mọi tham số chuỗi được thay {{name}} bằng giá trị biến (set_var/extract/http…).
  - Control-flow lồng nhau: loop{times,body}, foreach{var,file|list,body}, while_exists{selector,body},
    if{selector|left/op/right, then, else}, stop, throw.
  - Retry per-step: "retry": N (thử lại khi lỗi). Timeout per-step: "timeout": ms.
Ví dụ:
  [{"action":"goto","url":"https://x.com"},
   {"action":"foreach","file":"accs.txt","var":"acc","body":[
       {"action":"type","selector":"#u","text":"{{acc}}"},
       {"action":"gen_2fa","secret":"JBSWY...","as":"otp"},
       {"action":"type","selector":"#otp","text":"{{otp}}"}]}]

validate_script() thuần (test được không cần browser). run_script() nối Playwright qua CDP và thực thi.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

# action -> tuple các key BẮT BUỘC. Control-flow có body/then/else được validate đệ quy.
_ACTIONS: dict[str, tuple[str, ...]] = {
    # --- Browser ---
    "goto": ("url",), "click": ("selector",), "type": ("selector", "text"),
    "fill": ("selector", "text"), "human_type": ("selector", "text"), "clear": ("selector",),
    "hover": ("selector",), "dblclick": ("selector",), "rightclick": ("selector",),
    "select": ("selector",), "check": ("selector",), "press": ("key",),
    "uploadfile": ("selector", "path"), "scroll": (), "scrollto": ("selector",),
    "wait": ("ms",), "waitfor": ("selector",), "waittext": ("text",), "waiturl": ("contains",),
    "screenshot": (), "eval": ("js",), "extract": ("selector",), "getattr": ("selector", "attr"),
    "geturl": (), "gettitle": (), "exists": ("selector",), "count": ("selector",),
    "newtab": ("url",), "switchtab": ("index",), "closetab": (), "reload": (), "goback": (),
    "getcookies": (), "setcookie": ("name", "value"), "image_click": ("template",),
    # --- Data / biến ---
    "set_var": ("var", "value"), "inc_var": ("var",), "math": ("expr",),
    "http_request": ("url",), "parse_json": ("input", "path"), "regex": ("input", "pattern"),
    "random_data": ("kind",), "random_number": (), "random_line": ("path",),
    "read_file": ("path",), "write_file": ("path", "content"), "split_text": ("input", "sep"),
    # --- Logic (control-flow) ---
    "if": (), "loop": ("times",), "foreach": ("var",), "while_exists": ("selector",),
    "stop": (), "throw": (), "log": ("message",), "comment": (),
    # --- Account ---
    "gen_2fa": ("secret",), "telegram": ("token", "chatid", "message"),
    "solve_captcha": ("apikey",),
}
_BODY_KEYS = ("body", "then", "else")          # key chứa list step con -> validate đệ quy


def validate_script(steps: Any, _path: str = "") -> list[str]:
    """Trả list lỗi (rỗng = hợp lệ). Đệ quy vào body/then/else của control-flow."""
    errs: list[str] = []
    if not isinstance(steps, list):
        return [f"script{(' ' + _path) if _path else ''} phải là list step"]
    for i, s in enumerate(steps):
        at = f"{_path}step {i}"
        if not isinstance(s, dict) or "action" not in s:
            errs.append(f"{at}: thiếu 'action'"); continue
        act = s["action"]
        if act not in _ACTIONS:
            errs.append(f"{at}: action không hỗ trợ {act!r} ({list(_ACTIONS)})"); continue
        for k in _ACTIONS[act]:
            if k not in s:
                errs.append(f"{at} ({act}): thiếu '{k}'")
        for bk in _BODY_KEYS:
            if bk in s:
                errs += validate_script(s[bk], f"{at}>{bk} ")
    return errs


# ---------------------------------------------------------------- biến + helper thuần

_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _subst(text: Any, vars: dict) -> str:
    """Thay {{name}} bằng str(vars[name]) (rỗng nếu thiếu). Không phải chuỗi -> str()."""
    s = text if isinstance(text, str) else str(text)
    return _VAR_RE.sub(lambda m: str(vars.get(m.group(1), "")), s)


def _totp(secret: str, t: float | None = None, digits: int = 6, period: int = 30) -> str:
    """TOTP RFC-6238 (SHA1) — sinh mã 2FA từ secret Base32. Thuần stdlib, không cần lib."""
    import base64
    import hashlib
    import hmac
    import struct
    import time
    key_s = re.sub(r"\s", "", secret).upper()
    key_s += "=" * (-len(key_s) % 8)
    key = base64.b32decode(key_s, casefold=True)
    counter = int((time.time() if t is None else t) // period)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _random_data(kind: str, arg: str = "") -> str:
    """Sinh dữ liệu ngẫu nhiên: name/firstname/lastname/email/username/password/number/string/uuid/phone."""
    import random
    import string
    import uuid
    fn = ["an", "binh", "chi", "dung", "giang", "ha", "hoa", "khanh", "linh", "minh", "nam", "oanh", "phuc", "quan", "trang"]
    ln = ["nguyen", "tran", "le", "pham", "hoang", "vu", "dang", "bui", "do", "ho"]
    def _len(default: int) -> int:
        if "-" in arg:
            a, b = arg.split("-", 1)
            return random.randint(int(a), int(b))
        return int(arg) if arg.isdigit() else default
    k = kind.lower()
    if k == "firstname": return random.choice(fn)
    if k == "lastname": return random.choice(ln)
    if k == "name": return f"{random.choice(ln)} {random.choice(fn)}"
    if k == "username": return random.choice(fn) + str(random.randint(100, 99999))
    if k == "email":
        dom = arg or random.choice(["gmail.com", "hotmail.com", "outlook.com"])
        return random.choice(fn) + str(random.randint(100, 99999)) + "@" + dom
    if k == "password":
        pool = string.ascii_letters + string.digits + "!@#$%"
        return "".join(random.choice(pool) for _ in range(_len(12)))
    if k == "string":
        return "".join(random.choice(string.ascii_lowercase) for _ in range(_len(10)))
    if k == "number":
        return str(random.randint(0, 10 ** _len(6) - 1))
    if k == "uuid": return uuid.uuid4().hex
    if k == "phone": return "09" + "".join(random.choice("0123456789") for _ in range(8))
    return ""


def _json_path(obj: Any, path: str) -> Any:
    """Lấy giá trị theo path 'a.b.0.c' từ dict/list."""
    cur = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _compare(left: str, op: str, right: str) -> bool:
    """So sánh biến cho action if: == != > >= < <= contains empty notempty."""
    if op == "empty": return left.strip() == ""
    if op == "notempty": return left.strip() != ""
    if op == "contains": return right in left
    try:                                             # so sánh số nếu cả hai là số ("6.0" == "6")
        a: Any = float(left); b: Any = float(right)
    except ValueError:
        a, b = left, right
    if op in ("==", "!="):
        eq = a == b
        return eq if op == "==" else not eq
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}.get(op, False)


# ---------------------------------------------------------------- browser helpers

def _image_click(page: Any, template_path: str, threshold: float, workdir: Path) -> bool:
    """OpenCV template-match template trên screenshot trang -> click tâm match nếu >= threshold."""
    import cv2
    import numpy as np
    tpl_path = template_path if Path(template_path).is_absolute() else str(workdir / template_path)
    tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
    if tpl is None:
        raise RuntimeError(f"không đọc được template: {tpl_path}")
    shot = np.frombuffer(page.screenshot(), np.uint8)
    img = cv2.imdecode(shot, cv2.IMREAD_COLOR)
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    if maxv < threshold:
        return False
    h, w = tpl.shape[:2]
    dpr = page.evaluate("window.devicePixelRatio") or 1
    page.mouse.click((maxloc[0] + w / 2) / dpr, (maxloc[1] + h / 2) / dpr)
    return True


def _elem_exists(page: Any, selector: str, timeout_ms: int) -> bool:
    """Phần tử có xuất hiện trong timeout không (0 = kiểm tra ngay)."""
    try:
        if timeout_ms > 0:
            page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        return page.query_selector(selector) is not None
    except Exception:  # noqa: BLE001
        return False


def _connect(pw: Any, engine: str, ws_endpoint: str) -> Any:
    """camoufox phát ws endpoint Playwright-Firefox (connect); còn lại là CDP Chromium."""
    if engine == "camoufox":
        if str(ws_endpoint).startswith("camoufox-local://"):
            raise RuntimeError(
                "Automation chưa chạy được trên camoufox (mở ở chế độ persistent in-process, không có ws "
                "điều khiển từ xa) — dùng engine Chromium (ovobrowser/fpchromium) cho automation.")
        return pw.firefox.connect(ws_endpoint)
    return pw.chromium.connect_over_cdp(ws_endpoint)


def inject_cookies(ws_endpoint: str, cookies: list[dict], *, engine: str = "chromium") -> int:
    """Nạp cookie vào trình duyệt vừa mở (persistent context -> Chromium tự lưu lại). Trả số cookie."""
    if not cookies:
        return 0
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = _connect(pw, engine, ws_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        try:
            ctx.add_cookies(cookies)
        finally:
            browser.close()          # connect_over_cdp: chỉ ngắt CDP, trình duyệt vẫn mở cho user
    return len(cookies)


_IPHEY_JS = r"""() => {
  const kw = /^(trustworthy|suspicious|untrustworthy)$/i;
  let verdict='', note='';
  document.querySelectorAll('h1,h2,h3,div,span,p,strong,b').forEach(e=>{
    if(e.childElementCount) return;
    const t=(e.innerText||'').trim();
    if(!verdict && kw.test(t)) verdict=t;
    if(!note && /signals?\s+detected|no\s+suspicious/i.test(t) && t.length<90) note=t;
  });
  return {verdict, note};
}"""


def fingerprint_check(ws_endpoint: str, *, engine: str = "chromium", timeout: int = 45000) -> dict:
    """Test độ 'kín' của fingerprint profile: chấm verdict iphey.com (tin cậy) + mở creepjs/pixelscan
    thành tab cho user soi tay (scrape 2 site kia không ổn định). Trình duyệt phải đang mở (CDP Chromium).
    Trả {iphey, note, opened[]}."""
    from playwright.sync_api import sync_playwright
    res = {"iphey": "", "note": "", "opened": []}
    with sync_playwright() as pw:
        browser = _connect(pw, engine, ws_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        try:
            pg = ctx.new_page()
            try:
                pg.goto("https://iphey.com/", wait_until="domcontentloaded", timeout=timeout)
                pg.wait_for_timeout(9000)               # iphey tính vài giây
                d = pg.evaluate(_IPHEY_JS)
                res["iphey"] = d.get("verdict") or "(không đọc được)"
                res["note"] = d.get("note") or ""
            except Exception as e:  # noqa: BLE001
                res["iphey"] = "lỗi"; res["note"] = str(e)[:120]
            for url in ("https://abrahamjuliot.github.io/creepjs/", "https://pixelscan.net/"):
                try:
                    ctx.new_page().goto(url, wait_until="commit", timeout=15000)
                    res["opened"].append(url)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            browser.close()          # ngắt CDP, trình duyệt + tab vẫn mở cho user xem
    return res


# ---------------------------------------------------------------- engine thực thi

class _Ctx:
    """Trạng thái chạy: biến, log, data, workdir, trình duyệt + chặn vòng lặp vô hạn."""
    def __init__(self, browser: Any, page: Any, workdir: Path, timeout: int, max_seconds: int = 600):
        self.browser, self.page, self.workdir, self.timeout = browser, page, workdir, timeout
        self.vars: dict[str, Any] = {}
        self.log: list[str] = []
        self.data: dict[str, Any] = {}
        self.count = 0
        self.max_steps = 200_000           # ponytail: trần chống loop vô hạn; nâng nếu cần script dài
        self.deadline = (time.monotonic() + max_seconds) if max_seconds else None  # trần thời gian cả kịch bản


class _Stop(Exception):
    """stop action -> dừng sạch cả kịch bản (ok=True)."""


def _foreach_items(s: dict, ctx: _Ctx) -> list[str]:
    """Nguồn foreach: file (mỗi dòng 1 mục) hoặc list/text ({{var}} nhiều dòng)."""
    if s.get("file"):
        p = Path(_subst(s["file"], ctx.vars))
        p = p if p.is_absolute() else ctx.workdir / p
        return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    raw = _subst(s.get("list", s.get("text", "")), ctx.vars)
    return [ln for ln in raw.splitlines() if ln.strip()]


def _run_steps(steps: list[dict], ctx: _Ctx) -> None:
    """Chạy list step (đệ quy vào control-flow). Ném _Stop khi gặp stop."""
    page = ctx.page
    for i, s in enumerate(steps):
        ctx.count += 1
        if ctx.count > ctx.max_steps:
            raise RuntimeError("vượt trần số step (vòng lặp vô hạn?)")
        if ctx.deadline and time.monotonic() > ctx.deadline:   # trần thời gian tổng (captcha/wait treo lâu)
            raise RuntimeError("vượt thời gian tối đa của kịch bản")
        act = s["action"]
        # --- control-flow ---
        if act == "comment":
            continue
        if act == "stop":
            ctx.log.append("stop"); raise _Stop
        if act == "throw":
            raise RuntimeError(_subst(s.get("message", "throw"), ctx.vars))
        if act == "log":
            ctx.log.append(_subst(s.get("message", ""), ctx.vars)); continue
        if act == "if":
            if "selector" in s:
                ok = _elem_exists(page, _subst(s["selector"], ctx.vars), int(s.get("timeout", 0)))
                if str(s.get("negate", "")).lower() == "true":
                    ok = not ok
            else:
                ok = _compare(_subst(s.get("left", ""), ctx.vars), str(s.get("op", "==")),
                              _subst(s.get("right", ""), ctx.vars))
            _run_steps(s.get("then" if ok else "else", []) or [], ctx)
            continue
        if act == "loop":
            n = int(float(_subst(s.get("times", 1), ctx.vars) or 1))
            var = s.get("var", "loopIndex")
            for k in range(max(0, n)):
                ctx.vars[var] = k
                _run_steps(s.get("body", []) or [], ctx)
            continue
        if act == "foreach":
            var, iv = s.get("var", "item"), s.get("indexVar", "loopIndex")
            for k, it in enumerate(_foreach_items(s, ctx)):
                ctx.vars[var] = it; ctx.vars[iv] = k
                _run_steps(s.get("body", []) or [], ctx)
            continue
        if act == "while_exists":
            mx, var, k = int(s.get("max", 50)), s.get("var", "loopIndex"), 0
            while k < mx and _elem_exists(page, _subst(s["selector"], ctx.vars), 0):
                ctx.vars[var] = k
                _run_steps(s.get("body", []) or [], ctx)
                k += 1
            continue
        # --- leaf: có retry ---
        tries = int(s.get("retry", 0) or 0) + 1
        _step_to = s.get("timeout")
        if _step_to:
            page.set_default_timeout(int(_step_to))        # timeout riêng cho step này
        try:
            for attempt in range(tries):
                try:
                    _exec_leaf(s, ctx, i); break
                except Exception as e:  # noqa: BLE001
                    if attempt + 1 >= tries:
                        raise
                    ctx.log.append(f"step {i} retry {attempt + 1}: {e}")
            else:
                continue
        finally:
            if _step_to:
                page.set_default_timeout(ctx.timeout)      # khôi phục mặc định -> không rò sang step sau
        ctx.log.append(f"step {i} ok: {act}")


def _exec_leaf(s: dict, ctx: _Ctx, i: int) -> None:
    """Thực thi 1 action lá (không control-flow). Ghi biến vào ctx.vars/ctx.data."""
    page, v, wd = ctx.page, ctx.vars, ctx.workdir
    act = s["action"]
    def g(key: str, default: str = "") -> str:  # tham số chuỗi + thay {{var}}
        return _subst(s.get(key, default), v)
    def save(name: str, val: Any) -> None:
        v[name] = val; ctx.data[name] = val

    # ---- Browser
    if act == "goto": page.goto(g("url"), wait_until=s.get("wait_until", "load"))
    elif act == "click": page.click(g("selector"))
    elif act == "type": page.type(g("selector"), g("text"))
    elif act == "fill": page.fill(g("selector"), g("text"))
    elif act == "human_type":
        page.click(g("selector"))
        page.type(g("selector"), g("text"), delay=int(s.get("delay", 90)))   # gõ chậm như người
    elif act == "clear": page.fill(g("selector"), "")
    elif act == "hover": page.hover(g("selector"))
    elif act == "dblclick": page.dblclick(g("selector"))
    elif act == "rightclick": page.click(g("selector"), button="right")
    elif act == "select":
        val = g("value")
        page.select_option(g("selector"), value=(val or None))
    elif act == "check":
        (page.check if g("state", "check") != "uncheck" else page.uncheck)(g("selector"))
    elif act == "press": page.keyboard.press(g("key"))
    elif act == "uploadfile": page.set_input_files(g("selector"), g("path"))
    elif act == "scroll": page.mouse.wheel(int(s.get("x", 0)), int(s.get("y", 600)))
    elif act == "scrollto": page.query_selector(g("selector")).scroll_into_view_if_needed()
    elif act == "wait": page.wait_for_timeout(int(float(g("ms", "0") or 0)))
    elif act == "waitfor": page.wait_for_selector(g("selector"))
    elif act == "waittext": page.wait_for_selector(f"text={g('text')}")
    elif act == "waiturl": page.wait_for_url(f"**{g('contains')}**")
    elif act == "screenshot": page.screenshot(path=str(wd / (g("path") or f"shot_{i}.png")),
                                              full_page=str(s.get("full", "")).lower() == "true")
    elif act == "eval": save(s.get("as", f"eval_{i}"), page.evaluate(s["js"]))
    elif act == "extract":
        el = page.query_selector(g("selector"))
        val = (el.get_attribute(s["attr"]) if s.get("attr") else el.inner_text()) if el else None
        save(s.get("as", f"extract_{i}"), val)
    elif act == "getattr":
        el = page.query_selector(g("selector"))
        save(s.get("as", f"attr_{i}"), el.get_attribute(g("attr")) if el else None)
    elif act == "geturl": save(s.get("as", "url"), page.url)
    elif act == "gettitle": save(s.get("as", "title"), page.title())
    elif act == "exists": save(s.get("as", "exists"), page.query_selector(g("selector")) is not None)
    elif act == "count": save(s.get("as", "count"), len(page.query_selector_all(g("selector"))))
    elif act == "newtab": ctx.page = page.context.new_page(); ctx.page.goto(g("url"))
    elif act == "switchtab":
        pages = page.context.pages
        ctx.page = pages[min(int(g("index", "0") or 0), len(pages) - 1)]; ctx.page.bring_to_front()
    elif act == "closetab":
        page.close()
        ctx.page = page.context.pages[-1] if page.context.pages else page.context.new_page()
    elif act == "reload": page.reload()
    elif act == "goback": page.go_back()
    elif act == "getcookies":
        cs = page.context.cookies()
        if s.get("name"): cs = [c for c in cs if c.get("name") == g("name")]
        import json as _j
        save(s.get("as", "cookies"), _j.dumps(cs))
    elif act == "setcookie":
        page.context.add_cookies([{"name": g("name"), "value": g("value"),
                                   "url": g("domain") or page.url}])
    elif act == "image_click":
        hit = _image_click(page, s["template"], float(s.get("threshold", 0.85)), wd)
        if not hit and s.get("required", True):
            raise RuntimeError(f"image_click: không thấy {s['template']}")
        save(s.get("as", f"img_{i}"), hit)
    # ---- Data / biến
    elif act == "set_var": save(g("var"), g("value"))
    elif act == "inc_var":
        save(g("var"), float(v.get(g("var"), 0) or 0) + float(g("by", "1") or 1))
    elif act == "math":
        import ast
        import operator as op
        save(s.get("as", "result"), _safe_math(g("expr"), ast, op))
    elif act == "http_request":
        save(s.get("as", "resp"), _http(g("method", "GET"), g("url"), g("body"),
                                        s.get("headers", ""), v, int(s.get("timeout", 30))))
    elif act == "parse_json":
        import json as _j
        save(s.get("as", "value"), _json_path(_j.loads(g("input") or "{}"), g("path")))
    elif act == "regex":
        m = re.search(g("pattern"), g("input"))
        save(s.get("as", "match"), (m.group(1) if m and m.groups() else (m.group(0) if m else "")))
    elif act == "random_data": save(s.get("as", "value"), _random_data(g("kind"), g("arg")))
    elif act == "random_number":
        import random
        save(s.get("as", "num"), random.randint(int(g("min", "0") or 0), int(g("max", "100") or 100)))
    elif act == "random_line":
        import random
        p = Path(g("path")); p = p if p.is_absolute() else wd / p
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        save(s.get("as", "line"), random.choice(lines) if lines else "")
    elif act == "read_file":
        p = Path(g("path")); p = p if p.is_absolute() else wd / p
        save(s.get("as", "content"), p.read_text(encoding="utf-8"))
    elif act == "write_file":
        p = Path(g("path")); p = p if p.is_absolute() else wd / p
        mode = "a" if str(s.get("append", "")).lower() == "true" else "w"
        with open(p, mode, encoding="utf-8") as f:
            f.write(g("content"))
    elif act == "split_text":
        parts = g("input").split(g("sep"))
        idx = int(s.get("index", 0))
        save(s.get("as", "part"), parts[idx] if -len(parts) <= idx < len(parts) else "")
    # ---- Account
    elif act == "gen_2fa": save(s.get("as", "otp"), _totp(g("secret")))
    elif act == "telegram":
        _http("POST", f"https://api.telegram.org/bot{g('token')}/sendMessage", "",
              "", v, 15, json_body={"chat_id": g("chatid"), "text": g("message")})
    elif act == "solve_captcha":
        tok = _solve_captcha_2captcha(g("apikey"), g("type", "recaptcha_v2"),
                                      g("sitekey"), page.url, g("action"))
        save(s.get("as", "captcha"), tok)
        if str(s.get("inject", "true")).lower() == "true" and tok:
            page.evaluate(_CAPTCHA_INJECT_JS, tok)
    else:
        raise RuntimeError(f"action chưa cài: {act}")


def _safe_math(expr: str, ast: Any, op: Any) -> float:
    """Tính biểu thức số học an toàn (chỉ + - * / % ** và số), không eval()."""
    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
           ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos}
    def ev(n: Any) -> float:
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp):
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            return ops[type(n.op)](ev(n.operand))
        raise ValueError("biểu thức không hợp lệ")
    return ev(ast.parse(expr, mode="eval").body)


def _http(method: str, url: str, body: str, headers_raw: str, vars: dict,
          timeout: int, json_body: dict | None = None) -> str:
    """HTTP request thuần stdlib (urllib). headers_raw: 'Key: Value' mỗi dòng ({{var}} được)."""
    import json as _j
    import urllib.request
    hdrs: dict[str, str] = {}
    for ln in (headers_raw or "").splitlines():
        if ":" in ln:
            k, val = ln.split(":", 1)
            hdrs[k.strip()] = _subst(val.strip(), vars)
    data = None
    if json_body is not None:
        data = _j.dumps(json_body).encode(); hdrs.setdefault("Content-Type", "application/json")
    elif body:
        data = body.encode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL do user nhập)
        return r.read().decode("utf-8", "replace")


_CAPTCHA_INJECT_JS = """tok => {
  const set = (sel) => { const e = document.querySelector(sel); if (e) { e.value = tok;
    e.dispatchEvent(new Event('input', {bubbles:true})); } };
  set('#g-recaptcha-response'); set('[name="g-recaptcha-response"]');
  set('[name="h-captcha-response"]'); set('#h-captcha-response');
}"""


def _solve_captcha_2captcha(apikey: str, ctype: str, sitekey: str, pageurl: str, action: str) -> str:
    """Giải captcha qua API kiểu 2captcha (in.php/res.php). recaptcha_v2/v3/hcaptcha. Trả token."""
    import time
    import urllib.parse
    import urllib.request
    method = {"recaptcha_v2": "userrecaptcha", "recaptcha_v3": "userrecaptcha",
              "hcaptcha": "hcaptcha"}.get(ctype, "userrecaptcha")
    q = {"key": apikey, "method": method, "googlekey": sitekey, "sitekey": sitekey,
         "pageurl": pageurl, "json": "1"}
    if ctype == "recaptcha_v3":
        q["version"] = "v3"; q["action"] = action or "verify"
    in_url = "https://2captcha.com/in.php?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(in_url, timeout=30) as r:  # noqa: S310
        import json as _j
        rid = _j.loads(r.read())["request"]
    for _ in range(40):                                  # chờ tối đa ~2 phút
        time.sleep(5)
        res_url = f"https://2captcha.com/res.php?key={apikey}&action=get&id={rid}&json=1"
        with urllib.request.urlopen(res_url, timeout=30) as r:  # noqa: S310
            import json as _j
            d = _j.loads(r.read())
        if d.get("status") == 1:
            return d["request"]
        if d.get("request") != "CAPCHA_NOT_READY":
            raise RuntimeError(f"captcha lỗi: {d.get('request')}")
    raise RuntimeError("captcha quá thời gian chờ")


# ---------------------------------------------------------------- Recorder (ghi thao tác -> step)

# Inject vào trang live: bắt click/change + ghi URL, sinh selector ổn định (id > attr > path nth-of-type).
# Đẩy vào window.__pinkrec; UI poll fetch_recording để rút ra trước khi điều hướng xoá biến window.
_RECORDER_JS = r"""(function(){
  window.__pinkrec = window.__pinkrec || [];
  if(!window.__pinkRecNav){ window.__pinkRecNav = 1;
    try{ window.__pinkrec.push({action:'goto', url: location.href}); }catch(e){} }
  if(window.__pinkRecOn) return; window.__pinkRecOn = true;
  function uniq(s){ try{ return document.querySelectorAll(s).length === 1; }catch(e){ return false; } }
  function sel(el){
    if(!el || el.nodeType !== 1 || el === document.body) return 'body';
    if(el.id && uniq('#'+CSS.escape(el.id))) return '#'+CSS.escape(el.id);
    for(var i=0;i<4;i++){ var a=['data-testid','name','aria-label','placeholder'][i];
      var v = el.getAttribute && el.getAttribute(a);
      if(v){ var s = el.tagName.toLowerCase()+'['+a+'="'+String(v).replace(/"/g,'\\"')+'"]'; if(uniq(s)) return s; } }
    var path=[], node=el;
    while(node && node.nodeType===1 && node!==document.body){
      var part=node.tagName.toLowerCase();
      var sib=[].slice.call(node.parentNode?node.parentNode.children:[]).filter(function(c){return c.tagName===node.tagName;});
      if(sib.length>1) part += ':nth-of-type('+(sib.indexOf(node)+1)+')';
      path.unshift(part);
      if(uniq(path.join('>'))) break;
      node=node.parentNode;
    }
    return path.join('>') || el.tagName.toLowerCase();
  }
  document.addEventListener('click', function(e){
    var t=e.target; if(!t) return;
    window.__pinkrec.push({action:'click', selector: sel(t)});
  }, true);
  document.addEventListener('change', function(e){
    var t=e.target; if(!t||t.nodeType!==1) return; var tag=t.tagName;
    if(tag==='SELECT') window.__pinkrec.push({action:'select', selector: sel(t), value: t.value});
    else if(tag==='INPUT'||tag==='TEXTAREA') window.__pinkrec.push({action:'fill', selector: sel(t), text: t.value});
  }, true);
})();"""

_DRAIN_JS = "(()=>{const r=window.__pinkrec||[];window.__pinkrec=[];return r;})()"


def start_recording(ws_endpoint: str, *, engine: str = "chromium") -> bool:
    """Bật ghi thao tác: inject recorder vào trang hiện tại + mọi trang mở sau (add_init_script)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = _connect(pw, engine, ws_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        ctx.add_init_script(_RECORDER_JS)                    # trang mở sau khi bật
        for p in ctx.pages:
            try:
                p.evaluate(_RECORDER_JS)                      # trang đang mở
            except Exception:  # noqa: BLE001
                pass
        browser.close()
    return True


def fetch_recording(ws_endpoint: str, *, engine: str = "chromium") -> list[dict]:
    """Rút các thao tác đã ghi từ mọi trang (xoá khỏi trang). Gọi lặp lại để gom trước khi điều hướng."""
    from playwright.sync_api import sync_playwright
    steps: list[dict] = []
    with sync_playwright() as pw:
        browser = _connect(pw, engine, ws_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        for p in ctx.pages:
            try:
                steps += p.evaluate(_DRAIN_JS) or []
            except Exception:  # noqa: BLE001
                pass
        browser.close()
    return steps


def run_script(ws_endpoint: str, steps: list[dict], *, engine: str = "chromium",
               workdir: str | Path = ".", default_timeout: int = 20000, max_seconds: int = 600) -> dict:
    """Nối browser (camoufox=Playwright Firefox, còn lại=CDP Chromium), chạy step. Trả {ok, log[], data{}}."""
    from playwright.sync_api import sync_playwright
    errs = validate_script(steps)
    if errs:
        return {"ok": False, "log": errs, "data": {}}
    workdir = Path(workdir)
    with sync_playwright() as pw:
        browser = _connect(pw, engine, ws_endpoint)
        bctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = bctx.pages[0] if bctx.pages else bctx.new_page()
        page.set_default_timeout(default_timeout)
        ctx = _Ctx(browser, page, workdir, default_timeout, max_seconds)
        try:
            _run_steps(steps, ctx)
        except _Stop:
            pass
        except Exception as e:  # noqa: BLE001
            ctx.log.append(f"step lỗi: {e}")
            browser.close()
            return {"ok": False, "log": ctx.log, "data": ctx.data, "vars": ctx.vars}
        browser.close()
    return {"ok": True, "log": ctx.log, "data": ctx.data, "vars": ctx.vars}
