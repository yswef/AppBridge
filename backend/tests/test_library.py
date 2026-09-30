import pytest

from appbridge import manifest as mf
from appbridge.errors import AppBridgeError
from appbridge.library import Library


def _item(lib, pkg="com.x", vc=5, complete=True):
    folder = lib.new_folder(pkg, vc)
    (folder / "apk").mkdir()
    (folder / "apk" / "base.apk").write_bytes(b"x" * 10)
    m = mf.new_manifest(pkg)
    m.update(version_code=vc, version_name="1.0", label="X App", complete=complete)
    m["files"] = [mf.file_entry("apk", "apk/base.apk", "/data/app/x/base.apk", 10, "ab")]
    return lib.save_manifest(folder, m), folder


def test_library_crud(tmp_path):
    lib = Library(tmp_path / "lib")
    item_id, folder = _item(lib)
    assert folder.name == "com.x-5"
    items = lib.list()
    assert items[0]["display_name"] == "X App"
    assert items[0]["size"] == 10
    lib.rename(item_id, "لعبتي")
    assert lib.item(item_id)["display_name"] == "لعبتي"
    assert mf.load(folder)["display_name"] == "لعبتي"
    assert lib.packages() == {"com.x": 5}
    lib.delete(item_id)
    assert lib.list() == [] and not folder.exists()


def test_reconcile_picks_up_copied_folders(tmp_path):
    lib = Library(tmp_path / "lib")
    _, folder = _item(lib)
    lib.close()
    (tmp_path / "lib" / "library.db").unlink()
    lib2 = Library(tmp_path / "lib")
    assert len(lib2.list()) == 1
    import shutil

    shutil.rmtree(folder)
    lib2.reconcile()
    assert lib2.list() == []


def test_unique_folders(tmp_path):
    lib = Library(tmp_path / "lib")
    a = lib.new_folder("com.x", 1)
    b = lib.new_folder("com.x", 1)
    assert a != b


def test_manifest_validation_rejects_traversal():
    m = mf.new_manifest("com.x")
    m["files"] = [mf.file_entry("apk", "apk/../../evil.exe", "/x", 1)]
    with pytest.raises(AppBridgeError):
        mf.validate(m)
    m["files"] = [mf.file_entry("obb", "apk/base.apk", "/x", 1)]
    with pytest.raises(AppBridgeError):
        mf.validate(m)
