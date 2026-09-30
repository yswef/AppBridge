import pytest

from appbridge import errors


@pytest.mark.parametrize(
    "text,code",
    [
        (
            "Failure [INSTALL_FAILED_VERSION_DOWNGRADE: Downgrade detected: Update version code 1 is older]",
            "INSTALL_FAILED_VERSION_DOWNGRADE",
        ),
        (
            "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.x signatures do not match]",
            "INSTALL_FAILED_UPDATE_INCOMPATIBLE",
        ),
        ("Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]", "INSTALL_FAILED_INSUFFICIENT_STORAGE"),
        (
            "Failure [INSTALL_FAILED_DEPRECATED_SDK_VERSION: App package must target at least SDK version 23]",
            "INSTALL_FAILED_DEPRECATED_SDK_VERSION",
        ),
        (
            "Failure [INSTALL_FAILED_NO_MATCHING_ABIS: INSTALL_FAILED_NO_MATCHING_ABIS]",
            "INSTALL_FAILED_NO_MATCHING_ABIS",
        ),
        ("adb: error: failed to copy 'a' to 'b': remote No space left on device", "DEVICE_STORAGE_FULL"),
        ("adb: device offline", "DEVICE_OFFLINE"),
        ("adb: error: device 'R58' not found", "DEVICE_NOT_FOUND"),
        ("error: device unauthorized.\nThis adb server's $ADB_VENDOR_KEYS is not set", "DEVICE_UNAUTHORIZED"),
        ("Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]", "INSTALL_FAILED_USER_RESTRICTED"),
        ("Failure [INSTALL_FAILED_WEIRD_NEW_THING]", "INSTALL_FAILED"),
        ("everything fine", "UNKNOWN"),
    ],
)
def test_classify(text, code):
    assert errors.classify(text) == code


def test_every_code_has_both_languages():
    for code, msg in errors.MESSAGES.items():
        assert msg.en and msg.ar, code
        assert bool(msg.hint_en) == bool(msg.hint_ar), code


def test_every_rule_code_has_message():
    for rule in errors._RULES:
        assert rule.code in errors.MESSAGES


def test_describe_and_disk_full():
    d = errors.from_exception(OSError(28, "No space left on device"))
    assert d["code"] == "PC_DISK_FULL"
    assert d["message"]["ar"]
    assert errors.from_exception(errors.DeviceGoneError("x"))["code"] == "DEVICE_DISCONNECTED"
