#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path


PACKAGE_SOURCE_RULES: dict[str, list[dict[str, object]]] = {
    "RFS": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["rfs/*.c"]}],
    "app": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["app.c"]}],
    "arp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["arp.c"]}],
    "bfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["bfs/*.c"]}],
    "coff": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["coff/coff.c"]}],
    "cmux": [{"source_root": "uts/arch/at/i386/io", "output_root": "io/core", "patterns": ["chanmux.c"]}],
    "des": [{"source_root": "uts/i386/des", "output_root": "des", "patterns": ["*.c"]}],
    "dosx": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["dosx/dosx.c"]}],
    "elf": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["elf/elf.c"]}],
    "fdfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["fdfs/*.c"]}],
    "fifofs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["fifofs/*.c"]}],
    "gdebugger": [{"source_root": "uts/i386/kdb/gdebugger", "output_root": "kdb/gdebugger", "patterns": ["*.c"]}],
    "gvid": [{"source_root": "uts/arch/at/i386/io", "output_root": "io/core", "patterns": ["genvid.c"]}],
    "hrt": [{"source_root": "uts/i386/io", "output_root": "io/core", "patterns": ["hrtimers.c"]}],
    "i286x": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["i286x/i286x.c"]}],
    "icmp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["ip_icmp.c"]}],
    "intp": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["intp/intp.c"]}],
    "ip": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["in.c", "in_cksum.c", "in_pcb.c", "in_switch.c", "in_transp.c", "ip_input.c", "ip_main.c", "ip_output.c", "ip_vers.c", "netlib.c", "route.c"]}],
    "kdb": [{"source_root": "uts/i386/kdb/kdb", "output_root": "kdb/core", "patterns": ["*.c"]}],
    "kdb-util": [{"source_root": "uts/i386/kdb/kdb-util", "output_root": "kdb/kdb-util", "patterns": ["*.c"]}],
    "kd": [{"source_root": "uts/arch/at/i386/io/kd", "output_root": "io/kd", "patterns": ["*.c"]}],
    "kdvm": [{"source_root": "uts/arch/at/i386/io/kdvm", "output_root": "io/kdvm", "patterns": ["*.c"]}],
    "klm": [{"source_root": "uts/i386/klm", "output_root": "klm", "patterns": ["*.c"]}],
    "krpc": [{"source_root": "uts/i386/rpc", "output_root": "rpc", "patterns": ["*.c"]}],
    "ktli": [{"source_root": "uts/i386/ktli", "output_root": "ktli", "patterns": ["*.c"]}],
    "llcloop": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["llcloop.c"]}],
    "m320": [{"source_root": "uts/arch/at/i386/io/mouse", "output_root": "io/mouse", "patterns": ["m320.c", "mse_subr.c"]}],
    "namefs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["namefs/*.c"]}],
    "nfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["nfs/*.c"]}],
    "pic": [{"source_root": "uts/i386/ml", "output_root": "ml", "patterns": ["pic.c"]}],
    "proc": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["proc/*.c"]}],
    "rawip": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["raw_ip.c", "raw_ip_cb.c", "raw_ip_main.c"]}],
    "rt": [{"source_root": "uts/i386/disp", "output_root": "disp", "patterns": ["rt.c"]}],
    "s5": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["s5/*.c"]}],
    "specfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["specfs/*.c"]}],
    "tcp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["tcp_*.c"]}],
    "ticotsor": [{"source_root": "uts/i386/io", "output_root": "io/core", "patterns": ["ticotsord.c"]}],
    "ts": [{"source_root": "uts/i386/disp", "output_root": "disp", "patterns": ["ts.c"]}],
    "udp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["udp_*.c"]}],
    "ufs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["ufs/*.c"]}],
    "vx": [{"source_root": "uts/i386/vx", "output_root": "vx", "patterns": ["*.c"]}],
    "ws": [{"source_root": "uts/i386/io/ws", "output_root": "io/ws", "patterns": ["*.c"]}],
    "xnamfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["xnamfs/*.c"]}],
    "xout": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["xout/xout.c"]}],
}

SINGLE_SOURCE_FALLBACKS: list[tuple[str, str]] = [
    ("uts/arch/at/i386/io", "io/core"),
    ("uts/i386/io", "io/core"),
    ("uts/i386/os", "os"),
    ("uts/i386/ml", "ml"),
    ("uts/i386/vx", "vx"),
    ("uts/i386/des", "des"),
    ("uts/i386/ktli", "ktli"),
    ("uts/i386/klm", "klm"),
    ("uts/i386/netinet", "netinet"),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose modern pack.d/<module>/Driver.o files from staged idtools metadata.")
    parser.add_argument("--conf-root", required=True)
    parser.add_argument("--obj-root", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--ld", default="ld")
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--cflags", action="append", default=[], help="Space-joined compiler flags; shell-split and appended to --cflag.")
    parser.add_argument("--include-dir", action="append", default=[])
    parser.add_argument("--include-dirs", action="append", default=[], help="Space-joined include directories; shell-split and appended to --include-dir.")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    args.cflag = _expand_joined(args.cflag, args.cflags)
    args.include_dir = _expand_joined(args.include_dir, args.include_dirs)
    return args


def _expand_joined(individual: list[str], joined: list[str]) -> list[str]:
    expanded = list(individual)
    for group in joined:
        expanded.extend(shlex.split(group))
    return expanded


def _compile_source(cc: str, cflags: list[str], include_dirs: list[str], source_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [cc, *cflags, *[f"-I{include_dir}" for include_dir in include_dirs], "-c", str(source_path), "-o", str(output_path)]
    subprocess.run(command, check=True, capture_output=True, text=True)


def _compile_empty_object(cc: str, cflags: list[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [cc, *cflags, "-x", "c", "-c", "/dev/null", "-o", str(output_path)]
    subprocess.run(command, check=True, capture_output=True, text=True)


def _link_driver(ld: str, input_paths: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    linker = ld
    command = [linker]
    if Path(ld).name == "ld":
        bfd_linker = shutil.which("ld.bfd")
        if bfd_linker is not None:
            linker = bfd_linker
        command = [linker, "-m", "elf_i386", "-Ur"]
    else:
        command = [linker, "-Ur"]
    command.extend(str(path) for path in input_paths)
    command.extend(["-o", str(output_path)])
    subprocess.run(command, check=True, capture_output=True, text=True)


def _metadata_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith(("#", "*")):
            lines.append(stripped)
    return lines


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _object_path_from_source(obj_root: Path, source_root: Path, output_root: str, source_path: Path) -> Path:
    return obj_root / output_root / source_path.relative_to(source_root).with_suffix(".o")


def _source_root(workspace_root: Path, source_root_text: str) -> Path:
    if source_root_text.startswith("uts/") and (workspace_root / "i386").is_dir():
        return workspace_root / source_root_text.removeprefix("uts/")
    return workspace_root / source_root_text


def _expand_rule(workspace_root: Path, obj_root: Path, rule: dict[str, object]) -> tuple[list[str], list[str]]:
    source_root = _source_root(workspace_root, str(rule["source_root"]))
    if not source_root.exists():
        return [], []
    sources: list[str] = []
    objects: list[str] = []
    for pattern in [str(pattern) for pattern in rule["patterns"]]:
        for source_path in sorted(source_root.glob(pattern)):
            if not source_path.is_file():
                continue
            source_path = source_path.resolve()
            sources.append(str(source_path))
            objects.append(str(_object_path_from_source(obj_root, source_root, str(rule["output_root"]), source_path).resolve()))
    return sources, objects


def _single_source_mapping(workspace_root: Path, obj_root: Path, module_name: str, handler_name: str) -> tuple[list[str], list[str], str | None]:
    for source_root_text, output_root in SINGLE_SOURCE_FALLBACKS:
        source_root = _source_root(workspace_root, source_root_text)
        if not source_root.exists():
            continue
        for candidate in _unique([module_name, handler_name]):
            source_path = (source_root / f"{candidate}.c").resolve()
            if source_path.is_file():
                return [str(source_path)], [str(_object_path_from_source(obj_root, source_root, output_root, source_path).resolve())], "single-source"
    return [], [], None


def _resolve_package_implementation(workspace_root: Path, obj_root: Path, module_name: str, handler_name: str) -> tuple[list[str], list[str], str]:
    rules = PACKAGE_SOURCE_RULES.get(module_name, [])
    if rules:
        sources: list[str] = []
        objects: list[str] = []
        for rule in rules:
            rule_sources, rule_objects = _expand_rule(workspace_root, obj_root, rule)
            sources.extend(rule_sources)
            objects.extend(rule_objects)
        return _unique(sources), _unique(objects), "explicit"
    sources, objects, strategy = _single_source_mapping(workspace_root, obj_root, module_name, handler_name)
    return sources, objects, strategy or "unmapped"


def _read_packages(cf_dir: Path) -> list[tuple[str, str]]:
    packages: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in _metadata_lines(cf_dir / "mdevice"):
        parts = line.split()
        if len(parts) >= 4 and parts[0] not in seen:
            seen.add(parts[0])
            packages.append((parts[0], parts[3]))
    for line in _metadata_lines(cf_dir / "mfsys"):
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in seen:
            seen.add(parts[0])
            packages.append((parts[0], parts[1]))
    return packages


def _link_relocatable(ld: str, input_paths: list[Path], output_path: Path) -> None:
    _link_driver(ld, input_paths, output_path)


def main() -> int:
    args = _parse_args()
    conf_root = Path(args.conf_root).resolve()
    cf_dir = conf_root / "cf.d"
    obj_root = Path(args.obj_root).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    selected_modules = set(args.module)
    report: dict[str, object] = {"built": [], "skipped": [], "missing_inputs": [], "failed": []}
    packaged_objects: set[Path] = set()

    for name, handler in _read_packages(cf_dir):
        if selected_modules and name not in selected_modules:
            continue

        implementation_sources, declared_objects, mapping_strategy = _resolve_package_implementation(workspace_root, obj_root, name, handler)
        declared_implementation_objects = [Path(path) for path in declared_objects]
        implementation_objects = [path for path in declared_implementation_objects if path.is_file()]
        missing_implementation_objects = [path for path in declared_implementation_objects if not path.is_file()]
        pack_dir = conf_root / "pack.d" / name
        driver_object = pack_dir / "Driver.o"
        support_objects: list[Path] = []
        used_stub = False
        used_empty = False

        if declared_implementation_objects and missing_implementation_objects:
            casted_missing = report["missing_inputs"]
            assert isinstance(casted_missing, list)
            casted_missing.append(
                {
                    "name": name,
                    "mapping_strategy": mapping_strategy,
                    "sources": implementation_sources,
                    "missing_objects": [str(path) for path in missing_implementation_objects],
                    "present_objects": [str(path) for path in implementation_objects],
                }
            )
            continue

        stubs_path = pack_dir / "stubs.c"
        if stubs_path.is_file() and not implementation_objects:
            if stubs_path.is_file():
                stub_object = pack_dir / "Stubs.o"
                try:
                    _compile_source(args.cc, list(args.cflag), list(args.include_dir), stubs_path, stub_object)
                except subprocess.CalledProcessError as exc:
                    casted_failed = report["failed"]
                    assert isinstance(casted_failed, list)
                    casted_failed.append(
                        {
                            "name": name,
                            "stage": "compile-stubs",
                            "source": str(stubs_path),
                            "stderr": exc.stderr,
                        }
                    )
                    continue
                support_objects.append(stub_object)
                used_stub = True

        link_inputs = [*implementation_objects, *support_objects]
        if not link_inputs:
            if (pack_dir / "space.c").is_file():
                try:
                    _compile_empty_object(args.cc, list(args.cflag), driver_object)
                except subprocess.CalledProcessError as exc:
                    casted_failed = report["failed"]
                    assert isinstance(casted_failed, list)
                    casted_failed.append(
                        {
                            "name": name,
                            "stage": "compile-empty-driver",
                            "driver_object": str(driver_object),
                            "stderr": exc.stderr,
                        }
                    )
                    continue
                used_empty = True
            elif driver_object.exists():
                driver_object.unlink()
            if used_empty:
                casted_built = report["built"]
                assert isinstance(casted_built, list)
                casted_built.append(
                    {
                        "name": name,
                        "driver_object": str(driver_object),
                        "used_empty": True,
                        "inputs": [],
                    }
                )
                continue
            casted_missing = report["missing_inputs"]
            assert isinstance(casted_missing, list)
            casted_missing.append({
                "name": name,
                "mapping_strategy": mapping_strategy,
                "sources": implementation_sources,
            })
            continue

        try:
            _link_driver(args.ld, link_inputs, driver_object)
        except subprocess.CalledProcessError as exc:
            casted_failed = report["failed"]
            assert isinstance(casted_failed, list)
            casted_failed.append(
                {
                    "name": name,
                    "stage": "link-driver",
                    "driver_object": str(driver_object),
                    "inputs": [str(path) for path in link_inputs],
                    "stderr": exc.stderr,
                }
            )
            continue
        casted_built = report["built"]
        assert isinstance(casted_built, list)
        casted_built.append(
            {
                "name": name,
                "driver_object": str(driver_object),
                "used_stub": used_stub,
                "used_empty": used_empty,
                "inputs": [str(path) for path in link_inputs],
            }
        )
        packaged_objects.update(path.resolve() for path in implementation_objects)

    core_objects = [
        path.resolve()
        for path in sorted(obj_root.rglob("*.o"))
        if path.resolve() not in packaged_objects and obj_root / "ml" not in path.resolve().parents
    ]
    if core_objects:
        kernel_object = conf_root / "pack.d" / "kernel" / "kernel.o"
        _link_relocatable(args.ld, core_objects, kernel_object)
        casted_built = report["built"]
        assert isinstance(casted_built, list)
        casted_built.append({"name": "kernel", "driver_object": str(kernel_object), "inputs": [str(path) for path in core_objects]})

    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
