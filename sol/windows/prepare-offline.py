#!/usr/bin/env python3
# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
"""Acquire pinned Windows build inputs; verification performs no network access."""
import argparse
import concurrent.futures
import hashlib
import io
import json
import pathlib
import re
import tarfile
import tomllib
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def acquire(item, root):
    path = root / item['name']
    with urllib.request.urlopen(item['url'], timeout=180) as response:
        data = response.read()
    if digest(data) != item['sha256']:
        raise ValueError(f"input digest mismatch: {item['name']}")
    path.write_bytes(data)
    return {'path': item['name'], 'sha256': digest(data), 'size': len(data)}


def deterministic_tar(root, destination):
    with destination.open('wb') as output:
        import gzip
        with gzip.GzipFile(fileobj=output, mode='wb', mtime=0, filename='') as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as archive:
                for path in sorted(root.rglob('*')):
                    if path.is_symlink():
                        raise ValueError(f"symlink in offline input: {path}")
                    if not path.is_file():
                        continue
                    data = path.read_bytes()
                    member = tarfile.TarInfo('cargo-vendor/' + path.relative_to(root).as_posix())
                    member.size = len(data)
                    member.mode = 0o644
                    archive.addfile(member, io.BytesIO(data))


def crate(item, cache):
    name, version = item['name'], item['version']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not re.fullmatch(r'[0-9A-Za-z.+-]+', version):
        raise ValueError('invalid locked crate identity')
    return acquire({'name': f'{name}-{version}.crate',
                    'url': f'https://static.crates.io/crates/{name}/{name}-{version}.crate',
                    'sha256': item['checksum']}, cache)


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    inputs = json.loads((HERE / 'inputs.json').read_text())
    ca = tomllib.loads((REPO / 'sol/release/targets.toml').read_text())['release']
    items = inputs['sources'] + inputs['build_tools'] + inputs['cmake_sources'] + [inputs['cmake_tool']]
    items += [{'name': 'ca-bundle.pem', 'url': ca['ca_bundle_url'], 'sha256': ca['ca_bundle_sha256']}]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda item: acquire(item, root), items))
    lock_path = REPO / 'sol/release/regorus-Cargo.lock'
    lock = tomllib.loads(lock_path.read_text())
    packages = [p for p in lock['package'] if 'source' in p]
    if any(p['source'] != 'registry+https://github.com/rust-lang/crates.io-index' for p in packages):
        raise ValueError('unhandled Cargo source in locked graph')
    cache = root / 'crate-archives'
    cache.mkdir()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda item: crate(item, cache), packages))
    vendor = root / 'vendor-source'
    vendor.mkdir()
    for p in packages:
        identity = f"{p['name']}-{p['version']}"
        data = (cache / f'{identity}.crate').read_bytes()
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive.getmembers():
                if not member.name.startswith(identity + '/') or not (member.isfile() or member.isdir()):
                    raise ValueError(f'unsafe crate member: {member.name}')
            archive.extractall(vendor, filter='data')
        source = vendor / identity
        files = {f.relative_to(source).as_posix(): digest(f.read_bytes())
                 for f in sorted(source.rglob('*')) if f.is_file()}
        (source / '.cargo-checksum.json').write_text(json.dumps({'files': files, 'package': p['checksum']}, sort_keys=True))
    deterministic_tar(vendor, root / 'cargo-vendor.tar.gz')
    vendor_bytes = (root / 'cargo-vendor.tar.gz').read_bytes()
    (root / 'cargo-vendor.json').write_text(json.dumps({'sha256': digest(vendor_bytes),
        'cargo_lock_sha256': digest(lock_path.read_bytes())}, indent=2) + '\n')
    import shutil
    shutil.rmtree(vendor)
    files = [{'path': p.relative_to(root).as_posix(), 'sha256': digest(p.read_bytes()), 'size': p.stat().st_size}
             for p in sorted(root.rglob('*')) if p.is_file()]
    (root / 'offline-manifest.json').write_text(json.dumps({'schema': 1, 'files': files}, indent=2) + '\n')
    verify(root)


def verify(root):
    if any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('symlink in offline inputs')
    manifest = json.loads((root / 'offline-manifest.json').read_text())
    if manifest.get('schema') != 1 or not manifest.get('files'):
        raise ValueError('invalid offline manifest')
    expected = set()
    for item in manifest['files']:
        relative = pathlib.PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or str(relative) != item['path']:
            raise ValueError('unsafe offline path')
        if item['path'] in expected:
            raise ValueError('duplicate offline path')
        expected.add(item['path'])
        path = root / relative
        if any(part.is_symlink() for part in [path, *path.parents] if part == root or root in part.parents):
            raise ValueError('symlink in offline inputs')
        data = path.read_bytes()
        if len(data) != item['size'] or digest(data) != item['sha256']:
            raise ValueError(f"missing or changed offline input: {item['path']}")
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != expected | {'offline-manifest.json'}:
        raise ValueError('unexpected offline input')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'verify'])
    parser.add_argument('directory', type=pathlib.Path)
    args = parser.parse_args()
    try:
        (prepare if args.command == 'prepare' else verify)(args.directory)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'ERROR: {error}\n')
    print(f'NVATTEST_OFFLINE_INPUTS_OK {args.directory}')
