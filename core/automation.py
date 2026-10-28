"""Automation runner — chạy kịch bản no-code trên profile qua CDP (+ OpenCV image-match).

Kịch bản = list step dict (JSON), ví dụ:
  [{"action":"goto","url":"https://x.com"},
   {"action":"waitfor","selector":"#user"},
   {"action":"type","selector":"#user","text":"acc1"},
   {"action":"image_click","template":"login_btn.png","threshold":0.85},
   {"action":"extract","selector":".balance","as":"bal"}]

validate_script() thuần (test được không cần browser). run_script() nối Playwright qua CDP endpoint
(lấy từ engines.serve) và thực thi. image_click = OpenCV template-match trên screenshot rồi click toạ độ.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# action -> tuple các key bắt buộc
_ACTIONS: dict[str, tuple[str, ...]] = {
    "goto": ("url",), "click": ("selector",), "type": ("selector", "text"),
    "fill": ("selector", "text"), "wait": ("ms",), "waitfor": ("selector",),
    "press": ("key",), "scroll": (), "screenshot": (), "eval": ("js",),
    "extract": ("selector",), "image_click": ("template",),
}


def validate_script(steps: list[dict]) -> list[str]:
    """Trả list lỗi (rỗng = hợp lệ)."""
    errs = []
    if not isinstance(steps, list):
        return ["script phải là list step"]
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or "action" not in s:
            errs.append(f"step {i}: thiếu 'action'"); continue
        act = s["action"]
        if act not in _ACTIONS:
            errs.append(f"step {i}: action không hỗ trợ {act!r} ({list(_ACTIONS)})"); continue
        for k in _ACTIONS[act]:
            if k not in s:
                errs.append(f"step {i} ({act}): thiếu '{k}'")
    return errs


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


def _connect(pw: Any, engine: str, ws_endpoint: str) -> Any:
    """camoufox phát ws endpoint Playwright-Firefox (connect); còn lại là CDP Chromium."""
    return (pw.firefox.connect(ws_endpoint) if engine == "camoufox"
            else pw.chromium.connect_over_cdp(ws_endpoint))


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


def run_script(ws_endpoint: str, steps: list[dict], *, engine: str = "chromium",
               workdir: str | Path = ".", default_timeout: int = 20000) -> dict:
    """Nối browser (camoufox=Playwright Firefox, còn lại=CDP Chromium), chạy step. Trả {ok, log[], data{}}."""
    from playwright.sync_api import sync_playwright
    errs = validate_script(steps)
    if errs:
        return {"ok": False, "log": errs, "data": {}}
    workdir = Path(workdir)
    log: list[str] = []
    data: dict[str, Any] = {}
    with sync_playwright() as pw:
        browser = _connect(pw, engine, ws_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(default_timeout)
        try:
            for i, s in enumerate(steps):
                act = s["action"]
                if act == "goto": page.goto(s["url"], wait_until=s.get("wait_until", "load"))
                elif act == "click": page.click(s["selector"])
                elif act == "type": page.type(s["selector"], s["text"])   # gõ từng phím (bắn keydown/up)
                elif act == "fill": page.fill(s["selector"], s["text"])     # set value thẳng (nhanh)
                elif act == "wait": page.wait_for_timeout(int(s["ms"]))
                elif act == "waitfor": page.wait_for_selector(s["selector"])
                elif act == "press": page.keyboard.press(s["key"])
                elif act == "scroll": page.mouse.wheel(int(s.get("x", 0)), int(s.get("y", 600)))
                elif act == "screenshot": page.screenshot(path=str(workdir / s.get("path", f"shot_{i}.png")))
                elif act == "eval": data[s.get("as", f"eval_{i}")] = page.evaluate(s["js"])
                elif act == "extract":
                    el = page.query_selector(s["selector"])
                    val = (el.get_attribute(s["attr"]) if s.get("attr") else el.inner_text()) if el else None
                    data[s.get("as", f"extract_{i}")] = val
                elif act == "image_click":
                    hit = _image_click(page, s["template"], float(s.get("threshold", 0.85)), workdir)
                    if not hit and s.get("required", True):
                        raise RuntimeError(f"image_click: không thấy {s['template']}")
                    data[s.get("as", f"img_{i}")] = hit
                log.append(f"step {i} ok: {act}")
        except Exception as e:  # noqa: BLE001
            log.append(f"step lỗi: {e}")
            browser.close()
            return {"ok": False, "log": log, "data": data}
        browser.close()
    return {"ok": True, "log": log, "data": data}
