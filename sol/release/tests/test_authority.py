import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority  # noqa: E402


class AuthorityTest(unittest.TestCase):
    def load_mutated(self, mutator):
        source = authority.load().path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.toml"
            path.write_text(mutator(source), encoding="utf-8")
            return authority.load(path)

    def test_landed_authority_is_complete(self):
        data = authority.load()
        self.assertEqual(tuple(data.targets), authority.TARGET_IDS)
        self.assertEqual(
            data.targets[authority.TARGET_IDS[0]]["build_image"],
            "quay.io/pypa/manylinux_2_28_x86_64@sha256:"
            "a61875a2f84cab7df8de222ff12cabc08ff86eb4ad402ac90ba7bdaed9600cca",
        )
        self.assertNotIn("openssl_configure_target", data.targets[authority.TARGET_IDS[0]])
        self.assertIn("required_tools", data.targets["macos-arm64"])
        self.assertNotIn("required_tool_versions", data.targets["macos-arm64"])
        self.assertEqual(data.release["sol_revision"], 2)
        self.assertRegex(data.release["upstream_base_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            data.targets["macos-arm64"]["macho_install_id"],
            "@rpath/libnvat.1.dylib",
        )

    def test_host_selection_and_incompatible_target_fail_closed(self):
        data = authority.load()
        self.assertEqual(data.compatible_target("Linux", "x86_64"), authority.TARGET_IDS[0])
        self.assertEqual(data.compatible_target("Linux", "aarch64"), authority.TARGET_IDS[1])
        self.assertEqual(data.compatible_target("Darwin", "arm64"), authority.TARGET_IDS[2])
        with self.assertRaisesRegex(
            authority.AuthorityError, f"compatible target: {authority.TARGET_IDS[0]}"
        ):
            data.require_compatible("macos-arm64", "Linux", "x86_64")

    def test_unknown_host_names_valid_targets(self):
        with self.assertRaisesRegex(
            authority.AuthorityError,
            "unsupported release host Plan9/mips; valid targets: "
            + ", ".join(authority.TARGET_IDS),
        ):
            authority.load().compatible_target("Plan9", "mips")

    def test_duplicate_target_is_rejected(self):
        source = authority.load().path.read_text(encoding="utf-8")
        duplicate = source + "\n" + source[source.index("[[targets]]") :]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.toml"
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(authority.AuthorityError, "duplicate target"):
                authority.load(path)

    def test_unknown_field_is_rejected(self):
        source = authority.load().path.read_text(encoding="utf-8")
        source = source.replace("sol_revision = 2", "sol_revision = 2\nsurprise = true")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.toml"
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(authority.AuthorityError, "unknown fields: surprise"):
                authority.load(path)

    def test_upstream_base_pin_is_required_and_validated(self):
        line = "upstream_base_commit = "
        landed = authority.load().release["upstream_base_commit"]
        cases = (
            (
                "missing",
                lambda source: "\n".join(
                    row for row in source.splitlines() if not row.startswith(line)
                )
                + "\n",
                "release is missing fields: upstream_base_commit",
            ),
            (
                "short",
                lambda source: source.replace(
                    f'{line}"{landed}"', f'{line}"{landed[:-1]}"'
                ),
                "release.upstream_base_commit must be 40 lowercase hex digits",
            ),
            (
                "uppercase",
                lambda source: source.replace(
                    f'{line}"{landed}"', f'{line}"{landed.upper()}"'
                ),
                "release.upstream_base_commit must be 40 lowercase hex digits",
            ),
            (
                "non-hex",
                lambda source: source.replace(
                    f'{line}"{landed}"', f'{line}"{"g" * 40}"'
                ),
                "release.upstream_base_commit must be 40 lowercase hex digits",
            ),
            (
                "non-string",
                lambda source: source.replace(
                    f'{line}"{landed}"', f"{line}{'1' * 40}"
                ),
                "release.upstream_base_commit must be 40 lowercase hex digits",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(authority.AuthorityError, message):
                    self.load_mutated(mutate)

    def test_macos_floor_and_architecture_are_fail_closed(self):
        cases = (
            (
                lambda source: source.replace(
                    'abi_floor = { macos = "14.0" }',
                    'abi_floor = { macos = "latest" }',
                ),
                "abi_floor.macos must be a dotted numeric version",
            ),
            (
                lambda source: source.replace(
                    'expected_arch = "CPU_TYPE_ARM64"',
                    'expected_arch = "EM_AARCH64"',
                ),
                "expected_arch must be CPU_TYPE_ARM64",
            ),
        )
        for mutate, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(authority.AuthorityError, message):
                    self.load_mutated(mutate)

    def test_accessor_reports_incompatible_forced_target(self):
        result = subprocess.run(
            [
                sys.executable,
                str(RELEASE_DIR / "rail.py"),
                "authority",
                "build-image",
                "macos-arm64",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("incompatible with host", result.stderr)
        self.assertIn(
            f"retry with HOST_TARGET={authority.TARGET_IDS[0]}", result.stderr
        )


if __name__ == "__main__":
    unittest.main()
