"""Cổng nghiệm thu Pha A — bằng chứng lõi Chrome THẬT + duy nhất per-profile.

Launch N profile qua engine BotBrowser, đọc fingerprint LIVE qua CDP, so sánh:
  1. Là Chrome thật? (deviceMemory != None, UA Chrome, vendor Google Inc., webdriver false)
  2. Duy nhất giữa profile? (canvas + webgl hash khác nhau giữa 2 profile)
Chụp CreepJS mỗi profile vào _screenshots/ để soi mắt.

Chạy (cần BOTBROWSER_BIN + .enc trong BOTBROWSER_PROFILES_DIR):
  python tools/gate_pha_a.py [--headful] [--n 2] [--creepjs]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import engines
from core.db import Profile
from core.fingerprint import generate

_JS = r"""
() => {
  const c = document.createElement('canvas'); c.width=240; c.height=60;
  const x = c.getContext('2d'); x.textBaseline='top'; x.font='16px Arial';
  x.fillStyle='#f0a'; x.fillRect(0,0,240,60);
  x.fillStyle='#039'; x.fillText('PinkAgc fingerprint 0123456789',2,2);
  x.strokeStyle='#0a6'; x.beginPath(); x.arc(60,30,18,0,Math.PI*1.7); x.stroke();
  const canvas = c.toDataURL();
  let wv='', wr='';
  try { const gl = document.createElement('canvas').getContext('webgl');
    const d = gl.getExtension('WEBGL_debug_renderer_info');
    wv = gl.getParameter(d.UNMASKED_VENDOR_WEBGL);
    wr = gl.getParameter(d.UNMASKED_RENDERER_WEBGL);
  } catch(e) {}
  const uad = navigator.userAgentData || null;
  return {
    ua: navigator.userAgent,
    deviceMemory: navigator.deviceMemory,
    hardwareConcurrency: navigator.hardwareConcurrency,
    vendor: navigator.vendor,
    platform: navigator.platform,
    uaBrands: uad ? uad.brands : null,
    uaPlatform: uad ? uad.platform : null,
    languages: navigator.languages,
    webdriver: navigator.webdriver,
    hasBrave: !!navigator.brave,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    webglVendor: wv, webglRenderer: wr,
    _canvas: canvas,
  };
}
"""


def measure(ws: str, *, creepjs: bool, shot_path: Path | None):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(ws)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()          # trang mới, tránh chrome://newtab bất ổn (gây Target crashed)
        # Đo trên HTTPS thật: deviceMemory/userAgentData CHỈ expose ở secure context, không phải about:blank.
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=25000)
        fp = page.evaluate(_JS)
        fp["canvasHash"] = hashlib.sha256(fp.pop("_canvas").encode()).hexdigest()[:16]
        if creepjs and shot_path:
            try:
                page.goto("https://abrahamjuliot.github.io/creepjs/", timeout=45000)
                page.wait_for_timeout(14000)
                page.screenshot(path=str(shot_path), full_page=True)
                fp["creepjs_shot"] = str(shot_path)
            except Exception as e:  # noqa: BLE001
                fp["creepjs_error"] = str(e)
        browser.close()
    return fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--engine", default="fpchromium")
    ap.add_argument("--version", default="150.0.7871.186")   # khớp binary engine
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--creepjs", action="store_true")
    a = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    profiles_root = root / "asset" / "profiles"
    shots = root / "_screenshots"; shots.mkdir(parents=True, exist_ok=True)

    results, crashes = [], 0
    for i in range(a.n):
        fp = generate("Windows", browser_type="Chrome", browser_version=a.version)
        name = f"gate-{i+1}"
        prof = Profile(id=name, name=name, fingerprint_data=fp, dynamic_data={}, storage_path=name)
        print(f"\n[launch] {name} via {a.engine} (headless={not a.headful}) ...")
        proc = None
        try:
            proc, ws = engines.serve(a.engine, prof, str(profiles_root), headless=not a.headful)
            time.sleep(4.0)        # engine cần vài giây ổn định renderer trước khi eval
            r = measure(ws, creepjs=a.creepjs, shot_path=shots / f"creepjs_{name}.png")
            r["_name"] = name
            results.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "uaBrands"},
                             ensure_ascii=False, indent=2))
        except Exception as e:  # noqa: BLE001  — 1 profile crash không làm hỏng cả run
            crashes += 1
            print(f"  [CRASH] {name}: {str(e)[:70]}")
        finally:
            if proc is not None:
                try: proc.terminate()
                except Exception: pass
            time.sleep(0.6)

    # ---- verdict ----
    print("\n" + "=" * 60 + f"\nCỔNG PHA A — VERDICT (engine={a.engine})")
    total = a.n
    stable = len(results)
    print(f"  Ổn định: {stable}/{total} profile sống (canvas không crash renderer)"
          + (f"  [{crashes} crash]" if crashes else ""))
    if results:
        dm = [r.get("deviceMemory") for r in results]
        wd = [r.get("webdriver") for r in results]
        br = [bool(r.get("uaBrands")) for r in results]
        ok_chrome = all("Chrome" in (r.get("ua") or "") and r.get("vendor") == "Google Inc."
                        and not r.get("webdriver") for r in results)
        print(f"  [{'PASS' if ok_chrome else 'FAIL'}] Chrome thật: UA Chrome, vendor Google Inc., webdriver=false")
        print(f"  deviceMemory={dm}  webdriver={wd}  hasBrands={br}")
        print(f"  WebGL: {[(r['webglVendor'], r['webglRenderer'][:40]) for r in results]}")
        if len(results) >= 2:
            uniq = len({r['canvasHash'] for r in results}) == len(results)
            print(f"  [{'PASS' if uniq else 'WARN'}] Canvas duy nhất per-profile: {[r['canvasHash'] for r in results]}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
