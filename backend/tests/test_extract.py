import hashlib
import json
import time

import pytest
from fakeadb import FakeAdb, FakeDevice

from appbridge import extractor
from appbridge.extractor import ExtractJob
from appbridge.jobs import JobManager
from appbridge.library import Library

PKG = "com.dts.freefireth"
APK_DIR = "/data/app/~~ab==/com.dts.freefireth-1=="


def make_phone(tmp_path, serial="S1"):
    adb = FakeAdb()
    dev = adb.add(FakeDevice(serial, tmp_path / f"phone-{serial}"))
    dev.add_file(f"{APK_DIR}/base.apk", b"A" * 5000)
    dev.add_file(f"{APK_DIR}/split_config.arm64_v8a.apk", b"B" * 3000)
    dev.add_file(f"/sdcard/Android/obb/{PKG}/main.2019117233.{PKG}.obb", b"O" * 20000)
    dev.add_file(
        f"/sdcard/Android/data/{PKG}/files/contentcache/Optional/android/gameassetbundles/a.unity3d", b"D1" * 100
    )
    dev.add_file(f"/sdcard/Android/data/{PKG}/files/contentcache/b.bin", b"D2" * 50)
    dev.add_file(f"/sdcard/Android/data/{PKG}/files/ملف عربي.txt", "مرحبا".encode())
    dev.packages[PKG] = {
        "apks": [f"{APK_DIR}/base.apk", f"{APK_DIR}/split_config.arm64_v8a.apk"],
        "version_code": 2019117233,
        "version_name": "1.104.1",
    }
    return adb, dev


def run_job(jm, job, timeout=30):
    jm.submit(job)
    return jm.wait(job.id, timeout)


def test_full_extract_into_arabic_library_path(tmp_path):
    adb, dev = make_phone(tmp_path)
    lib = Library(tmp_path / "مكتبة التطبيقات")
    jm = JobManager()
    job = run_job(jm, ExtractJob(adb, lib, "S1", PKG, device_info={"model": "Pixel 7"}))
    assert job.state == "completed", job.error
    items = lib.list()
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "complete"
    assert item["has_obb"] and item["has_data"]
    assert item["apk_count"] == 2
    m = lib.manifest(item["id"])
    kinds = sorted({f["kind"] for f in m["files"]})
    assert kinds == ["apk", "data", "obb"]
    for f in m["files"]:
        local = lib.folder(item["id"]) / f["path"]
        assert hashlib.sha256(local.read_bytes()).hexdigest() == f["sha256"]
        assert f["remote"].startswith("/")
    assert "data/files/ملف عربي.txt" in {f["path"] for f in m["files"]}
    assert m["remote_roots"]["apk"] == APK_DIR
    assert "internal_data_not_included" in m["notes"]
    assert job.progress.done == job.progress.total > 0
    assert not (lib.folder(item["id"]) / ".appbridge-state.json").exists()
    assert json.loads((lib.folder(item["id"]) / "manifest.json").read_text(encoding="utf-8"))["complete"] is True


def test_resume_after_cable_disconnect(tmp_path, monkeypatch):
    adb, dev = make_phone(tmp_path)
    lib = Library(tmp_path / "lib")
    jm = JobManager()
    dev.fail_after_pulls = 2  # device drops after two pull calls
    job = ExtractJob(adb, lib, "S1", PKG)
    jm.submit(job)
    for _ in range(100):
        if job.state == "waiting_device":
            break
        time.sleep(0.05)
    assert job.state == "waiting_device"
    first_pulls = list(adb.pulled)
    dev.fail_after_pulls = None
    dev.state = "device"
    job = jm.wait(job.id, 30)
    assert job.state == "completed", job.error
    # the files pulled before the disconnect were not pulled again
    for r in first_pulls:
        assert adb.pulled.count(r) == 1


def test_data_access_denied_then_skip(tmp_path):
    adb, dev = make_phone(tmp_path)
    dev.deny_data_read = True
    lib = Library(tmp_path / "lib")
    jm = JobManager()
    job = ExtractJob(adb, lib, "S1", PKG)
    jm.submit(job)
    for _ in range(100):
        if job.state == "needs_decision":
            break
        time.sleep(0.02)
    assert job.decision["code"] == "DATA_ACCESS_DENIED"
    assert "skip_data" in job.decision["options"]
    jm.decide(job.id, "skip_data")
    job = jm.wait(job.id)
    assert job.state == "completed"
    item = lib.list()[0]
    assert not item["has_data"] and item["has_obb"]
    assert "external_data_skipped" in item["notes"]
    assert any(w["code"] == "DATA_ACCESS_DENIED" for w in job.warnings)


def test_pause_and_resume_does_not_recopy(tmp_path):
    adb, dev = make_phone(tmp_path)
    adb.pull_delay = 0.15
    lib = Library(tmp_path / "lib")
    jm = JobManager()
    job = ExtractJob(adb, lib, "S1", PKG)
    jm.submit(job)
    for _ in range(200):
        if len(adb.pulled) >= 2:
            break
        time.sleep(0.01)
    jm.pause(job.id)
    job = jm.wait(job.id)
    assert job.state == "paused"
    assert lib.list()[0]["status"] == "incomplete"
    before = list(adb.pulled)
    adb.pull_delay = 0
    jm.resume(job.id)
    job = jm.wait(job.id)
    assert job.state == "completed", job.error
    # everything finished before the pause (all but the in-flight pull) is not pulled again
    for r in before[:-1]:
        assert adb.pulled.count(r) == 1


def test_new_job_resumes_incomplete_item(tmp_path):
    adb, dev = make_phone(tmp_path)
    adb.pull_delay = 0.1
    lib = Library(tmp_path / "lib")
    jm = JobManager()
    job = ExtractJob(adb, lib, "S1", PKG)
    jm.submit(job)
    while len(adb.pulled) < 2:
        time.sleep(0.01)
    jm.cancel(job.id)
    assert jm.wait(job.id).state == "cancelled"
    adb.pull_delay = 0
    job2 = run_job(jm, ExtractJob(adb, lib, "S1", PKG))
    assert job2.state == "completed"
    assert len(lib.list()) == 1  # same folder reused


def test_pc_disk_full(tmp_path, monkeypatch):
    adb, dev = make_phone(tmp_path)
    monkeypatch.setattr(extractor, "free_bytes", lambda p: 1000)
    lib = Library(tmp_path / "lib")
    job = run_job(JobManager(), ExtractJob(adb, lib, "S1", PKG))
    assert job.state == "failed"
    assert job.error["code"] == "PC_DISK_FULL"


def test_package_not_found(tmp_path):
    adb, dev = make_phone(tmp_path)
    lib = Library(tmp_path / "lib")
    job = run_job(JobManager(), ExtractJob(adb, lib, "S1", "com.not.there"))
    assert job.state == "failed" and job.error["code"] == "PACKAGE_NOT_FOUND"


@pytest.mark.parametrize("include_data", [False])
def test_without_data(tmp_path, include_data):
    adb, dev = make_phone(tmp_path)
    lib = Library(tmp_path / "lib")
    job = run_job(JobManager(), ExtractJob(adb, lib, "S1", PKG, include_data=include_data))
    assert job.state == "completed"
    assert not lib.list()[0]["has_data"]
