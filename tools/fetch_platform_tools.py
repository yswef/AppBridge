"""Download Google's official platform-tools and place adb into backend/vendor/platform-tools.

Used by the build (and by developers once). The end user never has to install ADB.

    python tools/fetch_platform_tools.py            # Windows build (default)
    python tools/fetch_platform_tools.py --os linux # for local development on Linux
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://dl.google.com/android/repository/platform-tools-latest-{os}.zip"
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "backend" / "vendor" / "platform-tools"
KEEP = {
    "windows": {"adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt", "source.properties"},
    "linux": {"adb", "NOTICE.txt", "source.properties"},
    "darwin": {"adb", "NOTICE.txt", "source.properties"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", choices=sorted(KEEP), default="windows")
    ap.add_argument("--dest", type=Path, default=DEST)
    args = ap.parse_args()

    url = URL.format(os=args.os)
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    print(f"Downloaded {len(data) / 1e6:.1f} MB")

    if args.dest.exists():
        shutil.rmtree(args.dest)
    args.dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if info.is_dir() or name not in KEEP[args.os]:
                continue
            target = args.dest / name
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if args.os != "windows" and name == "adb":
                target.chmod(0o755)
            print(f"  + {name}")
    missing = {n for n in KEEP[args.os] if n.startswith("adb") or n.endswith(".dll")} - {
        p.name for p in args.dest.iterdir()
    }
    if missing:
        print(f"Missing files: {missing}", file=sys.stderr)
        return 1
    print(f"platform-tools ready in {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
