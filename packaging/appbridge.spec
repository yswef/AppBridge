# PyInstaller spec - build with:  pyinstaller packaging/appbridge.spec --noconfirm
# Produces dist/AppBridge/ (onedir, portable). Run from the repository root.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
web = ROOT / "frontend" / "dist"
tools = ROOT / "backend" / "vendor" / "platform-tools"
if not (web / "index.html").exists():
    raise SystemExit("frontend/dist is missing - run `npm ci && npm run build` in frontend/ first")
if not tools.exists():
    raise SystemExit("platform-tools missing - run `python tools/fetch_platform_tools.py` first")

datas = [(str(web), "web"), (str(tools), "platform-tools")]
datas += collect_data_files("pyaxmlparser")
datas += collect_data_files("webview")

a = Analysis(
    [str(ROOT / "backend" / "main.py")],
    pathex=[str(ROOT / "backend")],
    datas=datas,
    hiddenimports=collect_submodules("appbridge") + ["webview.platforms.edgechromium"],
    excludes=["tkinter", "matplotlib", "numpy", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AppBridge",
    icon=str(ROOT / "packaging" / "appbridge.ico"),
    console=False,
    upx=False,
    version=str(ROOT / "packaging" / "version_info.txt") if (ROOT / "packaging" / "version_info.txt").exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AppBridge")
