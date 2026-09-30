"""Integrity, version and signature checks.

* SHA-256 of every file against ``manifest.json``.
* Signing certificates of each APK (APK Signature Scheme v3/v2 block, v1 JAR signature as a
  fallback) and consistency between base and split APKs.
* Pre-install checks against a target phone: installed version (downgrade), installed
  signature, minimum SDK, ABI, free space.

Nothing here modifies an APK: files are only read.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import struct
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import manifest as mf
from .adb import Adb, rquote
from .devices import free_space
from .errors import AppBridgeError
from .fsutil import file_size, long_path, sha256_file

log = logging.getLogger(__name__)

APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
SIG_V2_ID = 0x7109871A
SIG_V3_ID = 0xF05368C0
SIG_V31_ID = 0x1B93AD61

# ---------------------------------------------------------------------------------------------
# File integrity
# ---------------------------------------------------------------------------------------------


@dataclass
class FileProblem:
    path: str
    problem: str  # missing | size | hash
    expected: str = ""
    actual: str = ""


def verify_files(
    folder: Path,
    m: dict,
    kinds: set[str] | None = None,
    on_bytes: Callable[[int], None] | None = None,
    cancel: Callable[[], None] | None = None,
) -> list[FileProblem]:
    problems: list[FileProblem] = []
    for f in m["files"]:
        if kinds and f["kind"] not in kinds:
            continue
        path = Path(folder) / f["path"]
        size = file_size(path)
        if size < 0:
            problems.append(FileProblem(f["path"], "missing"))
            if on_bytes:
                on_bytes(int(f["size"]))
            continue
        if size != int(f["size"]):
            problems.append(FileProblem(f["path"], "size", str(f["size"]), str(size)))
            if on_bytes:
                on_bytes(int(f["size"]))
            continue
        if not f.get("sha256"):
            problems.append(FileProblem(f["path"], "hash", "", "not recorded"))
            continue
        digest = sha256_file(path, on_bytes=on_bytes, cancel=cancel)
        if digest != f["sha256"]:
            problems.append(FileProblem(f["path"], "hash", f["sha256"], digest))
    return problems


def raise_for_problems(problems: list[FileProblem]) -> None:
    if not problems:
        return
    missing = [p for p in problems if p.problem == "missing"]
    code = "FILE_MISSING" if missing and len(missing) == len(problems) else "HASH_MISMATCH"
    detail = "\n".join(f"{p.problem}: {p.path} {p.expected} {p.actual}".strip() for p in problems[:50])
    raise AppBridgeError(code, detail, count=len(problems))


def job_verifier(folder: Path, m: dict, job) -> None:
    """Verifier used by InstallJob / VerifyJob: hashes the files the job needs, with progress."""
    kinds = {"apk"}
    if getattr(job, "include_obb", True):
        kinds.add("obb")
    if getattr(job, "include_data", True):
        kinds.add("data")
    done = {"n": 0}

    def on_bytes(n: int) -> None:
        done["n"] += n
        job.progress.set_done(done["n"])
        job.changed()

    problems = verify_files(folder, m, kinds, on_bytes=on_bytes, cancel=job.check_cancel)
    raise_for_problems(problems)


# ---------------------------------------------------------------------------------------------
# APK signing certificates
# ---------------------------------------------------------------------------------------------


def _find_eocd(tail: bytes) -> int:
    """Offset of the End Of Central Directory record inside ``tail`` (or -1)."""
    # EOCD is 22 bytes + comment (<= 65535). Search backwards for the signature with a consistent comment length.
    pos = len(tail) - 22
    while pos >= 0:
        if tail[pos : pos + 4] == b"PK\x05\x06":
            comment_len = struct.unpack_from("<H", tail, pos + 20)[0]
            if pos + 22 + comment_len == len(tail):
                return pos
        pos -= 1
    return -1


def central_directory_offset(tail: bytes, tail_start: int) -> int:
    """Return the absolute central directory offset, given the last bytes of the file."""
    eocd = _find_eocd(tail)
    if eocd < 0:
        raise ValueError("not a zip file (EOCD not found)")
    cd_offset = struct.unpack_from("<I", tail, eocd + 16)[0]
    if cd_offset == 0xFFFFFFFF:
        loc = eocd - 20
        if loc < 0 or tail[loc : loc + 4] != b"PK\x06\x07":
            raise ValueError("zip64 locator not found")
        z64_abs = struct.unpack_from("<Q", tail, loc + 8)[0]
        rel = z64_abs - tail_start
        if rel < 0 or tail[rel : rel + 4] != b"PK\x06\x06":
            raise ValueError("zip64 EOCD not in tail")
        cd_offset = struct.unpack_from("<Q", tail, rel + 48)[0]
    return cd_offset


def _len_prefixed(buf: bytes, off: int) -> tuple[bytes, int]:
    (n,) = struct.unpack_from("<I", buf, off)
    start = off + 4
    if start + n > len(buf):
        raise ValueError("truncated length-prefixed field")
    return buf[start : start + n], start + n


def parse_signing_block(block: bytes) -> dict[int, bytes]:
    """Parse the ID-value pairs of an APK Signing Block (``block`` = whole block incl. both sizes)."""
    if len(block) < 32 or block[-16:] != APK_SIG_BLOCK_MAGIC:
        raise ValueError("bad signing block magic")
    pairs: dict[int, bytes] = {}
    off = 8
    end = len(block) - 24
    while off < end:
        (length,) = struct.unpack_from("<Q", block, off)
        if length < 4 or off + 8 + length > end:
            raise ValueError("bad signing block pair")
        (pid,) = struct.unpack_from("<I", block, off + 8)
        pairs[pid] = block[off + 12 : off + 8 + length]
        off += 8 + length
    return pairs


def certs_from_scheme_value(value: bytes) -> list[bytes]:
    """Return the first (signing) certificate DER of every signer in a v2/v3 scheme value."""
    certs = []
    signers, _ = _len_prefixed(value, 0)
    off = 0
    while off < len(signers):
        signer, off = _len_prefixed(signers, off)
        signed_data, _ = _len_prefixed(signer, 0)
        _digests, p = _len_prefixed(signed_data, 0)
        cert_seq, _ = _len_prefixed(signed_data, p)
        if cert_seq:
            cert, _ = _len_prefixed(cert_seq, 0)
            certs.append(cert)
    return certs


def read_signing_block(read_at: Callable[[int, int], bytes], size: int) -> bytes | None:
    """Locate and return the APK signing block using a random-access reader ``read_at(offset, length)``."""
    tail_len = min(size, 65536 + 22 + 20 + 56)
    tail_start = size - tail_len
    tail = read_at(tail_start, tail_len)
    cd = central_directory_offset(tail, tail_start)
    if cd < 32:
        return None
    footer = read_at(cd - 24, 24)
    if footer[8:] != APK_SIG_BLOCK_MAGIC:
        return None
    (block_size,) = struct.unpack_from("<Q", footer, 0)
    start = cd - block_size - 8
    if start < 0 or block_size > 64 * 1024 * 1024:
        return None
    return read_at(start, block_size + 8)


def _local_reader(path: Path) -> tuple[Callable[[int, int], bytes], int, object]:
    fh = open(long_path(path), "rb")  # noqa: SIM115 - closed by caller

    def read_at(off: int, n: int) -> bytes:
        fh.seek(off)
        return fh.read(n)

    return read_at, os.fstat(fh.fileno()).st_size, fh


@dataclass
class SigningInfo:
    scheme: str = ""  # v3 | v2 | v1 | none
    certs_sha256: list[str] = field(default_factory=list)
    certs_der: list[bytes] = field(default_factory=list)
    error: str = ""


def _v1_certs(path: Path) -> list[bytes]:
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs7

    certs = []
    with zipfile.ZipFile(long_path(path)) as zf:
        for name in zf.namelist():
            if re.match(r"META-INF/[^/]+\.(RSA|DSA|EC)$", name, re.I):
                for c in pkcs7.load_der_pkcs7_certificates(zf.read(name)):
                    certs.append(c.public_bytes(Encoding.DER))
                break
    return certs


def apk_signing(path: Path) -> SigningInfo:
    info = SigningInfo()
    try:
        read_at, size, fh = _local_reader(path)
        try:
            block = read_signing_block(read_at, size)
        finally:
            fh.close()
        if block:
            pairs = parse_signing_block(block)
            for pid, name in ((SIG_V31_ID, "v3"), (SIG_V3_ID, "v3"), (SIG_V2_ID, "v2")):
                if pid in pairs:
                    info.certs_der = certs_from_scheme_value(pairs[pid])
                    info.scheme = name
                    break
        if not info.certs_der:
            info.certs_der = _v1_certs(path)
            info.scheme = "v1" if info.certs_der else "none"
    except Exception as e:  # noqa: BLE001 - reported as unknown signature
        info.error = f"{type(e).__name__}: {e}"
        info.scheme = "none"
        log.warning("Could not read signature of %s: %s", path, e)
    info.certs_sha256 = [hashlib.sha256(c).hexdigest() for c in info.certs_der]
    return info


def item_signing(folder: Path, m: dict) -> dict:
    """Signing summary for all APKs of an item: {sha256, scheme, consistent, per_apk}."""
    per_apk = {}
    ders: list[bytes] = []
    for f in mf.apk_files(m):
        info = apk_signing(Path(folder) / f["path"])
        per_apk[f["path"]] = {"scheme": info.scheme, "sha256": info.certs_sha256, "error": info.error}
        if not ders and info.certs_der:
            ders = info.certs_der
    sets = [tuple(sorted(v["sha256"])) for v in per_apk.values() if v["sha256"]]
    # every APK must carry the same certificate set (an unsigned split next to signed ones is inconsistent)
    consistent = len(set(sets)) <= 1 and (not sets or len(sets) == len(per_apk))
    first = next(iter(per_apk.values()), {"sha256": [], "scheme": "none"})
    return {
        "sha256": first["sha256"],
        "scheme": first["scheme"],
        "consistent": consistent,
        "per_apk": per_apk,
        "java_hash": [java_signature_hash(d) for d in ders],
    }


def java_signature_hash(der: bytes) -> str:
    """``Integer.toHexString(Arrays.hashCode(signatureBytes))`` - how ``dumpsys package`` prints signatures."""
    h = 1
    for b in der:
        sb = b - 256 if b > 127 else b
        h = (31 * h + sb) & 0xFFFFFFFF
    return format(h, "x")


_SIGS_RE = re.compile(r"signatures:\[([0-9a-fA-F, ]*)\]")


def parse_installed_signatures(dumpsys: str) -> list[str]:
    """Extract the current signature hashes from ``dumpsys package <pkg>``."""
    m = _SIGS_RE.search(dumpsys)
    if not m:
        return []
    return [s.strip().lower() for s in m.group(1).split(",") if s.strip()]


# ---------------------------------------------------------------------------------------------
# Version comparison and pre-install checks
# ---------------------------------------------------------------------------------------------


def compare_versions(item_code: int, installed_code: int | None) -> str:
    if installed_code is None:
        return "not_installed"
    if item_code > installed_code:
        return "upgrade"
    if item_code == installed_code:
        return "same"
    return "downgrade"


CHECK_TEXT: dict[str, tuple[str, str, str, str]] = {
    # code: (en, ar, hint_en, hint_ar)
    "FILES_PRESENT": ("All files are present.", "كل الملفات موجودة.", "", ""),
    "FILE_MISSING": (
        "Some files are missing from the library item.",
        "بعض ملفات عنصر المكتبة مفقودة.",
        "Extract the app again.",
        "أعد استخراج التطبيق.",
    ),
    "NOT_INSTALLED": ("Not installed on this phone — fresh install.", "غير مثبت على هذا الهاتف — تثبيت جديد.", "", ""),
    "UPGRADE": ("Will update version {installed} → {item}.", "سيُحدَّث الإصدار {installed} ← {item}.", "", ""),
    "SAME_VERSION": (
        "The same version is already installed; files will be refreshed.",
        "الإصدار نفسه مثبت مسبقًا؛ سيتم تحديث الملفات.",
        "",
        "",
    ),
    "DOWNGRADE": (
        "The phone has a newer version ({installed}) than this copy ({item}).",
        "الهاتف عليه إصدار أحدث ({installed}) من هذه النسخة ({item}).",
        "Android refuses downgrades. You can keep the newer version, or uninstall it first "
        "(its local data and login on this phone will be lost).",
        "أندرويد يرفض التثبيت فوق إصدار أحدث. يمكنك الإبقاء على الإصدار الأحدث، أو إزالته أولًا "
        "(ستُفقد بياناته المحلية وتسجيل الدخول على هذا الهاتف).",
    ),
    "SIGNATURE_MATCH": (
        "Signing certificate matches the installed app.",
        "شهادة التوقيع مطابقة للتطبيق المثبت.",
        "",
        "",
    ),
    "SIGNATURE_MISMATCH": (
        "The installed app is signed with a different certificate.",
        "التطبيق المثبت موقّع بشهادة مختلفة.",
        "It cannot be updated in place. Uninstall it first (its local data will be lost), or keep it.",
        "لا يمكن تحديثه مباشرة. أزله أولًا (ستُفقد بياناته المحلية) أو أبقِه كما هو.",
    ),
    "SIGNATURE_UNKNOWN": (
        "Could not compare signatures with the installed app.",
        "تعذرت مقارنة التوقيع مع التطبيق المثبت.",
        "",
        "",
    ),
    "SPLITS_CONSISTENT": (
        "All APK parts are signed with the same certificate ({scheme}).",
        "كل أجزاء APK موقّعة بنفس الشهادة ({scheme}).",
        "",
        "",
    ),
    "SPLIT_SIGNATURE_MISMATCH": (
        "APK parts are signed with different certificates.",
        "أجزاء APK موقّعة بشهادات مختلفة.",
        "The copy is inconsistent; extract it again from one phone.",
        "النسخة غير متسقة؛ أعد استخراجها من هاتف واحد.",
    ),
    "SDK_TOO_OLD": (
        "This phone runs Android API {device}, the app needs API {min}.",
        "هذا الهاتف يعمل بـ API {device} والتطبيق يحتاج API {min}.",
        "Use a phone with a newer Android version.",
        "استخدم هاتفًا بإصدار أندرويد أحدث.",
    ),
    "LOW_TARGET_SDK": (
        "The app targets an old Android (API {target}); Android 14 may block it.",
        "التطبيق يستهدف أندرويد قديم (API {target})؛ قد يمنعه أندرويد 14.",
        "AppBridge will retry with --bypass-low-target-sdk-block if needed.",
        "سيعيد AppBridge المحاولة مع ‎--bypass-low-target-sdk-block‎ عند الحاجة.",
    ),
    "ABI_MISMATCH": (
        "This copy has native code for {item_abis}, the phone supports {device_abis}.",
        "هذه النسخة تحتوي كودًا لمعالجات {item_abis} والهاتف يدعم {device_abis}.",
        "Installation will probably fail; extract the app from a phone with a similar CPU.",
        "على الأرجح سيفشل التثبيت؛ استخرج التطبيق من هاتف بمعالج مشابه.",
    ),
    "SPACE_OK": (
        "Enough free space ({free} free, about {need} needed).",
        "المساحة كافية (المتاح {free} والمطلوب قرابة {need}).",
        "",
        "",
    ),
    "DEVICE_STORAGE_FULL": (
        "Not enough free space: about {need} needed, {free} free.",
        "المساحة غير كافية: المطلوب قرابة {need} والمتاح {free}.",
        "Free up space on the phone.",
        "حرّر مساحة على الهاتف.",
    ),
    "INCOMPLETE": (
        "This library item is incomplete.",
        "عنصر المكتبة هذا غير مكتمل.",
        "Resume the extraction first.",
        "استأنف الاستخراج أولًا.",
    ),
}


def check(code: str, level: str, detail: str = "", **params) -> dict:
    en, ar, hint_en, hint_ar = CHECK_TEXT[code]
    fmt = {k: v for k, v in params.items()}
    return {
        "code": code,
        "level": level,
        "message": {"en": _fmt(en, fmt), "ar": _fmt(ar, fmt, isolate=True)},
        "hint": {"en": _fmt(hint_en, fmt), "ar": _fmt(hint_ar, fmt, isolate=True)},
        "detail": detail,
        "params": params,
    }


def _fmt(s: str, params: dict, isolate: bool = False) -> str:
    for k, v in params.items():
        # In Arabic text keep Latin values (versions, sizes) in their own LTR run.
        s = s.replace("{" + k + "}", f"\u2066{v}\u2069" if isolate else str(v))
    return s


def _human(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return str(n)


ABI_SPLIT_RE = re.compile(r"split_config\.(arm64_v8a|armeabi_v7a|armeabi|x86_64|x86|mips64|mips)\.apk$")


def item_abis(folder: Path, m: dict) -> set[str]:
    """ABIs the item carries native code for (from ABI splits, or lib/<abi>/ in the APKs)."""
    abis = set()
    for f in mf.apk_files(m):
        match = ABI_SPLIT_RE.search(f["path"])
        if match:
            abis.add(match.group(1).replace("_", "-"))
    if abis:
        return abis
    for f in mf.apk_files(m):
        try:
            with zipfile.ZipFile(long_path(Path(folder) / f["path"])) as zf:
                for name in zf.namelist():
                    if name.startswith("lib/") and name.count("/") >= 2:
                        abis.add(name.split("/")[1])
        except (OSError, zipfile.BadZipFile):
            continue
    return abis


def preflight(
    adb: Adb, folder: Path, m: dict, serial: str, device: dict, include_obb: bool = True, include_data: bool = True
) -> dict:
    checks: list[dict] = []
    confirm: list[str] = []
    package = m["package"]
    item_code = int(m.get("version_code") or 0)

    if not m.get("complete"):
        checks.append(check("INCOMPLETE", "error"))

    missing = [f["path"] for f in m["files"] if file_size(Path(folder) / f["path"]) != int(f["size"])]
    checks.append(check("FILE_MISSING", "error", "\n".join(missing[:20])) if missing else check("FILES_PRESENT", "ok"))

    signing = m.get("signing") or {}
    if signing.get("sha256"):
        if signing.get("consistent", True):
            checks.append(check("SPLITS_CONSISTENT", "ok", scheme=signing.get("scheme", "")))
        else:
            checks.append(check("SPLIT_SIGNATURE_MISMATCH", "error"))

    sdk = int(device.get("sdk") or 0)
    min_sdk = int(m.get("min_sdk") or 0)
    if sdk and min_sdk and sdk < min_sdk:
        checks.append(check("SDK_TOO_OLD", "error", device=sdk, min=min_sdk))
    target = int(m.get("target_sdk") or 0)
    if sdk >= 34 and 0 < target < 24:
        checks.append(check("LOW_TARGET_SDK", "info", target=target))

    dev_abis = [a.strip() for a in (device.get("abis") or device.get("abi") or "").split(",") if a.strip()]
    abis = item_abis(folder, m)
    if abis and dev_abis and not (abis & set(dev_abis)):
        checks.append(
            check("ABI_MISMATCH", "warning", item_abis=", ".join(sorted(abis)), device_abis=", ".join(dev_abis))
        )

    dump_text = adb.shell(serial, f"dumpsys package {rquote(package)}", timeout=60).out
    from .scanner import parse_dumpsys_packages

    installed = parse_dumpsys_packages(dump_text).get(package)
    installed_code = installed.version_code if installed else None
    relation = compare_versions(item_code, installed_code)
    vn_item = m.get("version_name") or str(item_code)
    vn_inst = (installed.version_name or str(installed_code)) if installed else ""
    if relation == "not_installed":
        checks.append(check("NOT_INSTALLED", "info"))
    elif relation == "upgrade":
        checks.append(check("UPGRADE", "ok", installed=vn_inst, item=vn_item))
    elif relation == "same":
        checks.append(check("SAME_VERSION", "info"))
    else:
        checks.append(check("DOWNGRADE", "warning", installed=vn_inst, item=vn_item))
        confirm.append("downgrade")

    if installed:
        inst_sigs = parse_installed_signatures(dump_text)
        ours = [h.lower() for h in signing.get("java_hash", [])]
        if not inst_sigs or not ours:
            checks.append(check("SIGNATURE_UNKNOWN", "info"))
        elif set(inst_sigs) & set(ours):
            checks.append(check("SIGNATURE_MATCH", "ok"))
        else:
            checks.append(check("SIGNATURE_MISMATCH", "warning", f"installed={inst_sigs} item={ours}"))
            confirm.append("signature")

    apk = sum(int(f["size"]) for f in m["files"] if f["kind"] == "apk")
    rest = sum(
        int(f["size"])
        for f in m["files"]
        if (f["kind"] == "obb" and include_obb) or (f["kind"] == "data" and include_data)
    )
    from .installer import APK_SPACE_FACTOR, SPACE_MARGIN

    need = int(apk * APK_SPACE_FACTOR) + rest + SPACE_MARGIN
    fs = free_space(adb, serial)
    if fs:
        if fs[0] < need:
            checks.append(check("DEVICE_STORAGE_FULL", "error", need=_human(need), free=_human(fs[0])))
        else:
            checks.append(check("SPACE_OK", "ok", need=_human(need), free=_human(fs[0])))

    return {
        "serial": serial,
        "device_label": device.get("label") or device.get("model") or serial,
        "checks": checks,
        "installed_version_code": installed_code,
        "installed_version_name": installed.version_name if installed else None,
        "can_install": not any(c["level"] == "error" for c in checks),
        "needs_confirmation": confirm,
    }


class VerifyJob:
    """Factory kept separate to avoid a circular import (jobs -> verify)."""

    @staticmethod
    def create(library, item_id: int):
        from .jobs import Job

        class _VerifyJob(Job):
            kind = "verify"

            def run(self_inner) -> None:
                folder = library.folder(item_id)
                m = mf.load(folder)
                self_inner.progress.set_total(mf.total_size(m), len(m["files"]))
                self_inner.set_phase("verify")
                job_verifier(folder, m, self_inner)
                sig = item_signing(folder, m)
                if not sig["consistent"]:
                    raise AppBridgeError("SPLIT_SIGNATURE_MISMATCH", str(sig["per_apk"]))
                self_inner.result = {"files": len(m["files"]), "signing": sig["sha256"]}

        row = library.item(item_id)
        job = _VerifyJob(title=row["display_name"], package=row["package"])
        job.item_id = item_id
        job.resumable = False
        return job
