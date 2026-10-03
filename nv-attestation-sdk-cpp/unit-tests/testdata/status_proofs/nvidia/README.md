# Real NVIDIA status proofs for one production H100

`gpu-evidence.json` is the GPU leg of the sol pbc confidential-processing
engine's qualified attestation fixture (driver 595.71.05, VBIOS
96.00.88.00.11), in the evidence-file shape nvattest reads. `rims/` holds the
three NVIDIA-signed reference manifests the journal packages for that engine.

`responses/` holds unchanged NVIDIA OCSP responses for the eight distinct
certificate IDs that appraisal checks, including the second VBIOS signer that
this GPU does not use. They were fetched once on 2026-10-03 UTC with
`sol/test-fixtures/capture_nvidia_status_proofs.py`: one nonce-free SHA-1
CertID request each, no owner data. `bundle.der` is the version 1 status-proof
bundle of all eight, and `receipt.json` records each response's hash, size and
signed times. Tests judge them at fixed verification times, so they do not
age.
