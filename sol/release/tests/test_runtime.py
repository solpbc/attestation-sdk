import subprocess
import sys
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, runtime  # noqa: E402


class RuntimeTest(unittest.TestCase):
    def result(self, stdout="", returncode=0, stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def fields(self, *values):
        return runtime.FIELD_SEPARATOR.join(values) + "\n"

    def outputs(self):
        return {
            runtime.PODMAN_VERSION: self.result(
                f"Client:       {runtime.PODMAN_PRODUCT}\n"
                "Version:      5.8.3\n"
                "API Version:  5.8.3\n"
                "OS/Arch:      linux/amd64\n"
            ),
            runtime.PODMAN_VERSION_FIELDS: self.result(
                self.fields("5.8.3", "5.8.3", "linux", "linux/amd64")
            ),
            runtime.PODMAN_INFO: self.result(
                self.fields("5.8.3", "linux", "amd64", "true")
            ),
            runtime.DOCKER_VERSION: self.result(
                self.fields(
                    "Docker CLI",
                    "28.5.1",
                    "Docker Desktop 4.50.0 (build)",
                    "28.5.1",
                    "linux",
                    "amd64",
                )
            ),
            runtime.DOCKER_INFO: self.result(
                self.fields("28.5.1", "linux", "amd64")
            ),
            runtime.DOCKER_ENDPOINT: self.result("unix:///var/run/docker.sock\n"),
        }

    def runner(self, outputs):
        def run(arguments, **_kwargs):
            return outputs[tuple(arguments)]

        return run

    def target(self):
        return authority.load().target(authority.TARGET_IDS[0])

    def test_podman_wins_when_both_are_available(self):
        selection = runtime.select(
            self.target(),
            which=lambda _name: "/runtime",
            runner=self.runner(self.outputs()),
            environment={},
        )
        self.assertEqual(selection.name, runtime.RUNTIME_NAMES[0])

    def test_absent_or_broken_podman_falls_back_to_usable_docker(self):
        for state in ("absent", "broken"):
            with self.subTest(state=state):
                outputs = self.outputs()
                if state == "broken":
                    outputs[runtime.PODMAN_INFO] = self.result(
                        returncode=125, stderr="engine unavailable"
                    )
                selection = runtime.select(
                    self.target(),
                    which=lambda name: None
                    if state == "absent" and name == runtime.PODMAN
                    else "/runtime",
                    runner=self.runner(outputs),
                    environment={},
                )
                self.assertEqual(selection.name, runtime.DOCKER)
                self.assertEqual(
                    selection.evidence["client"]["name"], runtime.DOCKER_PRODUCT
                )
                self.assertEqual(
                    selection.evidence["engine"]["name"], runtime.DOCKER_PRODUCT
                )
                self.assertEqual(selection.evidence["client"]["version"], "28.5.1")
                self.assertEqual(selection.evidence["engine"]["version"], "28.5.1")

    def test_neither_available_names_both_commands_and_recovery(self):
        with self.assertRaisesRegex(
            runtime.RuntimeSelectionError,
            rf"{runtime.PODMAN}: command not found.*{runtime.DOCKER}: command not found"
            ".*installing a working Podman or local Unix-socket Docker engine",
        ):
            runtime.select(self.target(), which=lambda _name: None)

    def test_wrong_product_malformed_and_inaccessible_engine_fail_closed(self):
        cases = {
            "wrong-product": (runtime.PODMAN_VERSION, self.result("Client: Other\n")),
            "malformed": (runtime.PODMAN_INFO, self.result("bad\n")),
            "inaccessible": (
                runtime.PODMAN_INFO,
                self.result(returncode=125, stderr="unavailable"),
            ),
        }
        for label, (command, result) in cases.items():
            with self.subTest(case=label):
                outputs = self.outputs()
                outputs[command] = result
                with self.assertRaisesRegex(
                    runtime.RuntimeSelectionError,
                    rf"{runtime.PODMAN}:.*{runtime.DOCKER}: command not found",
                ):
                    runtime.select(
                        self.target(),
                        which=lambda name: "/runtime"
                        if name == runtime.PODMAN
                        else None,
                        runner=self.runner(outputs),
                    )

    def test_docker_remote_endpoint_and_architecture_mismatch_fail(self):
        outputs = self.outputs()
        outputs[runtime.DOCKER_ENDPOINT] = self.result("ssh://builder\n")
        with self.assertRaisesRegex(
            runtime.RuntimeSelectionError, "endpoint is not local-unix compatible"
        ):
            runtime.select(
                self.target(),
                which=lambda name: "/runtime" if name == runtime.DOCKER else None,
                runner=self.runner(outputs),
                environment={},
            )

        for endpoint, succeeds in (
            ("ssh://remote", False),
            ("unix://", False),
            ("unix:///run/user/1000/docker.sock", True),
        ):
            with self.subTest(docker_host=endpoint):
                arguments = {
                    "target": self.target(),
                    "which": lambda name: "/runtime"
                    if name == runtime.DOCKER
                    else None,
                    "runner": self.runner(self.outputs()),
                    "environment": {
                        "DOCKER_CONTEXT": "local-context",
                        "DOCKER_HOST": endpoint,
                    },
                }
                if succeeds:
                    self.assertEqual(
                        runtime.select(**arguments).name, runtime.DOCKER
                    )
                else:
                    with self.assertRaisesRegex(
                        runtime.RuntimeSelectionError,
                        "endpoint is not local-unix compatible",
                    ):
                        runtime.select(**arguments)

        outputs = self.outputs()
        outputs[runtime.PODMAN_VERSION_FIELDS] = self.result(
            self.fields("5.8.3", "5.8.3", "linux", "linux/arm64")
        )
        outputs[runtime.PODMAN_INFO] = self.result(
            self.fields("5.8.3", "linux", "arm64", "true")
        )
        with self.assertRaisesRegex(
            runtime.RuntimeSelectionError, "engine architecture.*incompatible"
        ):
            runtime.select(
                self.target(),
                which=lambda name: "/runtime" if name == runtime.PODMAN else None,
                runner=self.runner(outputs),
            )

    def test_format_strings_never_contain_tabs_and_use_field_separator(self):
        self.assertEqual(runtime.FIELD_SEPARATOR, "|")
        commands = (
            (runtime.PODMAN_VERSION_FIELDS, 4),
            (runtime.PODMAN_INFO, 4),
            (runtime.DOCKER_VERSION, 6),
            (runtime.DOCKER_INFO, 3),
        )
        for command, field_count in commands:
            with self.subTest(command=command[:2]):
                format_body = command[command.index("--format") + 1]
                self.assertNotIn("\t", format_body)
                self.assertEqual(
                    format_body.count(runtime.FIELD_SEPARATOR), field_count - 1
                )

    def test_mount_rendering_and_validation(self):
        source = Path("/host/source")
        destination = Path("/container/destination")
        self.assertEqual(
            runtime.render_mount(source, destination, False),
            f"{source}:{destination}:{runtime.MOUNT_RW_SUFFIX}",
        )
        self.assertEqual(
            runtime.render_mount(source, destination, True),
            f"{source}:{destination}:{runtime.MOUNT_RO_SUFFIX}",
        )
        with self.assertRaises(runtime.RuntimeSelectionError):
            runtime.render_mount("relative", destination, False)


if __name__ == "__main__":
    unittest.main()
