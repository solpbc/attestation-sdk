# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'windows/prepare-offline.py'


class OfflineInputBoundary(unittest.TestCase):
    def fixture(self, root):
        (root / 'input.tar.gz').write_bytes(b'pinned input')
        (root / 'offline-manifest.json').write_text(json.dumps({'schema': 1, 'files': [{
            'path': 'input.tar.gz', 'size': 12,
            'sha256': hashlib.sha256(b'pinned input').hexdigest()}]}))

    def run_entry(self, root):
        return subprocess.run([sys.executable, str(SCRIPT), 'verify', str(root)],
                              cwd=root.parent, capture_output=True, text=True)

    def test_real_entry_accepts_intact_inputs_and_rejects_byte_changes_or_missing_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            self.assertEqual(self.run_entry(root).returncode, 0)
            (root / 'input.tar.gz').write_bytes(b'changed byte')
            self.assertNotEqual(self.run_entry(root).returncode, 0)
            (root / 'input.tar.gz').unlink()
            self.assertNotEqual(self.run_entry(root).returncode, 0)

    def test_extra_file_and_directory_symlink_cannot_enter_the_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            (root / 'extra').write_bytes(b'extra')
            self.assertNotEqual(self.run_entry(root).returncode, 0)
            (root / 'extra').unlink()
            (root / 'link').symlink_to(root.parent, target_is_directory=True)
            self.assertNotEqual(self.run_entry(root).returncode, 0)

    def test_manifest_cannot_read_outside_the_bundle_or_repeat_a_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            p = root / 'offline-manifest.json'
            manifest = json.loads(p.read_text())
            member = manifest['files'][0]
            manifest['files'].append(member)
            p.write_text(json.dumps(manifest))
            self.assertNotEqual(self.run_entry(root).returncode, 0)
            manifest['files'] = [dict(member, path='../input.tar.gz')]
            p.write_text(json.dumps(manifest))
            self.assertNotEqual(self.run_entry(root).returncode, 0)


if __name__ == '__main__':
    unittest.main()
