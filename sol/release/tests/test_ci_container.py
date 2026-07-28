import shlex
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import runtime  # noqa: E402


MAKEFILE = ROOT / "Makefile"
CONTAINERFILE = ROOT / "sol/ci/Containerfile"


def make_recipe(target):
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.startswith(f"{target}:")
    )
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line.removeprefix("\t"))
    return "\n".join(recipe)


def containerfile_instructions():
    instructions = []
    current = ""
    for raw_line in CONTAINERFILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        current = f"{current} {line}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        keyword, separator, body = current.partition(" ")
        instructions.append((keyword.upper(), body if separator else ""))
        current = ""
    if current:
        raise AssertionError("unterminated Containerfile instruction")
    return instructions


def env_assignments(body):
    assignments = {}
    for token in shlex.split(body):
        key, separator, value = token.partition("=")
        if not separator:
            raise AssertionError(f"unsupported ENV token: {token}")
        assignments[key] = value
    return assignments


class CiContainerTest(unittest.TestCase):
    def test_ci_container_consumes_run_args_with_status_guard(self):
        recipe = make_recipe("ci-container")
        assignment = 'RUN_ARGS="$$( $(RAIL) runtime run-args "$$RUNTIME" )"'
        invocation = '"$$RUNTIME" run --rm $$RUN_ARGS -v $(CURDIR):/src:Z'

        self.assertEqual(recipe.count("runtime run-args"), 1)
        self.assertIn(assignment, recipe)
        assignment_line = next(
            line for line in recipe.splitlines() if assignment in line
        )
        self.assertTrue(assignment_line.rstrip().endswith("&& \\"))
        self.assertIn(invocation, recipe)
        self.assertLess(recipe.index(assignment), recipe.index(invocation))
        self.assertNotIn("--platform", recipe)

    def test_ci_home_is_ignored_and_created_between_cleanup_and_configure(self):
        relative_home = PurePosixPath(runtime.CI_HOME).relative_to("/src")
        self.assertEqual(relative_home, PurePosixPath("build/.ci-home"))
        self.assertEqual(runtime.CI_CARGO_HOME, f"{runtime.CI_HOME}/.cargo")

        ignored = subprocess.run(
            [
                "git",
                "check-ignore",
                "-q",
                "--no-index",
                f"{relative_home}/marker",
            ],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(ignored.returncode, 0)

        recipe = make_recipe("ci-container")
        cleanup = recipe.index("rm -rf build")
        create_home = recipe.index(f"mkdir -p {relative_home}")
        configure = recipe.index("cmake -S $(CLI_DIR)")
        self.assertLess(cleanup, create_home)
        self.assertLess(create_home, configure)
        self.assertEqual(make_recipe("clean").strip(), "rm -rf build")

    def test_rustup_install_uses_non_root_readable_homes(self):
        instructions = containerfile_instructions()
        rustup_runs = [
            (index, body)
            for index, (keyword, body) in enumerate(instructions)
            if keyword == "RUN" and "https://sh.rustup.rs" in body
        ]
        self.assertEqual(len(rustup_runs), 1)
        run_index, run_body = rustup_runs[0]

        inherited = {}
        for keyword, body in instructions[:run_index]:
            if keyword == "ENV":
                inherited.update(env_assignments(body))
        self.assertEqual(inherited.get("RUSTUP_HOME"), "/usr/local/rustup")
        self.assertNotIn("CARGO_HOME", inherited)

        export_position = run_body.index("export CARGO_HOME=")
        install_position = run_body.index("https://sh.rustup.rs")
        chmod = 'chmod -R a+rX "$CARGO_HOME" "$RUSTUP_HOME"'
        chmod_position = run_body.index(chmod)
        self.assertLess(export_position, install_position)
        self.assertLess(install_position, chmod_position)

        before_install = shlex.split(run_body[:install_position])
        cargo_assignment = next(
            token for token in before_install if token.startswith("CARGO_HOME=")
        )
        effective = dict(inherited)
        effective["CARGO_HOME"] = cargo_assignment.partition("=")[2]
        for name in ("CARGO_HOME", "RUSTUP_HOME"):
            value = PurePosixPath(effective[name])
            self.assertTrue(value.is_absolute())
            self.assertNotEqual(value.parts[:2], ("/", "root"))

    def test_containerfile_limits_persistent_home_environment(self):
        instructions = containerfile_instructions()
        environment = []
        rustup_run_index = next(
            index
            for index, (keyword, body) in enumerate(instructions)
            if keyword == "RUN" and "https://sh.rustup.rs" in body
        )
        for index, (keyword, body) in enumerate(instructions):
            if keyword != "ENV":
                continue
            for name, value in env_assignments(body).items():
                environment.append((index, name, value))

        names = [name for _index, name, _value in environment]
        self.assertNotIn("HOME", names)
        self.assertNotIn("CARGO_HOME", names)
        self.assertEqual(names.count("RUSTUP_HOME"), 1)
        rustup_env_index, rustup_env_value = next(
            (index, value)
            for index, name, value in environment
            if name == "RUSTUP_HOME"
        )
        self.assertEqual(rustup_env_value, "/usr/local/rustup")
        self.assertLess(rustup_env_index, rustup_run_index)

        path_entries = [
            (index, value)
            for index, name, value in environment
            if name == "PATH"
        ]
        self.assertEqual(len(path_entries), 1)
        path_index, path_value = path_entries[0]
        self.assertGreater(path_index, rustup_run_index)
        self.assertEqual(path_value, "/usr/local/cargo/bin:${PATH}")


if __name__ == "__main__":
    unittest.main()
