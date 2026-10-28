"""Tải + giải nén BotBrowser (engine Chromium) từ release botswin/BotBrowser.

Dùng:  python tools/setup_botbrowser.py [--dest vendor/botbrowser]
Xong -> in ra lệnh export BOTBROWSER_BIN.

Lưu ý: binary ~726MB (win_x64). Profile .enc phân phối riêng (tự tạo/mua/sample).
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

RELEASE_API = "https://api.github.com/repos/botswin/BotBrowser/releases/latest"


def _asset_match() -> str:
    sysname = platform.system().lower()
    if sysname == "windows":
        return "win_x64.7z"
    if sysname == "darwin":
        return "mac_arm64.dmg" if platform.machine().lower() in ("arm64", "aarch64") else "mac_x64.dmg"
    return "arm64.deb" if platform.machine().lower() in ("arm64", "aarch64") else "x64.deb"


def _latest_asset():
    req = urllib.request.Request(RELEASE_API, headers={"User-Agent": "clone-gpm"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    want = _asset_match()
    for a in data.get("assets", []):
        if a["name"].endswith(want):
            return data["tag_name"], a["name"], a["browser_download_url"], a["size"]
    raise RuntimeError(f"Không tìm thấy asset khớp *{want} trong release {data.get('tag_name')}")


def _download(url: str, dest: Path, size: int):
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Tải {dest.name} ({size // 1048576}MB) ...")
    req = urllib.request.Request(url, headers={"User-Agent": "clone-gpm"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk); done += len(chunk)
            print(f"\r  {done // 1048576}/{size // 1048576}MB", end="", flush=True)
    print()


def _extract(archive: Path, dest: Path) -> Path | None:
    """Giải nén .7z (Windows). Trả path tới chrome.exe nếu thấy."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".7z":
        # Ưu tiên py7zr (self-contained, không cần cài 7-Zip); fallback sang 7z CLI.
        try:
            import py7zr
            with py7zr.SevenZipFile(archive, "r") as z:
                z.extractall(path=dest)
        except ImportError:
            for exe in ("7z", "7za", r"C:\Program Files\7-Zip\7z.exe"):
                try:
                    subprocess.run([exe, "x", f"-o{dest}", "-y", str(archive)], check=True)
                    break
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            else:
                print("! Cần py7zr (pip install py7zr) hoặc 7-Zip để giải nén:", archive)
                return None
    else:
        print(f"! Giải nén {archive.suffix} thủ công (dmg/deb) rồi set BOTBROWSER_BIN.")
        return None
    hits = list(dest.rglob("chrome.exe")) + list(dest.rglob("botbrowser"))
    return hits[0] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="vendor/botbrowser")
    ap.add_argument("--url", help="URL asset cụ thể (pin version khớp .enc; bỏ trống = latest). "
                                  "QUAN TRỌNG: binary PHẢI cùng major với .enc, nếu không BotBrowser "
                                  "từ chối profile và rơi về Chromium trần (webdriver=true).")
    ap.add_argument("--keep-archive", action="store_true")
    a = ap.parse_args()
    dest = Path(a.dest)

    if a.url:
        name = a.url.rstrip("/").split("/")[-1]
        tag, url, size = name, a.url, 0
    else:
        tag, name, url, size = _latest_asset()
    print(f"BotBrowser {tag} -> {name}")
    archive = dest / name
    if not archive.exists():
        _download(url, archive, size)
    binary = _extract(archive, dest / "app")
    if not a.keep_archive and archive.exists():
        archive.unlink()
    if binary:
        print("\n[ok] Binary:", binary)
        print("Export:")
        print(f'  export BOTBROWSER_BIN="{binary}"')
        print(f'  export BOTBROWSER_PROFILES_DIR="{dest.resolve()}/profiles"   # bỏ .enc vào đây')
    else:
        print("\n[!] Giải nén xong nhưng chưa thấy binary — kiểm tra", dest / "app")


if __name__ == "__main__":
    main()
