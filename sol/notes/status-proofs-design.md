# Verified-path coverage and offline status proofs (sol.5)

## Revocation coverage follows the verified path

`X509CertChain::verify` hands OpenSSL the first certificate and the rest as an
untrusted pool, and OpenSSL builds its own path. `generate_ocsp_claims` used to
pair `m_certs[i]` with `m_certs[i+1]` regardless of that path, so an inserted
non-issuer could make a certificate's status be asked of the wrong issuer.
After `X509_verify_cert` succeeds, the presented chain must now equal
`X509_STORE_CTX_get0_chain` exactly, root included, and every status lookup
uses subject/issuer pairs from that verified path. This applies to device and
RIM chains and to both OCSP clients.

## One strict response verifier

`OcspResponseVerifier` is shared by the online client and the offline one: one
complete, canonical, successful DER `OCSPResponse`; `OCSP_basic_verify` with
flags 0 against plain anchors; exactly one `SingleResponse` for the requested
`CertID`. Failure is an error with no status.

## Offline signed-age status

`RawProofOcspClient` (C API `nvat_ocsp_client_create_raw_proofs`, CLI
`--ocsp-proof-bundle` with `--ocsp-verification-time`) judges raw NVIDIA
responses on the relying party's clock. It has no HTTP client. Each checked
certificate must be covered exactly once; GOOD needs `thisUpdate` and
`nextUpdate`, `thisUpdate` at most 60 s after the verification time, and a
verification time before `min(nextUpdate, thisUpdate + 86400)`. Claims never
report a nonce match; each chain carries `x-sol-cert-ocsp-signed-age`
version 1 with the minimum deadline.

The bundle is the journal's RA-TLS status-proof extension value, version 1:
`SEQUENCE { version INTEGER (1), responses SEQUENCE OF OCTET STRING }`, at most
16,384 bytes, 16 responses and 2,048 bytes per response. The journal's
`core/fixtures/ratls-contract.json` (`status_proofs`) and its independent
vectors are the contract of record.

## Fixtures

`sol/test-fixtures/generate_status_proofs.py` builds an independent PKI and
responses with Python `cryptography` 46.0.7.
`sol/test-fixtures/capture_nvidia_status_proofs.py` captured the real NVIDIA
responses under `unit-tests/testdata/status_proofs/nvidia/`.
