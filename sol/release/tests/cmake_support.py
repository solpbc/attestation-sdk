import json
import shlex
import subprocess
import tempfile
from pathlib import Path


def write_stub(path, content):
    path.mkdir(parents=True, exist_ok=True)
    (path / "CMakeLists.txt").write_text(content, encoding="utf-8")


def warning_fixture_prepare(state, missing_targets=()):
    missing_targets = set(missing_targets)

    def prepare(root):
        corrosion = root / "corrosion"
        write_stub(
            corrosion,
            "cmake_minimum_required(VERSION 3.11)\n"
            "function(corrosion_import_crate)\n"
            "  add_library(regorus_ffi STATIC IMPORTED GLOBAL)\n"
            '  set_target_properties(regorus_ffi PROPERTIES IMPORTED_LOCATION '
            '"${CMAKE_CURRENT_BINARY_DIR}/libregorus_ffi.a")\n'
            "  add_custom_target(cargo-build_regorus_ffi)\n"
            "endfunction()\n"
            "function(corrosion_set_env_vars)\n"
            "endfunction()\n",
        )
        regorus = root / "regorus"
        write_stub(regorus, "cmake_minimum_required(VERSION 3.11)\n")
        (regorus / "bindings/ffi").mkdir(parents=True)
        jwt = root / "jwt-cpp"
        write_stub(jwt, "cmake_minimum_required(VERSION 3.11)\n")
        (jwt / "include").mkdir()
        json_stub = root / "json"
        write_stub(
            json_stub,
            "cmake_minimum_required(VERSION 3.11)\n"
            "add_library(nlohmann_json INTERFACE)\n"
            "add_library(nlohmann_json::nlohmann_json ALIAS nlohmann_json)\n",
        )
        cli11 = root / "cli11"
        write_stub(
            cli11,
            "cmake_minimum_required(VERSION 3.11)\n"
            "add_library(CLI11 INTERFACE)\n"
            "add_library(CLI11::CLI11 ALIAS CLI11)\n",
        )
        compiled = {}
        for target in ("fmt", "spdlog"):
            stub = root / target
            target_definition = ""
            if target not in missing_targets:
                target_definition = (
                    f'file(WRITE "${{CMAKE_CURRENT_SOURCE_DIR}}/stub.cpp" '
                    f'"int {target}_stub() {{ return 0; }}\\n")\n'
                    f"add_library({target} STATIC stub.cpp)\n"
                    f'target_include_directories({target} PUBLIC '
                    '"${CMAKE_CURRENT_SOURCE_DIR}/include")\n'
                )
            write_stub(
                stub,
                "cmake_minimum_required(VERSION 3.11)\n" + target_definition,
            )
            (stub / "include").mkdir()
            compiled[target] = stub.resolve()
        state["third_party_roots"] = tuple(compiled.values())
        state["root"] = root
        arguments = [
            "-DUSE_SYSTEM_NVAT=OFF",
            "-DUSE_SYSTEM_DEPS=OFF",
            "-DBUILD_SHARED_LIBS=ON",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DFETCHCONTENT_SOURCE_DIR_CORROSION={corrosion}",
            f"-DFETCHCONTENT_SOURCE_DIR_REGORUS={regorus}",
            f"-DFETCHCONTENT_SOURCE_DIR_JWT-CPP={jwt}",
            f"-DFETCHCONTENT_SOURCE_DIR_JSON={json_stub}",
            f"-DFETCHCONTENT_SOURCE_DIR_FMT={compiled['fmt']}",
            f"-DFETCHCONTENT_SOURCE_DIR_SPDLOG={compiled['spdlog']}",
            f"-DFETCHCONTENT_SOURCE_DIR_CLI11={cli11}",
        ]
        return arguments, ""

    return prepare


def production_configure(
    source,
    *,
    fixture_prepare=None,
    build=None,
    configure_arguments=(),
    query_codemodel=False,
    export_compile_commands=False,
):
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    build = build or root / "build"
    event_log = root / "events.txt"
    extra_arguments = []
    project_include_content = ""
    if fixture_prepare is not None:
        extra_arguments, project_include_content = fixture_prepare(root)

    if query_codemodel:
        query = build / ".cmake/api/v1/query"
        query.mkdir(parents=True, exist_ok=True)
        (query / "codemodel-v2").touch()

    trace = root / "trace.json"
    source = source(root) if callable(source) else source
    arguments = [
        "cmake",
        "--trace-format=json-v1",
        f"--trace-redirect={trace}",
        "-S",
        str(source),
        "-B",
        str(build),
        "-DBUILD_TESTING=OFF",
    ]
    if project_include_content:
        project_include = root / "project-include.cmake"
        project_include.write_text(project_include_content, encoding="utf-8")
        arguments.append(f"-DCMAKE_PROJECT_INCLUDE={project_include}")
    if export_compile_commands:
        arguments.append("-DCMAKE_EXPORT_COMPILE_COMMANDS=ON")
    arguments.extend(configure_arguments)
    arguments.extend(extra_arguments)

    completed = subprocess.run(
        arguments, text=True, capture_output=True, check=False
    )
    records = load_trace(trace)
    return temporary, completed, event_log, records, build


def load_trace(path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("{")
    ]


def load_codemodel(build):
    reply = build / ".cmake/api/v1/reply"
    codemodel_paths = list(reply.glob("codemodel-v2-*.json"))
    if len(codemodel_paths) != 1:
        raise AssertionError(
            f"expected one codemodel-v2 reply, found {len(codemodel_paths)}"
        )
    codemodel = json.loads(codemodel_paths[0].read_text(encoding="utf-8"))
    configurations = codemodel.get("configurations", [])
    if len(configurations) != 1:
        raise AssertionError(
            f"expected one codemodel configuration, found {len(configurations)}"
        )
    targets = {}
    for reference in configurations[0].get("targets", []):
        target_path = reply / reference["jsonFile"]
        targets[reference["name"]] = json.loads(
            target_path.read_text(encoding="utf-8")
        )
    return codemodel, targets


def load_compile_commands(build):
    path = build / "compile_commands.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    for record in records:
        if "arguments" in record:
            record["arguments"] = list(record["arguments"])
        elif "command" in record:
            record["arguments"] = shlex.split(record["command"])
        else:
            raise AssertionError("compile command has neither command nor arguments")
    return records
