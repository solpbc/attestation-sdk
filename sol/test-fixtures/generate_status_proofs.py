#!/usr/bin/env python3
"""Generate the synthetic PKI and signed OCSP fixtures for status-proof tests.

The SDK verifies raw OCSP responses with OpenSSL. These fixtures are produced
independently, with the Python `cryptography` package (46.0.7, the version the
sealed engine's status worker uses) plus a small hand-written DER encoder for
the shapes its builder cannot express. Run with:

    uv run --with cryptography==46.0.7 python3 sol/test-fixtures/generate_status_proofs.py

Every key is freshly generated, so a rerun rewrites every file. The fixture
times are fixed; tests pass their own verification time.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import shutil

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import ocsp
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "nv-attestation-sdk-cpp/unit-tests/testdata/status_proofs"
)

# 2026-10-01T00:00:00Z. Tests verify relative to this instant.
T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
DAY = dt.timedelta(days=1)
NOT_BEFORE = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
NOT_AFTER = dt.datetime(2049, 12, 31, tzinfo=dt.timezone.utc)


def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP384R1())


def name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "sol pbc test"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def certificate(
    subject: str,
    subject_key,
    issuer_cert: x509.Certificate | None,
    issuer_key,
    *,
    ca: bool,
    ocsp_signing: bool = False,
    serial: int | None = None,
) -> x509.Certificate:
    issuer_name = name(subject) if issuer_cert is None else issuer_cert.subject
    builder = (
        x509.CertificateBuilder()
        .subject_name(name(subject))
        .issuer_name(issuer_name)
        .public_key(subject_key.public_key())
        .serial_number(serial if serial is not None else x509.random_serial_number())
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(subject_key.public_key()),
            critical=False,
        )
    )
    if ca:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    else:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    if ocsp_signing:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.OCSP_SIGNING]), critical=False
        )
    if issuer_cert is not None:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_cert.public_key()),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA384())


def pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def response(
    subject: x509.Certificate,
    issuer: x509.Certificate,
    responder: x509.Certificate,
    responder_key,
    *,
    status: ocsp.OCSPCertStatus = ocsp.OCSPCertStatus.GOOD,
    this_update: dt.datetime = T0,
    next_update: dt.datetime | None = T0 + DAY,
) -> bytes:
    builder = ocsp.OCSPResponseBuilder().add_response(
        cert=subject,
        issuer=issuer,
        algorithm=hashes.SHA1(),
        cert_status=status,
        this_update=this_update,
        next_update=next_update,
        revocation_time=T0 - DAY if status == ocsp.OCSPCertStatus.REVOKED else None,
        revocation_reason=(
            x509.ReasonFlags.key_compromise
            if status == ocsp.OCSPCertStatus.REVOKED
            else None
        ),
    )
    builder = builder.responder_id(ocsp.OCSPResponderEncoding.HASH, responder)
    if responder.subject != issuer.subject or responder.public_key() != issuer.public_key():
        builder = builder.certificates([responder])
    signed = builder.sign(responder_key, hashes.SHA384())
    return signed.public_bytes(serialization.Encoding.DER)


# A minimal DER encoder for the shapes cryptography's builder refuses to make.
def der_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + der_len(len(value)) + value


def seq(*items: bytes) -> bytes:
    return tlv(0x30, b"".join(items))


def octets(value: bytes) -> bytes:
    return tlv(0x04, value)


def integer(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big", signed=True)
    return tlv(0x02, raw)


def gentime(value: dt.datetime) -> bytes:
    return tlv(0x18, value.strftime("%Y%m%d%H%M%SZ").encode())


SHA1_ALG = seq(tlv(0x06, bytes.fromhex("2b0e03021a")), b"\x05\x00")
ECDSA_SHA384 = seq(tlv(0x06, bytes.fromhex("2a8648ce3d040303")))
OCSP_BASIC = tlv(0x06, bytes.fromhex("2b06010505073001 01".replace(" ", "")))


def cert_id(subject: x509.Certificate, issuer: x509.Certificate) -> bytes:
    issuer_name_hash = hashlib.sha1(issuer.subject.public_bytes()).digest()
    issuer_key = issuer.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    issuer_key_hash = hashlib.sha1(issuer_key).digest()
    return seq(
        SHA1_ALG,
        octets(issuer_name_hash),
        octets(issuer_key_hash),
        integer(subject.serial_number),
    )


def single_good(subject, issuer, this_update=T0, next_update=T0 + DAY) -> bytes:
    return seq(
        cert_id(subject, issuer),
        tlv(0x80, b""),  # [0] IMPLICIT NULL: good
        gentime(this_update),
        tlv(0xA0, gentime(next_update)),
    )


def manual_response(singles: list[bytes], responder, responder_key) -> bytes:
    responder_key_hash = hashlib.sha1(
        responder.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).digest()
    tbs = seq(
        tlv(0xA2, octets(responder_key_hash)),  # responderID byKey
        gentime(T0),
        seq(*singles),
    )
    signature = responder_key.sign(tbs, ec.ECDSA(hashes.SHA384()))
    basic = seq(
        tbs,
        ECDSA_SHA384,
        tlv(0x03, b"\x00" + signature),
        tlv(0xA0, seq(responder.public_bytes(serialization.Encoding.DER))),
    )
    return seq(
        tlv(0x0A, b"\x00"),  # successful
        tlv(0xA0, seq(OCSP_BASIC, octets(basic))),
    )


def bundle(responses: list[bytes], version: int = 1) -> bytes:
    return seq(integer(version), seq(*(octets(item) for item in responses)))


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "responses").mkdir(parents=True)
    (OUT / "bundles").mkdir()

    root_key, l2_key, l3_key, l4_key, leaf_key = (key() for _ in range(5))
    root = certificate("Test Device Identity CA", root_key, None, root_key, ca=True)
    l2 = certificate("Test GH100 Identity", l2_key, root, root_key, ca=True)
    l3 = certificate("Test Provisioner ICA", l3_key, l2, l2_key, ca=True)
    l4 = certificate("Test GPU BROM", l4_key, l3, l3_key, ca=True)
    leaf = certificate("Test GPU FMC LF", leaf_key, l4, l4_key, ca=False)
    unrelated_key = key()
    unrelated = certificate("Test Unrelated", unrelated_key, l3, l3_key, ca=False)
    stranger_key = key()
    stranger = certificate("Test Stranger CA", stranger_key, None, stranger_key, ca=True)

    responders = {}
    for label, issuer, issuer_key in (("root", root, root_key), ("l2", l2, l2_key), ("l3", l3, l3_key)):
        responder_key = key()
        responders[label] = (
            certificate(f"Test OCSP Responder {label}", responder_key, issuer, issuer_key, ca=False, ocsp_signing=True),
            responder_key,
        )
    wrong_key = key()
    wrong_issuer = certificate("Test OCSP Responder wrong issuer", wrong_key, l2, l2_key, ca=False, ocsp_signing=True)
    no_eku_key = key()
    no_eku = certificate("Test OCSP Responder no EKU", no_eku_key, l3, l3_key, ca=False)
    root_signer_key = key()
    root_signer = certificate("Test OCSP Root Signer no EKU", root_signer_key, root, root_key, ca=False)

    for label, cert in {
        "root": root,
        "l2": l2,
        "l3": l3,
        "l4": l4,
        "leaf": leaf,
        "unrelated": unrelated,
        "stranger_root": stranger,
    }.items():
        (OUT / f"{label}.pem").write_bytes(pem(cert))

    r_root, k_root = responders["root"]
    r_l2, k_l2 = responders["l2"]
    r_l3, k_l3 = responders["l3"]
    good = {
        "l2": response(l2, root, r_root, k_root),
        "l3": response(l3, l2, r_l2, k_l2),
        "l4": response(l4, l3, r_l3, k_l3),
    }
    responses = {
        "good_l2": good["l2"],
        "good_l3": good["l3"],
        "good_l4": good["l4"],
        "good_l4_issuer_signed": response(l4, l3, l3, l3_key),
        "unused_unrelated": response(unrelated, l3, r_l3, k_l3),
        "l4_wrong_issuer_responder": response(l4, l3, wrong_issuer, wrong_key),
        "l4_responder_without_eku": response(l4, l3, no_eku, no_eku_key),
        "l4_root_signer_without_eku": response(l4, l3, root_signer, root_signer_key),
        "l4_revoked": response(l4, l3, r_l3, k_l3, status=ocsp.OCSPCertStatus.REVOKED),
        "l4_unknown": response(l4, l3, r_l3, k_l3, status=ocsp.OCSPCertStatus.UNKNOWN),
        "l4_no_next_update": response(l4, l3, r_l3, k_l3, next_update=None),
        "l4_next_equals_this": response(l4, l3, r_l3, k_l3, next_update=T0),
        "l4_next_48h": response(l4, l3, r_l3, k_l3, next_update=T0 + 2 * DAY),
        "l4_next_1h": response(l4, l3, r_l3, k_l3, next_update=T0 + dt.timedelta(hours=1)),
        "l4_two_singles": manual_response(
            [single_good(l4, l3), single_good(l4, l3, this_update=T0 + dt.timedelta(minutes=1))],
            r_l3,
            k_l3,
        ),
        "l4_manual_single": manual_response([single_good(l4, l3)], r_l3, k_l3),
        "try_later": seq(tlv(0x0A, b"\x03")),
    }
    # Flip one byte inside the response signature itself, not the embedded
    # responder certificate that follows it.
    signature = ocsp.load_der_ocsp_response(good["l4"]).signature
    signature_at = good["l4"].index(signature)
    bad_signature = bytearray(good["l4"])
    bad_signature[signature_at + len(signature) // 2] ^= 0x01
    responses["l4_bad_signature"] = bytes(bad_signature)
    responses["l4_trailing_byte"] = good["l4"] + b"\x00"
    for label, data in responses.items():
        (OUT / "responses" / f"{label}.der").write_bytes(data)

    bundles = {
        "good": bundle([good["l2"], good["l3"], good["l4"], responses["unused_unrelated"]]),
        "version_2": bundle([good["l4"]], version=2),
        "empty": bundle([]),
        "seventeen": bundle([good["l4"]] * 17),
        "oversized_response": bundle([b"\x30" + b"\x00" * 2048]),
        "trailing_byte": bundle([good["l4"]]) + b"\x00",
        "version_non_minimal": seq(tlv(0x02, b"\x00\x01"), seq(octets(good["l4"]))),
        "length_non_minimal": seq(b"\x02\x81\x01\x01", seq(octets(good["l4"]))),
        "indefinite_length": b"\x30\x80" + integer(1) + seq(octets(good["l4"])) + b"\x00\x00",
        "item_not_octet_string": seq(integer(1), seq(tlv(0x30, good["l4"]))),
    }
    for label, data in bundles.items():
        (OUT / "bundles" / f"{label}.der").write_bytes(data)

    manifest = {
        "generator": "sol/test-fixtures/generate_status_proofs.py",
        "cryptography": __import__("cryptography").__version__,
        "t0_unix": int(T0.timestamp()),
        "chain_order": ["leaf", "l4", "l3", "l2", "root"],
        "files": {
            str(path.relative_to(OUT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(OUT.rglob("*"))
            if path.is_file()
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
