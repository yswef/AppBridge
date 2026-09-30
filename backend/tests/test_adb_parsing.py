from appbridge.adb import parse_devices, parse_df, parse_getprop, parse_stat_lines, rquote


def test_parse_devices(fixture_text):
    devs = parse_devices(fixture_text("devices_l.txt"))
    assert [d.serial for d in devs] == ["R58M12ABCDE", "8A7Y0CXYZ", "emulator-5554", "ZY22ABCD12", "0123456789ABCDEF"]
    assert devs[0].state == "device"
    assert devs[0].props["model"] == "SM_A515F"
    assert devs[1].state == "unauthorized"
    assert devs[2].state == "offline"
    assert devs[3].props["usb"] == "2-1.4"
    assert devs[4].state == "no permissions"


def test_parse_devices_empty():
    assert parse_devices("List of devices attached\n\n") == []


def test_parse_getprop(fixture_text):
    props = parse_getprop(fixture_text("getprop.txt"))
    assert props["ro.build.version.sdk"] == "34"
    assert props["ro.product.model"] == "SM-A515F"
    assert props["ro.empty"] == ""


def test_parse_df(fixture_text):
    (e,) = parse_df(fixture_text("df_data.txt"))
    assert e.avail_kb == 35111104
    assert e.mount == "/data"


def test_parse_df_wrapped(fixture_text):
    (e,) = parse_df(fixture_text("df_wrapped.txt"))
    assert e.total_kb == 61237248
    assert e.mount == "/storage/emulated"


def test_parse_stat_lines():
    out = "123|1700000000|/sdcard/Android/obb/x/main.1.x.obb\nbad line\n5|1|/sdcard/a|b.txt\n"
    assert parse_stat_lines(out) == [(123, 1700000000, "/sdcard/Android/obb/x/main.1.x.obb"), (5, 1, "/sdcard/a|b.txt")]


def test_rquote_arabic_and_spaces():
    assert rquote("/sdcard/ملفات اللعبة/a b") == "'/sdcard/ملفات اللعبة/a b'"
    assert rquote("/sdcard/it's") == "'/sdcard/it'\"'\"'s'"
