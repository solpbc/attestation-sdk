import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import archive, authority, elf, fixtures, set_validator  # noqa: E402
from support import (  # noqa: E402
    SOURCE,
    host_archive_target,
    make_quartet,
    rewrite_manifest,
)


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

    def validate(self):
        return set_validator.validate(
            self.dist,
            self.data,
            self.version,
            expected_source_commit=SOURCE["commit"],
        )

    def test_accepts_exact_complete_set(self):
        result = self.validate()
        self.assertEqual(tuple(result), authority.TARGET_IDS)

    def test_missing_target_and_incomplete_quartet_fail(self):
        self.quartets[authority.TARGET_IDS[2]]["manifest"].unlink()
        self.quartets[authority.TARGET_IDS[2]]["manifest-sha256"].unlink()
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            "missing target: macos-arm64",
        ):
            self.validate()

    def test_all_missing_targets_are_named(self):
        for target_id in authority.TARGET_IDS[1:]:
            self.quartets[target_id]["manifest"].unlink()
            self.quartets[target_id]["manifest-sha256"].unlink()
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            "missing target: linux-aarch64; missing target: macos-arm64",
        ):
            self.validate()

    def test_each_missing_quartet_member_and_manifest_hash_fail(self):
        paths = self.quartets[authority.TARGET_IDS[1]]
        for key in ("archive", "archive-sha256", "manifest", "manifest-sha256"):
            with self.subTest(missing=key):
                path = paths[key]
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaises(set_validator.SetValidationError):
                    self.validate()
                path.write_bytes(contents)
        manifest_path = paths["manifest"]
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "quartet hash mismatch.*manifest sidecar"
        ):
            self.validate()

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
            self.validate()

    def test_duplicate_and_unknown_targets_fail(self):
        original = self.quartets[authority.TARGET_IDS[0]]["manifest"]
        duplicate = self.dist / "duplicate.manifest.json"
        shutil.copy2(original, duplicate)
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            f"duplicate target: {authority.TARGET_IDS[0]}",
        ):
            self.validate()
        duplicate.unlink()
        unknown = json.loads(original.read_text())
        unknown["target"]["id"] = "plan9-mips"
        extra = self.dist / "extra.manifest.json"
        extra.write_text(json.dumps(unknown), encoding="utf-8")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "unknown target: plan9-mips"
        ):
            self.validate()

    def test_extra_release_file_fails(self):
        extra = self.dist / f"libnvat-plan9-mips-{self.version}-archive.tar.xz"
        extra.write_bytes(b"extra")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, f"extra release file: {extra}"
        ):
            self.validate()

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
                "source.sol_series_commits",
                lambda value: value["source"].update(
                    sol_series_commits=[
                        {"commit": "7" * 40, "subject": "different"}
                    ]
                ),
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
                    self.validate()
                path.write_bytes(original)
                Path(f"{path}.sha256").write_bytes(original_sidecar)

    def test_all_targets_with_the_same_stale_source_commit_fail(self):
        stale = "9" * 40
        for paths in self.quartets.values():
            rewrite_manifest(
                paths["manifest"],
                lambda value: value["source"].update(commit=stale),
            )
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            rf"source identity mismatch: source.commit: expected.*{SOURCE['commit']}.*"
            rf"all targets.*{stale}",
        ):
            self.validate()

    def test_foreign_archived_binary_fails_with_consistent_hashes(self):
        target = self.data.target(authority.TARGET_IDS[1])
        paths = self.quartets[target["id"]]
        stage = self.dist / f"stage-{target['id']}"
        (stage / "bin/nvattest").write_bytes(
            fixtures.elf_fixture(elf.EM_X86_64)
        )
        archive.construct(
            stage,
            paths["archive"],
            host_archive_target(target),
            self.data.release,
            SOURCE["source_date_epoch"],
        )
        archive.write_sidecar(paths["archive-sha256"], paths["archive"])
        rewrite_manifest(
            paths["manifest"],
            lambda value: value["artifact"].update(
                size=paths["archive"].stat().st_size,
                sha256=archive.sha256(paths["archive"]),
            ),
        )
        with self.assertRaisesRegex(
            set_validator.SetValidationError,
            "static archive gate failed: linux-aarch64:.*wrong ELF architecture",
        ):
            self.validate()

    def test_wrong_hash_target_architecture_and_members_fail(self):
        archive_path = self.quartets[authority.TARGET_IDS[0]]["archive"]
        archive_path.write_bytes(archive_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "quartet hash mismatch"
        ):
            self.validate()

        self.tearDown()
        self.setUp()
        path = self.quartets[authority.TARGET_IDS[1]]["manifest"]
        rewrite_manifest(
            path, lambda value: value["target"].update(architecture="EM_X86_64")
        )
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "target.architecture"
        ):
            self.validate()

        self.tearDown()
        self.setUp()
        path = self.quartets[authority.TARGET_IDS[2]]["manifest"]
        rewrite_manifest(path, lambda value: value["archive_members"].pop())
        with self.assertRaisesRegex(
            set_validator.SetValidationError, "archive_members"
        ):
            self.validate()


if __name__ == "__main__":
    unittest.main()
