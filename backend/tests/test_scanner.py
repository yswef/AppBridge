from fakeadb import FakeAdb, FakeDevice

from appbridge.scanner import (
    list_apps,
    list_remote_files,
    looks_like_game,
    parse_du,
    parse_dumpsys_packages,
    parse_pm_list,
    parse_pm_path,
)


def test_parse_pm_list(fixture_text):
    lines = parse_pm_list(fixture_text("pm_list.txt"))
    assert lines[0].package == "com.dts.freefireth"
    assert lines[0].apk_path == "/data/app/~~Qx1a2b==/com.dts.freefireth-AbCd12==/base.apk"
    assert lines[0].uid == 10245
    # '=' inside the path: the package is after the LAST '='
    assert lines[2].package == "com.example.weird"
    assert lines[2].apk_path == "/data/app/~~k==/com.example.my=app-1==/base.apk"
    assert lines[3].package == "com.android.settings"


def test_parse_pm_path():
    out = "package:/data/app/x/base.apk\npackage:/data/app/x/split_config.arm64_v8a.apk\n\n"
    assert parse_pm_path(out) == ["/data/app/x/base.apk", "/data/app/x/split_config.arm64_v8a.apk"]


def test_parse_dumpsys(fixture_text):
    d = parse_dumpsys_packages(fixture_text("dumpsys_packages.txt"))
    ff = d["com.dts.freefireth"]
    assert ff.version_code == 2019117233
    assert ff.version_name == "1.104.1"
    assert ff.target_sdk == 33 and ff.min_sdk == 21
    assert "LARGE_HEAP" in ff.flags
    # hidden system package must not override the active one
    assert d["com.android.settings"].version_name == "14"
    assert "SYSTEM" in d["com.android.settings"].flags


def test_parse_du():
    assert parse_du("1024\t/sdcard/Android/obb/com.x\n12 /a b/\nbad\n") == {
        "/sdcard/Android/obb/com.x": 1048576,
        "/a b": 12288,
    }


def test_game_heuristic():
    assert looks_like_game("com.dts.freefireth", False, [])
    assert looks_like_game("com.some.app", True, [])
    assert not looks_like_game("com.whatsapp", False, [])


def _device(tmp_path):
    adb = FakeAdb()
    dev = adb.add(FakeDevice("S1", tmp_path / "phone"))
    apk_dir = "/data/app/~~ab==/com.dts.freefireth-1=="
    dev.add_file(f"{apk_dir}/base.apk", b"A" * 5000)
    dev.add_file(f"{apk_dir}/split_config.arm64_v8a.apk", b"B" * 3000)
    dev.add_file("/sdcard/Android/obb/com.dts.freefireth/main.2019117233.com.dts.freefireth.obb", b"O" * 10000)
    dev.packages["com.dts.freefireth"] = {
        "apks": [f"{apk_dir}/base.apk", f"{apk_dir}/split_config.arm64_v8a.apk"],
        "version_code": 2019117233,
        "version_name": "1.104.1",
    }
    dev.add_file("/data/app/~~cd==/com.whatsapp-1==/base.apk", b"W" * 2000)
    dev.packages["com.whatsapp"] = {"apks": ["/data/app/~~cd==/com.whatsapp-1==/base.apk"]}
    return adb, dev


def test_list_apps(tmp_path):
    adb, _ = _device(tmp_path)
    apps = {a.package: a for a in list_apps(adb, "S1")}
    ff = apps["com.dts.freefireth"]
    assert ff.game and not ff.system
    assert ff.obb_bytes >= 9 * 1024
    assert ff.version_code == 2019117233
    assert not apps["com.whatsapp"].game


def test_list_remote_files_missing_and_denied(tmp_path):
    adb, dev = _device(tmp_path)
    files, err = list_remote_files(adb, "S1", "/sdcard/Android/obb/com.dts.freefireth")
    assert err is None and len(files) == 1 and files[0].size == 10000
    files, err = list_remote_files(adb, "S1", "/sdcard/Android/obb/nothing")
    assert files == [] and err is None
    dev.add_file("/sdcard/Android/data/com.dts.freefireth/files/a.bin", b"x")
    dev.deny_data_read = True
    files, err = list_remote_files(adb, "S1", "/sdcard/Android/data/com.dts.freefireth")
    assert err and "Permission denied" in err
