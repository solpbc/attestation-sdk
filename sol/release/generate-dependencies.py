#!/usr/bin/env python3
import argparse
import json
import pathlib
import re
import shlex
import sys


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


def dependency_inputs(root):
    inputs = sorted(
        list((root / "nv-attestation-sdk-cpp").rglob("CMakeLists.txt"))
        + list((root / "nv-attestation-cli").rglob("CMakeLists.txt"))
    )
    inputs.append(root / "nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake")
    return inputs


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


def notices(dependencies):
    lines = [
        "# Third-Party Notices",
        "",
        "This distribution contains software from the pinned upstream projects below.",
        "Refer to each project for its complete license terms.",
        "",
    ]
    for dep in dependencies:
        if dep["classification"] != "runtime":
            continue
        source = dep.get("url", dep.get("repository"))
        revision = dep.get("revision", dep.get("hash", {}).get("value", "immutable release URL"))
        lines.extend([f"## {dep['name']}", "", f"Source: {source}", f"Pin: {revision}", ""])
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
    args = parser.parse_args()
    try:
        dependencies = parse(args.root)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    args.json.write_text(json.dumps(dependencies, indent=2) + "\n")
    args.notices.write_text(notices(dependencies))
    print(f"generated {len(dependencies)} dependency pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
