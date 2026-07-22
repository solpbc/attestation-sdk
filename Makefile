# sol pbc build rail for the attestation-sdk fork (sol/portable branch).
# All real builds run inside the CI container (podman) — the host needs only podman.
# The vendored dep build (USE_SYSTEM_DEPS=OFF) is used for BOTH ci and release so CI
# tests the same configuration that ships. (el8 system curl 7.61 predates the URL API
# the SDK needs, so the system-deps build is not viable on the CI image anyway.)
#
# If cmake fails with "Could not find toolchain" after a CI-image rebuild, the build/
# dir has a stale toolchain cache — run `make clean` first.

IMAGE := attestation-sdk-ci
SDK_DIR := nv-attestation-sdk-cpp
PODMAN_RUN := podman run --rm -v $(CURDIR):/src:Z -w /src $(IMAGE)

# The upstream test harness hard-refuses to run when NVAT_C_SDK_TEST_SERVICE_KEY is
# empty; the offline subset never sends it, so any non-empty value satisfies setup.
TEST_SERVICE_KEY ?= sol-unit-dummy

# These suites hit live NVIDIA endpoints (OCSP/RIM/NRAS) and 403 without a real
# service key — they are integration tests, not offline unit tests, so they are
# excluded from the ci gate. Full suite manually:
#   make ci TEST_SERVICE_KEY=<real-key> NETWORK_TESTS='^$$'
NETWORK_TESTS := GpuVerifierTest|SwitchVerifierTest|GpuLocalVerifierTestCApi|SwitchLocalVerifierTestCApi|RimDocumentFixture|AttestationTest|GpuEvidenceTest|SwitchEvidenceTest|GpuRemoteVerifierTestCApi|SwitchRemoteVerifierTestCApi

.PHONY: install hopper-install image ci test format clean

install: image

hopper-install: image

image:
	podman build -t $(IMAGE) -f sol/ci/Containerfile sol/ci

ci: image
	$(PODMAN_RUN) bash -ec '\
	  cmake -S $(SDK_DIR) -B build -DUSE_SYSTEM_DEPS=OFF -DBUILD_TESTING=ON -DBUILD_SHARED_LIBS=ON && \
	  cmake --build build -j$$(nproc) && \
	  NVAT_C_SDK_TEST_SERVICE_KEY=$(TEST_SERVICE_KEY) ctest --test-dir build --output-on-failure -E "$(NETWORK_TESTS)"'

test: ci

format:
	@echo "no formatter wired yet (upstream C++ has no enforced format); see sol/ci"

clean:
	rm -rf build
