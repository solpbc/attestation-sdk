#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import re
import shlex
import sys
import tomllib


CPP_NOTICE_FILES = {
    "CLI11": ["CLI11.txt"],
    "curl_external": ["curl_external.txt"],
    "fmt": ["fmt.txt"],
    "json": ["json.txt"],
    "jwt-cpp": ["jwt-cpp.txt"],
    "libxml2_external": [
        "libxml2_external.txt", "libxml2-hash.c-notice.txt",
        "libxml2-list.c-notice.txt", "libxml2-dict.c-notice.txt",
    ],
    "openssl_external": ["openssl_external.txt"],
    "regorus": ["regorus.txt"],
    "spdlog": ["spdlog.txt"],
    "xmlsec_external": ["xmlsec_external.txt"],
}
NOTICE_ROOT = pathlib.Path(__file__).resolve().parent / "notices"
# Union of the three release triples' normal/build cargo trees for the pinned
# lock and regorus/semver feature. Update with the lock and notice snapshot.
EXPECTED_CRATE_COUNT = 162


def declaration_records(text, path):
    pattern = re.compile(r"(ExternalProject_Add|FetchContent_Declare)\s*\(")
    for match in pattern.finditer(text):
        depth = 1
        index = match.end()
        quoted = False
        escaped = False
        while index < len(text) and depth:
            char = text[index]
            if escaped:
                escaped = False
            elif char == "\\" and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted and char == "(":
                depth += 1
            elif not quoted and char == ")":
                depth -= 1
            index += 1
        if depth:
            raise ValueError(f"unbalanced dependency declaration in {path}")
        body = re.sub(r"#[^\n]*", "", text[match.end():index - 1])
        tokens = shlex.split(body, posix=True)
        if not tokens:
            raise ValueError(f"empty dependency declaration in {path}")
        yield match.group(1), tokens


def declarations(path):
    for _kind, tokens in declaration_records(path.read_text(), path):
        yield tokens


def value_after(tokens, key):
    try:
        return tokens[tokens.index(key) + 1]
    except (ValueError, IndexError):
        return None


def classify(name, path):
    lowered = name.lower()
    if lowered in {"googletest", "gtest"} or "unit-tests" in path.parts or "tests" in path.parts:
        return "test"
    if lowered == "corrosion":
        return "build"
    return "runtime"


def select_dependency_inputs(candidates):
    candidates = {pathlib.Path(path) for path in candidates}
    inputs = sorted(
        path
        for path in candidates
        if path.name == "CMakeLists.txt"
        and path.parts
        and path.parts[0]
        in {"nv-attestation-sdk-cpp", "nv-attestation-cli"}
    )
    gtest = pathlib.Path("nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake")
    if gtest in candidates:
        inputs.append(gtest)
    return inputs


def dependency_inputs(root):
    candidates = [
        path.relative_to(root)
        for path in (
            list((root / "nv-attestation-sdk-cpp").rglob("CMakeLists.txt"))
            + list((root / "nv-attestation-cli").rglob("CMakeLists.txt"))
        )
    ]
    gtest = root / "nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake"
    candidates.append(gtest.relative_to(root))
    return [root / path for path in select_dependency_inputs(candidates)]


def parse(root):
    inputs = dependency_inputs(root)
    dependencies = {}
    for path in inputs:
        for tokens in declarations(path):
            name = tokens[0]
            url = value_after(tokens, "URL")
            url_hash = value_after(tokens, "URL_HASH")
            repository = value_after(tokens, "GIT_REPOSITORY")
            tag = value_after(tokens, "GIT_TAG")
            if repository or tag:
                if not repository or not tag or url or url_hash:
                    raise ValueError(f"dependency {name} has an unrecognized or incomplete git declaration in {path}")
                pin = {"type": "git", "repository": repository, "revision": tag}
            elif url or url_hash:
                if not url:
                    raise ValueError(f"dependency {name} has URL_HASH without URL in {path}")
                if not url_hash:
                    raise ValueError(f"dependency {name} archive URL has no URL_HASH in {path}")
                if not re.search(r"(?:/v?\d|[-_]\d)", url):
                    raise ValueError(f"dependency {name} has a floating URL: {url}")
                pin = {"type": "archive", "url": url}
                algorithm, separator, digest = url_hash.partition("=")
                if not separator or not digest:
                    raise ValueError(f"dependency {name} has an invalid URL_HASH")
                pin["hash"] = {"algorithm": algorithm.lower(), "value": digest}
            else:
                raise ValueError(f"dependency {name} is unpinned or unrecognized in {path}")
            entry = {"name": name, "classification": classify(name, path), **pin}
            previous = dependencies.get(name.lower())
            if previous:
                previous_pin = {key: value for key, value in previous.items() if key not in {"name", "classification"}}
                current_pin = {key: value for key, value in entry.items() if key not in {"name", "classification"}}
                if previous_pin != current_pin:
                    raise ValueError(f"conflicting declarations for dependency {name}")
                if previous["classification"] == "runtime" or entry["classification"] == "runtime":
                    entry["classification"] = "runtime"
                elif previous["classification"] == "build" or entry["classification"] == "build":
                    entry["classification"] = "build"
                entry["name"] = previous["name"]
            dependencies[name.lower()] = entry
    return sorted(dependencies.values(), key=lambda item: item["name"].lower())


def _notice_text(path):
    data = path.read_bytes()
    if not data.strip():
        raise ValueError(f"empty licence text: {path}")
    return data.decode("utf-8").rstrip("\n")


def _add_text(lines, title, text):
    # Long fences keep source text verbatim, including embedded Markdown/HTML.
    fence = "~" * 8
    if fence in text:
        raise ValueError(f"licence text contains notice fence: {title}")
    lines.extend([f"### {title}", "", f"{fence}text", text, fence, ""])


def _rust_notices(lines, cargo_lock):
    pinned = pathlib.Path(__file__).resolve().parent / "regorus-Cargo.lock"
    lock_bytes = cargo_lock.read_bytes()
    if lock_bytes != pinned.read_bytes():
        raise ValueError("built regorus Cargo.lock differs from the release pin")
    index = json.loads((NOTICE_ROOT / "regorus-sources.json").read_text())
    if index["cargo_lock_sha256"] != hashlib.sha256(lock_bytes).hexdigest():
        raise ValueError("regorus licence inventory does not match pinned Cargo.lock")
    if len(index["packages"]) != EXPECTED_CRATE_COUNT:
        raise ValueError("regorus licence inventory has an incomplete crate population")
    locked = {
        (package["name"], package["version"])
        for package in tomllib.loads(lock_bytes.decode())["package"]
    }
    seen = set()
    lines.extend(["## regorus Rust crate tree", "", "This crate population is bound to the Cargo.lock shipped with the release rail.", ""])
    for package in index["packages"]:
        identity = (package["name"], package["version"])
        if identity not in locked or identity in seen:
            raise ValueError(f"invalid regorus licence inventory entry: {identity}")
        seen.add(identity)
        lines.extend([f"### {identity[0]} {identity[1]}", "", f"Licence: {package['license']}", ""])
        for record in package["texts"]:
            path = NOTICE_ROOT / "texts" / f"{record['sha256']}.txt"
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"regorus licence text digest mismatch: {path}")
            _add_text(lines, record["name"], data.decode("utf-8").rstrip("\n"))
    if not seen:
        raise ValueError("empty regorus crate licence inventory")


def notices(dependencies, cargo_lock, rustc_version):
    runtime = {dep["name"]: dep for dep in dependencies if dep["classification"] == "runtime"}
    if set(runtime) != set(CPP_NOTICE_FILES):
        raise ValueError(f"runtime dependency notice inventory changed: {sorted(set(runtime) ^ set(CPP_NOTICE_FILES))}")
    if rustc_version not in {"1.88.0", "1.97.1"}:
        raise ValueError(f"no Rust standard-library notice bundle for rustc {rustc_version}")
    lines = [
        "# Third-Party Notices",
        "",
        "This distribution includes the following third-party code and licence texts.",
        "",
    ]
    for dep in dependencies:
        if dep["classification"] != "runtime":
            continue
        source = dep.get("url", dep.get("repository"))
        revision = dep.get("revision", dep.get("hash", {}).get("value", "immutable release URL"))
        lines.extend([f"## {dep['name']}", "", f"Source: {source}", f"Pin: {revision}", ""])
        for name in CPP_NOTICE_FILES[dep["name"]]:
            _add_text(lines, name, _notice_text(NOTICE_ROOT / "cpp" / name))
    _rust_notices(lines, cargo_lock)
    lines.extend([f"## Rust standard library {rustc_version}", "", "The Rust standard library is statically linked through regorus.", ""])
    for name in ("COPYRIGHT", "LICENSE-MIT", "LICENSE-APACHE", "COPYRIGHT-library.html"):
        _add_text(lines, name, _notice_text(NOTICE_ROOT / "std" / rustc_version / name))
    lines.extend([
        "## Mozilla CA Certificate Store",
        "",
        "The bundled CA certificate data is derived from Mozilla's root certificate store",
        "and redistributed under the Mozilla Public License 2.0.",
        "Source: https://curl.se/docs/caextract.html",
        "License: https://www.mozilla.org/MPL/2.0/",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--json", type=pathlib.Path, required=True)
    parser.add_argument("--notices", type=pathlib.Path, required=True)
    parser.add_argument("--cargo-lock", type=pathlib.Path, required=True)
    parser.add_argument("--rustc-version", required=True)
    args = parser.parse_args()
    try:
        dependencies = parse(args.root)
        notice_text = notices(dependencies, args.cargo_lock, args.rustc_version)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    args.json.write_text(json.dumps(dependencies, indent=2) + "\n")
    args.notices.write_text(notice_text)
    print(f"generated {len(dependencies)} dependency pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
