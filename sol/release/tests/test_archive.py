import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import archive, authority, manifest  # noqa: E402
from support import SOURCE, host_archive_target, make_stage, tools_for  # noqa: E402


class ArchiveReproducibilityTest(unittest.TestCase):
    def test_every_target_is_byte_identical_twice(self):
        data = authority.load()
        version = "1.2.2-sol.2"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in data.targets.values():
                with self.subTest(target=target["id"]):
                    fixture_target = host_archive_target(target)
                    outputs = []
                    for run in (1, 2):
                        run_root = root / f"{target['id']}-{run}"
                        run_root.mkdir()
                        stage = run_root / "stage"
                        stage.mkdir()
                        make_stage(stage, target)
                        artifact = run_root / target["archive_name"].format(
                            target=target["id"], version=version
                        )
                        archive.construct(
                            stage,
                            artifact,
                            fixture_target,
                            data.release,
                            SOURCE["source_date_epoch"],
                        )
                        artifact_sidecar = root / f"{artifact.name}.sha256"
                        archive.write_sidecar(artifact_sidecar, artifact)
                        value = manifest.build(
                            release=data.release,
                            target=target,
                            version=version,
                            source=SOURCE,
                            artifact_path=artifact,
                            dependencies=[],
                            build_tools=tools_for(target),
                        )
                        manifest_path = run_root / (
                            artifact.name.removesuffix(".tar.xz") + ".manifest.json"
                        )
                        manifest_sidecar = manifest.write(manifest_path, value)
                        outputs.append(
                            (
                                artifact.read_bytes(),
                                artifact_sidecar.read_bytes(),
                                manifest_path.read_bytes(),
                                manifest_sidecar.read_bytes(),
                            )
                        )
                    self.assertEqual(outputs[0], outputs[1])

    def test_ambient_xz_options_are_removed(self):
        data = authority.load()
        target = data.target(authority.TARGET_IDS[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            stage.mkdir()
            make_stage(stage, target)
            with mock.patch.dict(
                "os.environ", {"XZ_OPT": "--invalid", "XZ_DEFAULTS": "--invalid"}
            ):
                archive.construct(
                    stage,
                    root / "a.tar.xz",
                    host_archive_target(target),
                    data.release,
                    1,
                )


if __name__ == "__main__":
    unittest.main()
