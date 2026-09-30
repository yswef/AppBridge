import time

from fakeadb import FakeDevice
from test_extract import PKG, make_phone, run_job

from appbridge.extractor import ExtractJob
from appbridge.installer import InstallJob
from appbridge.jobs import JobManager
from appbridge.library import Library


def extracted(tmp_path):
    adb, src = make_phone(tmp_path, "SRC")
    lib = Library(tmp_path / "lib")
    jm = JobManager()
    job = run_job(jm, ExtractJob(adb, lib, "SRC", PKG))
    assert job.state == "completed"
    return adb, lib, jm, lib.list()[0]["id"]


def add_target(adb, tmp_path, serial, sdk=34):
    return adb.add(FakeDevice(serial, tmp_path / f"phone-{serial}", model=f"Phone {serial}", sdk=sdk))


def dev_info(dev):
    return {"label": dev.model, "model": dev.model, "sdk": dev.sdk}


def test_install_single_phone(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1")
    job = run_job(jm, InstallJob(adb, lib, item_id, "T1", dev_info(t)))
    assert job.state == "completed", job.error
    ((apks, flags),) = t.installed
    assert [a.rsplit("/", 1)[-1] for a in apks][0] == "base.apk"
    assert len(apks) == 2 and flags == ["-r"]
    obb = t.local(f"/sdcard/Android/obb/{PKG}/main.2019117233.{PKG}.obb")
    assert obb.read_bytes() == b"O" * 20000
    data = t.local(f"/sdcard/Android/data/{PKG}/files/ملف عربي.txt")
    assert data.read_text(encoding="utf-8") == "مرحبا"
    assert job.progress.done == job.progress.total


def test_install_on_several_phones_failure_is_isolated(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    ok1 = add_target(adb, tmp_path, "T1")
    bad = add_target(adb, tmp_path, "T2")
    ok2 = add_target(adb, tmp_path, "T3", sdk=30)
    bad.install_failures = ["INSTALL_FAILED_NO_MATCHING_ABIS: Failed to extract native libraries"]
    jobs = [jm.submit(InstallJob(adb, lib, item_id, d.serial, dev_info(d))) for d in (ok1, bad, ok2)]
    states = {j.serial: jm.wait(j.id).state for j in jobs}
    assert states == {"T1": "completed", "T2": "failed", "T3": "completed"}
    assert jm.get(jobs[1].id).error["code"] == "INSTALL_FAILED_NO_MATCHING_ABIS"
    assert jm.get(jobs[1].id).error["message"]["ar"]


def test_android14_low_target_sdk_bypass(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1", sdk=34)
    t.install_failures = ["INSTALL_FAILED_DEPRECATED_SDK_VERSION: App package must target at least SDK version 23"]
    job = run_job(jm, InstallJob(adb, lib, item_id, "T1", dev_info(t)))
    assert job.state == "completed"
    assert "--bypass-low-target-sdk-block" in t.installed[-1][1]


def test_downgrade_asks_then_uninstalls(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1")
    t.packages[PKG] = {"apks": ["/data/app/x/base.apk"], "version_code": 2099999999}
    t.install_failures = ["INSTALL_FAILED_VERSION_DOWNGRADE: Downgrade detected"]
    job = jm.submit(InstallJob(adb, lib, item_id, "T1", dev_info(t)))
    for _ in range(200):
        if job.state == "needs_decision":
            break
        time.sleep(0.02)
    assert job.decision["code"] == "INSTALL_FAILED_VERSION_DOWNGRADE"
    jm.decide(job.id, "uninstall_first")
    assert jm.wait(job.id).state == "completed"
    assert PKG not in t.packages or t.packages[PKG].get("version_code") != 2099999999


def test_data_write_denied_launches_app_once(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1")
    t.deny_data_write = True
    job = InstallJob(adb, lib, item_id, "T1", dev_info(t))
    job.launch_wait_seconds = 0
    job = run_job(jm, job)
    assert job.state == "completed", job.error
    assert t.launched == [PKG]
    assert t.local(f"/sdcard/Android/data/{PKG}/files/contentcache/b.bin").exists()


def test_device_storage_full(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1")
    t.free_kb = 10
    job = run_job(jm, InstallJob(adb, lib, item_id, "T1", dev_info(t)))
    assert job.state == "failed" and job.error["code"] == "DEVICE_STORAGE_FULL"
    assert t.installed == []


def test_push_skips_files_already_on_phone(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1")
    t.add_file(f"/sdcard/Android/obb/{PKG}/main.2019117233.{PKG}.obb", b"O" * 20000)
    adb.pushed = []
    job = run_job(jm, InstallJob(adb, lib, item_id, "T1", dev_info(t)))
    assert job.state == "completed"
    assert not any(p.endswith(".obb") for p in adb.pushed)
