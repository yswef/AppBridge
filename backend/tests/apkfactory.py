"""Build tiny signed-looking APKs for tests (real zip + APK Signing Block / v1 PKCS#7 with a real cert)."""

from __future__ import annotations

import datetime
import io
import struct
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from appbridge.verify import SIG_V2_ID, SIG_V3_ID


def make_cert(cn: str = "AppBridge Test"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _lp(b: bytes) -> bytes:
    return struct.pack("<I", len(b)) + b


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for k, v in entries.items():
            zf.writestr(k, v)
    return buf.getvalue()


def signed_apk(cert_der: bytes, scheme_id: int = SIG_V2_ID, entries: dict[str, bytes] | None = None) -> bytes:
    data = _zip_bytes(entries or {"AndroidManifest.xml": b"manifest", "classes.dex": b"dex"})
    eocd = data.rfind(b"PK\x05\x06")
    cd = struct.unpack_from("<I", data, eocd + 16)[0]
    signed_data = _lp(_lp(b"")) + _lp(_lp(cert_der)) + _lp(b"")  # digests, certificates, attributes
    if scheme_id == SIG_V3_ID:
        signed_data += struct.pack("<II", 24, 0x7FFFFFFF)
    signer = _lp(signed_data) + _lp(b"") + _lp(b"pubkey")
    value = _lp(_lp(signer))
    pair = struct.pack("<Q", len(value) + 4) + struct.pack("<I", scheme_id) + value
    size = len(pair) + 8 + 16
    block = struct.pack("<Q", size) + pair + struct.pack("<Q", size) + b"APK Sig Block 42"
    out = bytearray(data[:cd] + block + data[cd:])
    new_eocd = eocd + len(block)
    struct.pack_into("<I", out, new_eocd + 16, cd + len(block))
    return bytes(out)


def v1_apk(key, cert) -> bytes:
    sig = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(b"Signature-Version: 1.0\r\n")
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
    )
    return _zip_bytes({"AndroidManifest.xml": b"m", "META-INF/CERT.SF": b"sf", "META-INF/CERT.RSA": sig})
