# sol pbc build rail for the attestation-sdk fork (sol/portable branch).
# All real builds run inside the CI container (podman) — the host needs only podman.
# Unit CI uses USE_SYSTEM_DEPS=ON (deps from the container image); release artifacts
# use the vendored static build (separate targets, added by the release rail).

IMAGE := attestation-sdk-ci
SDK_DIR := nv-attestation-sdk-cpp
PODMAN_RUN := podman run --rm -v $(CURDIR):/src:Z -w /src $(IMAGE)

.PHONY: install hopper-install image ci test format clean

install: image

hopper-install: image

image:
	podman build -t $(IMAGE) -f sol/ci/Containerfile sol/ci

ci: image
	$(PODMAN_RUN) bash -ec '\
	  cmake -S $(SDK_DIR) -B build -DUSE_SYSTEM_DEPS=OFF -DBUILD_TESTING=ON -DBUILD_SHARED_LIBS=ON && \
	  cmake --build build -j$$(nproc) && \
	  ctest --test-dir build --output-on-failure'

test: ci

format:
	@echo "no formatter wired yet (upstream C++ has no enforced format); see sol/ci"

clean:
	rm -rf build
