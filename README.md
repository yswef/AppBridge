# AppBridge

**[العربية](README.ar.md)** · English

AppBridge is a Windows desktop app that copies an Android app or game — **APK and split APKs, OBB
files and the downloaded game resources in `Android/data`** — from one phone to your computer, then
installs it on one or many other phones over USB. Your friends don't have to download a multi‑GB
game again. The main example is Free Fire (`com.dts.freefireth`).

- Works **fully offline**. No accounts, no analytics, nothing leaves your computer.
- **USB only**, using Google's official `adb` (bundled — nothing to install).
- Arabic and English UI with instant switching and full RTL, light/dark theme.

> **For personal use.** Share only apps you are allowed to share. AppBridge copies apps exactly as
> they are: it never modifies, re‑signs or cracks APKs and never bypasses licence or protection checks.

## Download & install

Get the latest version from **[Releases](https://github.com/yswef/AppBridge/releases)**:

- `AppBridge-x.y.z-setup.exe` — installer (no admin rights needed, adds a Start‑menu entry and
  lets you open `.appbridge` files by double‑click), or
- `AppBridge-x.y.z-win64-portable.zip` — unzip anywhere and run `AppBridge.exe`. Rename
  `portable.txt.example` to `portable.txt` to keep settings, logs and the library beside the app.

Requirements: Windows 10/11 64‑bit with the Microsoft Edge **WebView2 Runtime** (already present on
Windows 11 and on up‑to‑date Windows 10; otherwise
[install it](https://go.microsoft.com/fwlink/p/?LinkId=2124703)).

### Windows SmartScreen warning

The builds are **not code‑signed** (a signing certificate costs money), so on first run Windows may
show *“Windows protected your PC”*. Click **More info → Run anyway**. You can check the download
against `SHA256SUMS.txt` on the release page, or build it yourself from source (below).

## How to use

1. **Enable USB debugging** on the phone: *Settings → About phone →* tap *Build number* 7 times,
   then *Settings → System → Developer options → USB debugging*. On Xiaomi/Oppo/Vivo also enable
   *Install via USB*. (The app has an illustrated guide: *Devices → How to enable USB debugging*.)
2. **Connect the first phone** with a data USB cable. It appears on the *Devices* page with its model,
   Android version and free space. If it shows *Waiting for permission*, unlock the phone and tap
   **Allow** on *“Allow USB debugging?”* (tick *Always allow*).
3. Open **Phone apps**, filter *Games* / *User apps* / *All*, pick the game and press
   **Extract to library**. You can choose whether to include OBB and `Android/data`.
4. Follow the progress in **Tasks** (bytes, speed, time left). You can pause and resume; if the cable
   is pulled the task waits for the same phone and continues **without re‑copying finished files**.
5. **Unplug the first phone, connect the other one(s)** — one at a time or several through a USB hub.
6. In **Library**, press **Install**, choose the phones and review the checks (version, signature,
   space…). Each phone is installed in parallel; a failure on one never stops the others.

### Share with a friend who has their own PC

*Library → Export bundle* creates one `.appbridge` file (optionally split into parts such as
`.appbridge.001`, `.002` of 2 GB each — set the size in *Settings*). Your friend opens it with
*Library → Import bundle* (or just double‑clicks it after installing AppBridge). The bundle also
contains an `Install.bat` that works with only `adb.exe`: rename the bundle to `.zip`, extract it, put
`adb.exe` next to `Install.bat` and run it.

## What gets copied — and the limits

| Copied | Not copied |
| --- | --- |
| All APK files (`pm path`: base + split APKs) | Internal app data `/data/data/<package>` (logins, saved progress) — impossible without root |
| `/sdcard/Android/obb/<package>` | Other apps' data, accounts |
| `/sdcard/Android/data/<package>` (downloaded resources) | |

- The copied app starts **fresh** on the other phone (log in again). Online games may refuse to
  start if their **server requires a newer version** or verifies the account/device.
- **Android 14 / `Android/data`**: most phones allow ADB to read and write this folder, but some
  vendors block it. AppBridge then tells you clearly and offers to continue without it (the game will
  re‑download its resources). When installing, if the phone refuses to write there, AppBridge opens
  the game once so Android creates the folder, then retries.
- Android 14 blocks apps that target very old Android versions; AppBridge retries automatically with
  `--bypass-low-target-sdk-block`.
- Installing an **older** version over a newer one, or an app signed differently from the installed
  one, requires uninstalling it first (local data on that phone is lost). AppBridge asks before doing it.
- Native code must match the phone's CPU (e.g. copy from an `arm64` phone to an `arm64` phone).
- Some phones need their maker's USB driver on Windows (e.g. *Samsung USB Driver*).

## Safety checks

- SHA‑256 of every file is recorded at extraction (`manifest.json`) and verified before installing
  (*Settings* can turn this off) or on demand (*Library → Verify integrity*).
- Signing certificates are read from the APK Signature Scheme v2/v3 block (v1 as fallback); all split
  APKs must share the same certificate, and the certificate is compared with the app already installed
  on the target phone.
- Installed `versionCode` is compared (downgrade warning), plus minimum SDK, CPU ABI and free space.

## Where things are stored

- Library: `Documents\AppBridge Library` by default (change it in *Settings*). One folder per app with
  `manifest.json`, `icon.png`, `apk\`, `obb\`, `data\`; the SQLite index `library.db` is rebuilt from
  the folders, so a library can be moved or copied.
- Settings and logs: `%LOCALAPPDATA%\AppBridge`. *Settings → Export logs* zips the logs if you need help.
- Tip: choose a short library path (e.g. `D:\AppBridge`) — some games have very deep data folders.

## Build from source

Requirements: Python 3.11+, Node.js 20+, Windows for the final build.

```bash
# UI
cd frontend && npm ci && npm run build && cd ..
# official platform-tools (adb) into backend/vendor/platform-tools
python tools/fetch_platform_tools.py            # --os linux for development on Linux
# run from source
pip install -e ".[dev]"
python backend/main.py
# Windows build (dist/AppBridge) + optional installer
pyinstaller packaging/appbridge.spec --noconfirm
iscc /DMyAppVersion=0.1.0 packaging\installer.iss
```

UI development with hot reload: `npm run dev` in `frontend/` (a mock backend is used in a normal
browser), or run `APPBRIDGE_DEV_URL=http://localhost:5173 python backend/main.py` to use the real
backend. `APPBRIDGE_DEBUG=1` enables verbose logs and the WebView devtools.

Tests and lint: `pytest -q` and `ruff check backend tools`. The tests use recorded `adb` output and a
fake device (a folder emulating the phone), covering parsing, extraction/resume after a pulled cable,
installs on several phones, hashes, signatures, version comparison and bundles.

### Releases

GitHub Actions (`.github/workflows/build.yml`) runs lint and tests on every push, builds the Windows
app (PyInstaller onedir + zip + Inno Setup installer) and, when a tag like `v0.1.0` is pushed, creates
a GitHub Release with the files attached:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Or run the **build** workflow manually from the *Actions* tab and enter a tag such as `v0.1.1` in the
*release* field — the workflow builds, creates the tag and publishes the release.

## Project layout

```
backend/appbridge/  adb.py devices.py scanner.py extractor.py installer.py library.py
                    bundle.py verify.py api.py errors.py jobs.py transfer.py manifest.py …
backend/tests/      unit tests (recorded adb output, fake device)
backend/main.py     pywebview entry point
frontend/           React + Vite + TypeScript UI (ar/en, RTL, light/dark)
tools/              fetch_platform_tools.py, make_icon.py
packaging/          PyInstaller spec, Inno Setup script, icon
```

## License

MIT — see [LICENSE](LICENSE). The Windows build bundles Google's Android SDK Platform‑Tools under
their own license.
