import hashlib
import time

from apkfactory import make_cert, signed_apk, v1_apk
from cryptography.hazmat.primitives.serialization import Encoding
from test_extract import PKG, run_job
from test_install import add_target, dev_info, extracted

from appbridge import manifest as mf
from appbridge import verify
from appbridge.installer import InstallJob
from appbridge.verify import (
    SIG_V3_ID,
    apk_signing,
    compare_versions,
    item_signing,
    java_signature_hash,
    parse_installed_signatures,
    verify_files,
)


def test_java_signature_hash():
    assert java_signature_hash(bytes([1, 2, 3])) == format(((31 + 1) * 31 + 2) * 31 + 3, "x")
    assert java_signature_hash(bytes([255])) == format(31 - 1, "x")
    # wraps like a Java int and prints as unsigned hex
    assert len(java_signature_hash(b"\xff" * 100)) <= 8


def test_parse_installed_signatures():
    line = "    signatures=PackageSignatures{9fbbc6c version:3, signatures:[1b2c7b42, A1], past signatures:[]}"
    assert parse_installed_signatures(line) == ["1b2c7b42", "a1"]
    assert parse_installed_signatures("nothing") == []


def test_compare_versions():
    assert compare_versions(5, None) == "not_installed"
    assert compare_versions(5, 4) == "upgrade"
    assert compare_versions(5, 5) == "same"
    assert compare_versions(5, 6) == "downgrade"


def test_v2_v3_and_v1_signatures(tmp_path):
    key, cert = make_cert()
    der = cert.public_bytes(Encoding.DER)
    sha = hashlib.sha256(der).hexdigest()
    p2 = tmp_path / "v2.apk"
    p2.write_bytes(signed_apk(der))
    p3 = tmp_path / "v3.apk"
    p3.write_bytes(signed_apk(der, SIG_V3_ID))
    p1 = tmp_path / "v1.apk"
    p1.write_bytes(v1_apk(key, cert))
    for p, scheme in ((p2, "v2"), (p3, "v3"), (p1, "v1")):
        info = apk_signing(p)
        assert info.scheme == scheme, (p, info.error)
        assert info.certs_sha256 == [sha]
    # still a readable zip after inserting the signing block
    import zipfile

    assert zipfile.ZipFile(p2).read("classes.dex") == b"dex"


def test_unsigned_apk(tmp_path):
    import zipfile

    p = tmp_path / "u.apk"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("a", "b")
    assert apk_signing(p).scheme == "none"
    bad = tmp_path / "bad.apk"
    bad.write_bytes(b"not a zip")
    assert apk_signing(bad).scheme == "none"


def _item_with_apks(tmp_path, ders):
    folder = tmp_path / "item"
    (folder / "apk").mkdir(parents=True)
    m = mf.new_manifest("com.x")
    for i, der in enumerate(ders):
        name = "base.apk" if i == 0 else f"split_config.{i}.apk"
        data = signed_apk(der)
        (folder / "apk" / name).write_bytes(data)
        m["files"].append(
            mf.file_entry("apk", f"apk/{name}", f"/data/app/x/{name}", len(data), hashlib.sha256(data).hexdigest())
        )
    return folder, m


def test_split_consistency(tmp_path):
    _, c1 = make_cert("one")
    _, c2 = make_cert("two")
    d1, d2 = c1.public_bytes(Encoding.DER), c2.public_bytes(Encoding.DER)
    folder, m = _item_with_apks(tmp_path / "a", [d1, d1])
    s = item_signing(folder, m)
    assert s["consistent"] and s["scheme"] == "v2" and s["java_hash"] == [java_signature_hash(d1)]
    folder, m = _item_with_apks(tmp_path / "b", [d1, d2])
    assert not item_signing(folder, m)["consistent"]


def test_verify_files_detects_corruption(tmp_path):
    _, c = make_cert()
    folder, m = _item_with_apks(tmp_path, [c.public_bytes(Encoding.DER)])
    assert verify_files(folder, m) == []
    p = folder / "apk" / "base.apk"
    data = bytearray(p.read_bytes())
    data[10] ^= 0xFF
    p.write_bytes(bytes(data))
    (problem,) = verify_files(folder, m)
    assert problem.problem == "hash"
    p.unlink()
    assert verify_files(folder, m)[0].problem == "missing"


def test_preflight_downgrade_signature_sdk_space(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    folder = lib.folder(item_id)
    m = lib.manifest(item_id)
    m["signing"] = {"sha256": ["x"], "scheme": "v2", "consistent": True, "java_hash": ["1234abcd"]}
    m["min_sdk"] = 26
    t = add_target(adb, tmp_path, "T1", sdk=34)
    t.packages[PKG] = {
        "apks": ["/data/app/x/base.apk"],
        "version_code": 2099999999,
        "version_name": "9.9",
        "sigs": ["deadbeef"],
    }
    res = verify.preflight(adb, folder, m, "T1", {**dev_info(t), "abis": "arm64-v8a"})
    codes = {c["code"]: c["level"] for c in res["checks"]}
    assert codes["DOWNGRADE"] == "warning"
    assert codes["SIGNATURE_MISMATCH"] == "warning"
    assert codes["SPACE_OK"] == "ok"
    assert res["needs_confirmation"] == ["downgrade", "signature"]
    assert res["can_install"]
    assert "9.9" in res["checks"][[c["code"] for c in res["checks"]].index("DOWNGRADE")]["message"]["ar"]

    old = add_target(adb, tmp_path, "T2", sdk=23)
    old.free_kb = 1
    res = verify.preflight(adb, folder, m, "T2", {**dev_info(old), "abis": "x86"})
    codes = {c["code"]: c["level"] for c in res["checks"]}
    assert codes["SDK_TOO_OLD"] == "error"
    assert codes["DEVICE_STORAGE_FULL"] == "error"
    assert codes["ABI_MISMATCH"] == "warning"
    assert codes["NOT_INSTALLED"] == "info"
    assert not res["can_install"]

    t.packages[PKG]["sigs"] = ["1234abcd"]
    t.packages[PKG]["version_code"] = 1
    res = verify.preflight(adb, folder, m, "T1", dev_info(t))
    codes = {c["code"] for c in res["checks"]}
    assert {"SIGNATURE_MATCH", "UPGRADE"} <= codes


def test_install_refuses_corrupted_files(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    t = add_target(adb, tmp_path, "T1")
    obb = next((lib.folder(item_id) / "obb").iterdir())
    obb.write_bytes(b"X" * obb.stat().st_size)
    job = run_job(jm, InstallJob(adb, lib, item_id, "T1", dev_info(t), verifier=verify.job_verifier))
    assert job.state == "failed" and job.error["code"] == "HASH_MISMATCH"
    assert t.installed == []


def test_verify_job(tmp_path):
    adb, lib, jm, item_id = extracted(tmp_path)
    job = jm.submit(verify.VerifyJob.create(lib, item_id))
    job = jm.wait(job.id)
    assert job.state == "completed", job.error
    time.sleep(0)
