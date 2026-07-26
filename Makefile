# sol pbc build rail for the attestation-sdk fork (sol/portable branch).
# Linux containers prefer Podman and fall back to a usable local Docker engine.
# The vendored dep build (USE_SYSTEM_DEPS=OFF) is used for BOTH ci and release so CI
# tests the same configuration that ships. (el8 system curl 7.61 predates the URL API
# the SDK needs, so the system-deps build is not viable on the CI image anyway.)
#
# If cmake fails with "Could not find toolchain" after a CI-image rebuild, the build/
# dir has a stale toolchain cache — run `make clean` first.

CLI_DIR := nv-attestation-cli
GIT_COMMON_DIR := $(shell git rev-parse --path-format=absolute --git-common-dir)
RAIL := python3 sol/release/rail.py
HOST_TARGET ?=

# The upstream test harness hard-refuses to run when NVAT_C_SDK_TEST_SERVICE_KEY is
# empty; the offline subset never sends it, so any non-empty value satisfies setup.
TEST_SERVICE_KEY ?= sol-unit-dummy

# These suites hit live NVIDIA endpoints (OCSP/RIM/NRAS) and 403 without a real
# service key — they are integration tests, not offline unit tests, so they are
# excluded from the ci gate. Full suite manually:
#   make ci TEST_SERVICE_KEY=<real-key> NETWORK_TESTS='^$$'
NETWORK_TESTS := GpuVerifierTest|SwitchVerifierTest|GpuLocalVerifierTestCApi|SwitchLocalVerifierTestCApi|RimDocumentFixture|AttestationTest|GpuEvidenceTest|SwitchEvidenceTest|GpuRemoteVerifierTestCApi|SwitchRemoteVerifierTestCApi

.PHONY: install hopper-install image rail-test ci ci-container test release format clean

install: image

hopper-install: image

image:
	RUNTIME="$$( $(RAIL) runtime select )" && \
		IMAGE="$$( $(RAIL) runtime image-tag )" && \
		CI_IMAGE="$$( $(RAIL) authority build-image "$(HOST_TARGET)" )" && \
		"$$RUNTIME" build --build-arg CI_IMAGE="$$CI_IMAGE" -t "$$IMAGE" -f sol/ci/Containerfile sol/ci

rail-test:
	python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
	shellcheck $$(find sol -type f -name '*.sh' -print | sort)

ci:
	$(MAKE) rail-test
	$(MAKE) ci-container HOST_TARGET="$(HOST_TARGET)"

ci-container: image
	./sol/check-curl-handle-sites.sh
	RUNTIME="$$( $(RAIL) runtime select )" && \
		IMAGE="$$( $(RAIL) runtime image-tag )" && \
		"$$RUNTIME" run --rm -v $(CURDIR):/src:Z \
			-v $(GIT_COMMON_DIR):$(GIT_COMMON_DIR):ro,Z -w /src "$$IMAGE" bash -ec '\
		  rm -rf build && \
		  cmake -S $(CLI_DIR) -B build -DUSE_SYSTEM_NVAT=OFF -DUSE_SYSTEM_DEPS=OFF -DBUILD_TESTING=ON -DBUILD_SHARED_LIBS=ON && \
		  cmake --build build -j$$(nproc) && \
		  NVAT_C_SDK_TEST_SERVICE_KEY=$(TEST_SERVICE_KEY) ctest --test-dir build --output-on-failure -L unit -E "$(NETWORK_TESTS)"'

test: ci

release:
	./sol/release/release.sh "$(TARGET)"

format:
	@echo "no formatter wired yet (upstream C++ has no enforced format); see sol/ci"

clean:
	rm -rf build
