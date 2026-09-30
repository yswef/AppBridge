from fakeadb import FakeAdb, FakeDevice

from appbridge.devices import DeviceInfo, DeviceMonitor, assign_labels


def test_assign_labels_same_model():
    infos = [
        DeviceInfo("AAAA1111", "device", model="SM-A515F"),
        DeviceInfo("BBBB2222", "device", model="SM-A515F"),
        DeviceInfo("CCCC", "device", model="Pixel 7"),
    ]
    assign_labels(infos)
    assert infos[0].label == "SM-A515F (…1111)"
    assert infos[1].label == "SM-A515F (…2222)"
    assert infos[2].label == "Pixel 7"


def test_monitor_poll(tmp_path):
    adb = FakeAdb()
    adb.add(FakeDevice("S1", tmp_path / "s1", model="Pixel 7", sdk=34))
    adb.add(FakeDevice("S2", tmp_path / "s2", state="unauthorized"))
    mon = DeviceMonitor(adb)
    assert mon.poll_once() is True
    s1 = mon.get("S1")
    assert s1.android_version == "14" and s1.sdk == 34
    assert s1.free_bytes == 50_000_000 * 1024
    assert mon.get("S2").state == "unauthorized"
    assert mon.poll_once() is False
    del adb.devices_map["S2"]
    assert mon.poll_once() is True
    assert mon.get("S2") is None
