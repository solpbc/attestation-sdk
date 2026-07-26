import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import archive, authority, set_validator  # noqa: E402
from support import make_quartet, rewrite_manifest  # noqa: E402


class SetValidatorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.dist = Path(self.temporary.name)
        self.data = authority.load()
        self.version = "1.2.2-sol.2"
        self.quartets = {
            target_id: make_quartet(
                self.dist, self.data, target, self.version
            )
            for target_id, target in self.data.targets.items()
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_accepts_exact_complete_set(self):
        result = set_validator.validate(self.dist, self.data, self.version)
        self.assertEqual(tuple(result), authority.TARGET_IDS)

    def test_missing_target_and_incomplete_quartet_fail(self):
        self.quartets[authority.TARGET_IDS[2]]["manifest"].unlink()
        self.quartets[authority.TARGET_IDS[2]]["manifest-sha256"].unlink()
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            "missing target: macos-arm64",
        ):
            set_validator.validate(self.dist, self.data, self.version)

    def test_all_missing_targets_are_named(self):
        for target_id in authority.TARGET_IDS[1:]:
            self.quartets[target_id]["manifest"].unlink()
            self.quartets[target_id]["manifest-sha256"].unlink()
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            "missing target: linux-aarch64; missing target: macos-arm64",
        ):
            set_validator.validate(self.dist, self.data, self.version)

    def test_each_missing_quartet_member_and_manifest_hash_fail(self):
        paths = self.quartets[authority.TARGET_IDS[1]]
        for key in ("archive", "archive-sha256", "manifest", "manifest-sha256"):
            with self.subTest(missing=key):
                path = paths[key]
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaises(set_validator.SetValidationError):
                    set_validator.validate(self.dist, self.data, self.version)
                path.write_bytes(contents)
        manifest_path = paths["manifest"]
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "quartet hash mismatch.*manifest sidecar"
        ):
            set_validator.validate(self.dist, self.data, self.version)

        make_quartet(
            self.dist,
            self.data,
            self.data.target(authority.TARGET_IDS[2]),
            self.version,
        )
        self.quartets[authority.TARGET_IDS[1]]["archive-sha256"].unlink()
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            "incomplete quartet: linux-aarch64: missing",
        ):
            set_validator.validate(self.dist, self.data, self.version)

    def test_duplicate_and_unknown_targets_fail(self):
        original = self.quartets[authority.TARGET_IDS[0]]["manifest"]
        duplicate = self.dist / "duplicate.manifest.json"
        shutil.copy2(original, duplicate)
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            f"duplicate target: {authority.TARGET_IDS[0]}",
        ):
            set_validator.validate(self.dist, self.data, self.version)
        duplicate.unlink()
        unknown = json.loads(original.read_text())
        unknown["target"]["id"] = "plan9-mips"
        extra = self.dist / "extra.manifest.json"
        extra.write_text(json.dumps(unknown), encoding="utf-8")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "unknown target: plan9-mips"
        ):
            set_validator.validate(self.dist, self.data, self.version)

    def test_extra_release_file_fails(self):
        extra = self.dist / f"libnvat-plan9-mips-{self.version}-archive.tar.xz"
        extra.write_bytes(b"extra")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, f"extra release file: {extra}"
        ):
            set_validator.validate(self.dist, self.data, self.version)

    def test_cross_target_mismatches_name_field_targets_and_values(self):
        cases = (
            ("release.sol_revision", lambda value: value["release"].update(sol_revision=99)),
            (
                "source.upstream_base_commit",
                lambda value: value["source"].update(upstream_base_commit="9" * 40),
            ),
            (
                "source.source_date_epoch",
                lambda value: value["source"].update(source_date_epoch=42),
            ),
            (
                "source.commit",
                lambda value: value["source"].update(commit="8" * 40),
            ),
        )
        for field, mutate in cases:
            with self.subTest(field=field):
                path = self.quartets[authority.TARGET_IDS[1]]["manifest"]
                original = path.read_bytes()
                original_sidecar = Path(f"{path}.sha256").read_bytes()
                rewrite_manifest(path, mutate)
                with self.assertRaisesRegex(
                    set_validator.SetValidationError,
                    rf"cross-target mismatch: {field}:.*"
                    rf"{authority.TARGET_IDS[0]}=.*{authority.TARGET_IDS[1]}=",
                ):
                    set_validator.validate(self.dist, self.data, self.version)
                path.write_bytes(original)
                Path(f"{path}.sha256").write_bytes(original_sidecar)

    def test_wrong_hash_target_architecture_and_members_fail(self):
        archive_path = self.quartets[authority.TARGET_IDS[0]]["archive"]
        archive_path.write_bytes(archive_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "quartet hash mismatch"
        ):
            set_validator.validate(self.dist, self.data, self.version)

        self.tearDown()
        self.setUp()
        path = self.quartets[authority.TARGET_IDS[1]]["manifest"]
        rewrite_manifest(
            path, lambda value: value["target"].update(architecture="EM_X86_64")
        )
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "target.architecture"
        ):
            set_validator.validate(self.dist, self.data, self.version)

        self.tearDown()
        self.setUp()
        path = self.quartets[authority.TARGET_IDS[2]]["manifest"]
        rewrite_manifest(path, lambda value: value["archive_members"].pop())
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "archive_members"
        ):
            set_validator.validate(self.dist, self.data, self.version)


if __name__ == "__main__":
    unittest.main()
