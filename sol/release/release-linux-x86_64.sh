#!/usr/bin/env bash
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"
dirty_status=$(git status --porcelain --untracked-files=all)
if [[ -n "$dirty_status" ]]; then
  echo "release requires a clean worktree; commit or remove these changes:" >&2
  printf '%s\n' "$dirty_status" >&2
  exit 1
fi
source sol/release/release.env

upstream_version=$(sed -nE 's/^project\(nv-attestation VERSION ([0-9.]+)\)$/\1/p' nv-attestation-sdk-cpp/CMakeLists.txt)
if [[ -z "$upstream_version" ]]; then
  echo "could not derive upstream SDK version" >&2
  exit 1
fi
version="${upstream_version}-sol.${SOL_REVISION}"
artifact_name="libnvat-linux-x86_64-${version}-archive.tar.xz"
source_date_epoch=$(git log -1 --format=%ct)
git_common_dir=$(git rev-parse --path-format=absolute --git-common-dir)

./sol/check-curl-handle-sites.sh

podman run --rm \
  -v "$root:/src:Z" \
  -v "$git_common_dir:$git_common_dir:ro,Z" \
  -w /src localhost/attestation-sdk-ci \
  bash -ec 'rm -rf build/release && cmake -S nv-attestation-cli -B build/release -DUSE_SYSTEM_NVAT=OFF -DUSE_SYSTEM_DEPS=OFF -DBUILD_TESTING=OFF -DBUILD_SHARED_LIBS=ON -DCMAKE_BUILD_TYPE=Release && cmake --build build/release -j$(nproc)'

work_dir=$(mktemp -d)
cleanup() {
  rm -rf -- "$work_dir"
}
trap cleanup EXIT
stage="$work_dir/stage"
extracted="$work_dir/extracted"
mkdir -p "$stage/bin" "$stage/lib" "$stage/share/ca" "$extracted" dist

tool_dir="$work_dir/gate-tools"
mkdir -p "$tool_dir/lib"
podman run --rm -v "$tool_dir:/out:Z" localhost/attestation-sdk-ci bash -ec '
  for tool in readelf strings; do
    path=$(command -v "$tool")
    cp "$path" "/out/${tool}.real"
    ldd "$path" | awk '\''$3 ~ /^\// && $1 !~ /^(libc|libpthread|libdl|librt|libm)\.so/ {print $3}'\''
  done | sort -u | while read -r library; do cp "$library" /out/lib/; done
'
cp sol/release/binutils-wrapper.sh "$tool_dir/readelf"
cp sol/release/binutils-wrapper.sh "$tool_dir/strings"
chmod +x "$tool_dir/readelf" "$tool_dir/strings"

curl -fL --retry 3 -o "$work_dir/ca-bundle.pem" "$CA_BUNDLE_URL"
curl -fL --retry 3 -o "$work_dir/ca-bundle.sha256" "${CA_BUNDLE_URL}.sha256"
downloaded_hash=$(sha256sum "$work_dir/ca-bundle.pem" | awk '{print $1}')
published_hash=$(awk 'NR == 1 {print $1}' "$work_dir/ca-bundle.sha256")
if [[ "$downloaded_hash" != "$CA_BUNDLE_SHA256" || "$published_hash" != "$CA_BUNDLE_SHA256" ]]; then
  echo "CA bundle hash mismatch: expected=$CA_BUNDLE_SHA256 downloaded=$downloaded_hash published=$published_hash" >&2
  exit 1
fi
echo "CA snapshot verified: $CA_SNAPSHOT_DATE $CA_BUNDLE_SHA256"

cp build/release/nvattest "$stage/bin/nvattest"
cp -a build/release/nv-attestation-sdk-build/libnvat.so "$stage/lib/libnvat.so"
cp -a build/release/nv-attestation-sdk-build/libnvat.so.1 "$stage/lib/libnvat.so.1"
cp build/release/nv-attestation-sdk-build/libnvat.so.1.2.2 "$stage/lib/libnvat.so.1.2.2"
cp LICENSE "$stage/LICENSE"
cp "$work_dir/ca-bundle.pem" "$stage/share/ca/ca-bundle.pem"

python3 sol/release/generate-dependencies.py \
  --root "$root" \
  --json "$work_dir/dependencies.json" \
  --notices "$stage/share/THIRD_PARTY_NOTICES.md"

sol/release/gate-artifact.sh "$stage" "$root/sol/release/dt-needed.allow"

members=(
  bin/nvattest
  lib/libnvat.so
  lib/libnvat.so.1
  lib/libnvat.so.1.2.2
  LICENSE
  share/ca/ca-bundle.pem
  share/THIRD_PARTY_NOTICES.md
)
archive="dist/$artifact_name"
tar --sort=name --mtime="@$source_date_epoch" --owner=0 --group=0 --numeric-owner \
  -C "$stage" -cJf "$archive" "${members[@]}"
tar -C "$extracted" -xJf "$archive"

artifact_hash=$(sha256sum "$archive" | awk '{print $1}')
printf '%s  %s\n' "$artifact_hash" "$artifact_name" > "${archive}.sha256"
manifest="dist/${artifact_name%.tar.xz}.manifest.json"
manifest_name=$(basename "$manifest")
manifest_args=()
for member in "${members[@]}"; do
  manifest_args+=(--member "$member")
done
python3 sol/release/generate-manifest.py \
  --root "$root" \
  --dependencies "$work_dir/dependencies.json" \
  --output "$manifest" \
  --artifact "$artifact_name" \
  --artifact-sha256 "$artifact_hash" \
  --version "$version" \
  --ci-image "$CI_IMAGE" \
  --ca-date "$CA_SNAPSHOT_DATE" \
  --ca-url "$CA_BUNDLE_URL" \
  --ca-sha256 "$CA_BUNDLE_SHA256" \
  --source-date-epoch "$source_date_epoch" \
  "${manifest_args[@]}"

for image_name in FEDORA_IMAGE TUMBLEWEED_IMAGE; do
  image=${!image_name}
  label=${image_name%_IMAGE}
  output=$(podman run --rm \
    -v "$extracted:/artifact:ro,Z" \
    -v "$root/sol/release/gate-artifact.sh:/gate/gate-artifact.sh:ro,Z" \
    -v "$root/sol/release/dt-needed.allow:/gate/dt-needed.allow:ro,Z" \
    -v "$tool_dir:/gate-tools:ro,Z" \
    -v "$root/dist:/release:ro,Z" \
    -e ARTIFACT_NAME="$artifact_name" \
    -e MANIFEST_NAME="$manifest_name" \
    -w /artifact "$image" sh -ec '
    PATH=/gate-tools:$PATH /gate/gate-artifact.sh /artifact /gate/dt-needed.allow
    LD_LIBRARY_PATH=lib ./bin/nvattest --help >/dev/null
    if output=$(LD_LIBRARY_PATH=lib ./bin/nvattest attest --device gpu --gpu-evidence-source file --gpu-evidence-file /dev/null --verifier local --rim-store remote --ca-bundle /nonexistent/path 2>&1); then
      echo "missing CA path unexpectedly succeeded" >&2
      exit 1
    fi
    printf "%s\n" "$output"
    printf "%s\n" "$output" | grep -F "/nonexistent/path" >/dev/null
    printf "%s\n" "$output" | grep -F "from --ca-bundle" >/dev/null

    test -f LICENSE
    test -f bin/nvattest
    test -L lib/libnvat.so
    test -L lib/libnvat.so.1
    test -f lib/libnvat.so.1.2.2
    test -f share/ca/ca-bundle.pem
    test -f share/THIRD_PARTY_NOTICES.md
    set -- /artifact/*; test "$#" -eq 4
    set -- /artifact/bin/*; test "$#" -eq 1
    set -- /artifact/lib/*; test "$#" -eq 3
    set -- /artifact/share/*; test "$#" -eq 2
    set -- /artifact/share/ca/*; test "$#" -eq 1

    set -- $(sha256sum "/release/$ARTIFACT_NAME"); archive_hash=$1
    set -- $(cat "/release/${ARTIFACT_NAME}.sha256"); sidecar_hash=$1
    manifest_hash=$(sed -n '\''/"artifact": {/,/}/ s/.*"sha256": "\([^"]*\)".*/\1/p'\'' "/release/$MANIFEST_NAME")
    test -n "$manifest_hash"
    test "$archive_hash" = "$sidecar_hash"
    test "$archive_hash" = "$manifest_hash"
    echo "archive layout and artifact hash gates passed"
  ')
  echo "[$label] bare-container runtime and eager-error gates passed"
  printf '%s\n' "$output"
done

manifest_hash=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["sha256"])' "$manifest")
sidecar_hash=$(awk 'NR == 1 {print $1}' "${archive}.sha256")
base=$(git merge-base main HEAD)
manifest_base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream_base_commit"])' "$manifest")
expected_series=$(git log --reverse --format='%H%x09%s' "$base..HEAD")
manifest_series=$(python3 -c 'import json,sys; print("\n".join(item["commit"] + "\t" + item["subject"] for item in json.load(open(sys.argv[1]))["sol_series_commits"]))' "$manifest")
manifest_members=$(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["archive_members"]))' "$manifest")
if [[ "$artifact_hash" != "$manifest_hash" \
   || "$artifact_hash" != "$sidecar_hash" \
   || "$base" != "$manifest_base" \
   || "$expected_series" != "$manifest_series" \
   || "$(printf '%s\n' "${members[@]}")" != "$manifest_members" ]]; then
  echo "archive, sidecar, or manifest consistency gate failed" >&2
  exit 1
fi

echo "layout and manifest consistency gates passed"
echo "release artifact: $archive"
