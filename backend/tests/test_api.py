import time

from fakeadb import FakeAdb
from test_extract import PKG, make_phone

from appbridge.api import Api
from appbridge.settings import SettingsStore


def make_api(tmp_path, adb: FakeAdb) -> Api:
    store = SettingsStore(tmp_path / "settings.json")
    store.update({"library_dir": str(tmp_path / "Library")})
    api = Api(adb=adb, settings=store, start_monitor=False)
    api._monitor.poll_once()
    return api


def test_api_flow(tmp_path):
    adb, dev = make_phone(tmp_path)
    api = make_api(tmp_path, adb)
    r = api.list_devices()
    assert r["ok"] and r["data"]["devices"][0]["serial"] == "S1"
    apps = api.list_apps("S1")["data"]
    assert any(a["package"] == PKG and not a["in_library"] for a in apps)
    job = api.start_extract("S1", PKG, {"include_data": True})["data"]
    for _ in range(200):
        j = next(x for x in api.list_jobs()["data"] if x["id"] == job["id"])
        if j["state"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert j["state"] == "completed", j["error"]
    lib = api.library_list()["data"]
    assert len(lib["items"]) == 1
    apps = api.list_apps("S1")["data"]
    assert next(a for a in apps if a["package"] == PKG)["in_library"]
    item_id = lib["items"][0]["id"]
    assert api.library_rename(item_id, "فري فاير")["data"]["display_name"] == "فري فاير"
    assert api.library_delete(item_id)["ok"]
    assert api.library_list()["data"]["items"] == []


def test_api_errors_are_translated(tmp_path):
    adb = FakeAdb()
    api = make_api(tmp_path, adb)
    r = api.list_apps("NOPE")
    assert r["ok"] is False
    assert r["error"]["code"] == "DEVICE_NOT_FOUND"
    assert r["error"]["message"]["ar"]


def test_update_settings_validates(tmp_path):
    api = make_api(tmp_path, FakeAdb())
    assert api.update_settings({"theme": "dark"})["data"]["theme"] == "dark"
    assert api.update_settings({"split_size_mb": "big"})["ok"] is False
