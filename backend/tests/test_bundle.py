import json
import zipfile

import pytest
from test_extract import PKG
from test_install import extracted

from appbridge import manifest as mf
from appbridge.bundle import (
    ExportJob,
    ImportJob,
    PartReader,
    PartWriter,
    default_bundle_name,
    install_bat,
    resolve_parts,
    should_store,
)
from appbridge.errors import AppBridgeError
from appbridge.library import Library


def test_should_store():
    assert should_store("apk/base.apk", b"")
    assert should_store("obb/main.obb", b"x" * 1000)
    assert not should_store("data/files/config.json", b'{"a": 1}' * 200)
    import os

    assert should_store("data/files/blob.bin", os.urandom(4096))


def test_part_writer_reader_roundtrip(tmp_path):
    data = bytes(range(256)) * 1000
    w = PartWriter(tmp_path / "x.appbridge", 10_000)
    w.write(data[:5])
    w.write(data[5:])
    w.close()
    assert len(w.parts) == 26
    r = PartReader(resolve_parts(tmp_path / "x.appbridge.007"))
    assert r.read() == data
    r.seek(12_345)
    assert r.read(100) == data[12_345:12_445]
    r.close()


def _export(lib, jm, item_id, dest, split_mb=0):
    job = jm.submit(ExportJob(lib, item_id, dest, split_mb))
    job = jm.wait(job.id)
    assert job.state == "completed", job.error
    return job


def _import(lib, jm, path):
    job = jm.submit(ImportJob(lib, path))
    return jm.wait(job.id)


def test_export_import_roundtrip(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    src_manifest = lib.manifest(item_id)
    dest = tmp_path / "out" / "لعبة.appbridge"
    dest.parent.mkdir()
    job = _export(lib, jm, item_id, dest)
    assert job.result["files"] == [str(dest)]
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "Install.bat", "README.txt"} <= names
        info = zf.getinfo(next(f["path"] for f in src_manifest["files"] if f["kind"] == "apk"))
        assert info.compress_type == zipfile.ZIP_STORED
        assert json.loads(zf.read("manifest.json"))["package"] == PKG

    other = Library(tmp_path / "friend-pc")
    job = _import(other, jm, dest)
    assert job.state == "completed", job.error
    items = other.list()
    assert len(items) == 1 and items[0]["status"] == "complete"
    m = other.manifest(items[0]["id"])
    assert [f["sha256"] for f in m["files"]] == [f["sha256"] for f in src_manifest["files"]]
    folder = other.folder(items[0]["id"])
    for f in m["files"]:
        assert (folder / f["path"]).stat().st_size == f["size"]


def test_split_export_and_import_from_any_part(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    job = jm.submit(ExportJob(lib, item_id, tmp_path / "game.appbridge", 0))
    job.split_size = 7000  # tiny parts for the test
    job = jm.wait(job.id)
    assert job.state == "completed", job.error
    parts = job.result["files"]
    assert len(parts) > 2 and parts[0].endswith(".appbridge.001")
    other = Library(tmp_path / "friend")
    assert _import(other, jm, parts[1]).state == "completed"
    assert len(other.list()) == 1


def test_import_rejects_missing_part(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    job = jm.submit(ExportJob(lib, item_id, tmp_path / "g.appbridge", 0))
    job.split_size = 7000
    parts = jm.wait(job.id).result["files"]
    import os

    os.remove(parts[-1])
    other = Library(tmp_path / "friend")
    job = _import(other, jm, parts[0])
    assert job.state == "failed" and job.error["code"] == "INVALID_BUNDLE"
    assert other.list() == []


def _bundle_with(tmp_path, manifest: dict, files: dict[str, bytes]) -> str:
    p = tmp_path / "evil.appbridge"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for k, v in files.items():
            zf.writestr(k, v)
    return str(p)


def test_import_rejects_traversal_and_tampering(tmp_path):
    lib = Library(tmp_path / "lib")
    from appbridge.jobs import JobManager

    jm = JobManager()
    m = mf.new_manifest("com.x")
    m["complete"] = True
    m["files"] = [mf.file_entry("apk", "apk/../../../evil.exe", "/x", 3)]
    job = _import(lib, jm, _bundle_with(tmp_path, m, {"apk/../../../evil.exe": b"bad"}))
    assert job.state == "failed" and job.error["code"] == "INVALID_BUNDLE"
    assert not (tmp_path / "evil.exe").exists()

    m["files"] = [mf.file_entry("apk", "apk/base.apk", "/x", 3, "0" * 64)]
    job = _import(lib, jm, _bundle_with(tmp_path, m, {"apk/base.apk": b"abc"}))
    assert job.state == "failed" and job.error["code"] == "HASH_MISMATCH"
    assert lib.list() == []

    (tmp_path / "junk.appbridge").write_bytes(b"junk")
    assert _import(lib, jm, tmp_path / "junk.appbridge").error["code"] == "INVALID_BUNDLE"


def test_install_bat():
    m = mf.new_manifest("com.dts.freefireth")
    m["files"] = [mf.file_entry("apk", "apk/base.apk", "/x", 1), mf.file_entry("obb", "obb/main.obb", "/y", 1)]
    bat = install_bat(m)
    assert "install-multiple -r" in bat
    assert "/sdcard/Android/obb/com.dts.freefireth/" in bat
    assert "Android/data" not in bat
    bat.encode("ascii")
    m["package"] = "com.x & del *"
    with pytest.raises(AppBridgeError):
        install_bat(m)


def test_default_bundle_name():
    assert default_bundle_name({"display_name": "Free Fire: MAX", "package": "p", "version_name": "1.104.1"}) == (
        "Free Fire_ MAX 1.104.1.appbridge"
    )
