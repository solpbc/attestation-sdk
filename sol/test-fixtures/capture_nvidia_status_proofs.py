#!/usr/bin/env python3
"""Capture real NVIDIA-signed OCSP responses for one GPU evidence fixture.

Derives the CertIDs a local appraisal checks (device chain without the alias
leaf and root, plus every RIM signing chain without its root), sends one
nonce-free SHA-1 CertID request per distinct ID to NVIDIA's OCSP responder,
and writes each unchanged response, a version 1 status-proof bundle and a
receipt. Content-free: only certificate identifiers leave the host.

    uv run --with cryptography==46.0.7 python3 \
        sol/test-fixtures/capture_nvidia_status_proofs.py EVIDENCE.json RIM_DIR OUT_DIR
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509 import ocsp

URL = "https://ocsp.ndis.nvidia.com"


def device_pairs(evidence: dict) -> list[tuple[x509.Certificate, x509.Certificate]]:
    chain = x509.load_pem_x509_certificates(base64.b64decode(evidence["certificate"]))
    # Index 0 is the GPU alias certificate and the last is the root.
    return [(chain[i], chain[i + 1]) for i in range(1, len(chain) - 1)]


def rim_pairs(xml: str) -> list[tuple[x509.Certificate, x509.Certificate]]:
    chain = [
        x509.load_der_x509_certificate(base64.b64decode(re.sub(r"\s", "", body)))
        for body in re.findall(r"<ds:X509Certificate>(.*?)</ds:X509Certificate>", xml, re.S)
    ]
    return [(chain[i], chain[i + 1]) for i in range(0, len(chain) - 1)]


def der_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + der_len(len(value)) + value


def bundle(responses: list[bytes]) -> bytes:
    items = b"".join(tlv(0x04, item) for item in responses)
    return tlv(0x30, tlv(0x02, b"\x01") + tlv(0x30, items))


def main() -> None:
    evidence_path, rim_dir, out = (pathlib.Path(arg) for arg in sys.argv[1:4])
    evidence = json.loads(evidence_path.read_text())[0]
    pairs = device_pairs(evidence)
    for rim in sorted(rim_dir.glob("*.xml")):
        pairs += rim_pairs(rim.read_text())

    requests: dict[bytes, tuple[x509.Certificate, x509.Certificate]] = {}
    for subject, issuer in pairs:
        request = (
            ocsp.OCSPRequestBuilder()
            .add_certificate(subject, issuer, hashes.SHA1())
            .build()
        )
        requests.setdefault(request.public_bytes(serialization.Encoding.DER), (subject, issuer))

    out.mkdir(parents=True, exist_ok=True)
    receipt = {"url": URL, "evidence": evidence_path.name, "rims": [p.name for p in sorted(rim_dir.glob("*.xml"))], "responses": []}
    responses = []
    for index, (der, (subject, issuer)) in enumerate(requests.items()):
        queried_at = dt.datetime.now(dt.timezone.utc)
        http = urllib.request.Request(
            URL, data=der, method="POST",
            headers={"Content-Type": "application/ocsp-request", "Accept": "application/ocsp-response"},
        )
        with urllib.request.urlopen(http, timeout=30) as reply:
            body = reply.read(4097)
        if len(body) > 4096:
            raise SystemExit("response larger than 4096 bytes")
        parsed = ocsp.load_der_ocsp_response(body)
        if parsed.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            raise SystemExit(f"unsuccessful response for {subject.serial_number:x}")
        name = f"{index:02d}-{subject.serial_number:x}.der"
        (out / name).write_bytes(body)
        responses.append(body)
        receipt["responses"].append({
            "file": name,
            "subject": subject.subject.rfc4514_string(),
            "issuer": issuer.subject.rfc4514_string(),
            "serial": f"{subject.serial_number:x}",
            "queried_at": queried_at.isoformat(),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "status": parsed.certificate_status.name,
            "this_update_unix": int(parsed.this_update_utc.timestamp()),
            "next_update_unix": int(parsed.next_update_utc.timestamp()) if parsed.next_update_utc else None,
            "produced_at_unix": int(parsed.produced_at_utc.timestamp()),
        })
    data = bundle(responses)
    (out / "bundle.der").write_bytes(data)
    receipt["bundle_bytes"] = len(data)
    receipt["bundle_sha256"] = hashlib.sha256(data).hexdigest()
    receipt["required_certids"] = len(requests)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("required_certids", "bundle_bytes")}))


if __name__ == "__main__":
    main()
