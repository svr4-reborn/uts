#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose modern pack.d/<module>/Driver.o files from the generated uts_idconfig manifest.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--ld", default="ld")
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--include-dir", action="append", default=[])
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--report", required=True)
    return parser.parse_args()


def _compile_source(cc: str, cflags: list[str], include_dirs: list[str], source_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [cc, *cflags, *[f"-I{include_dir}" for include_dir in include_dirs], "-c", str(source_path), "-o", str(output_path)]
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


def main() -> int:
    args = _parse_args()
    manifest_path = Path(args.manifest).resolve()
    payload = json.loads(manifest_path.read_text())
    selected_modules = set(args.module)
    driver_packages = payload.get("driver_packages", [])
    report: dict[str, object] = {"built": [], "skipped": [], "missing_inputs": [], "failed": []}

    for package in driver_packages:
        if not isinstance(package, dict):
            continue
        name = str(package.get("name", ""))
        if selected_modules and name not in selected_modules:
            continue

        configured = bool(package.get("configured", False))
        declared_implementation_objects = [Path(path) for path in package.get("implementation_objects", [])]
        implementation_objects = [path for path in declared_implementation_objects if path.is_file()]
        missing_implementation_objects = [path for path in declared_implementation_objects if not path.is_file()]
        pack_dir = Path(str(package.get("pack_dir", "")))
        driver_object = Path(str(package.get("driver_object", "")))
        support_objects: list[Path] = []
        used_stub = False

        if declared_implementation_objects and missing_implementation_objects:
            casted_missing = report["missing_inputs"]
            assert isinstance(casted_missing, list)
            casted_missing.append(
                {
                    "name": name,
                    "configured": configured,
                    "mapping_strategy": package.get("mapping_strategy", "unknown"),
                    "sources": package.get("implementation_sources", []),
                    "missing_objects": [str(path) for path in missing_implementation_objects],
                    "present_objects": [str(path) for path in implementation_objects],
                }
            )
            continue

        stubs_c = package.get("stubs_c")
        if stubs_c and ((not configured) or not implementation_objects):
            stubs_path = Path(str(stubs_c))
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
                            "configured": configured,
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
            if driver_object.exists():
                driver_object.unlink()
            casted_missing = report["missing_inputs"]
            assert isinstance(casted_missing, list)
            casted_missing.append({
                "name": name,
                "configured": configured,
                "mapping_strategy": package.get("mapping_strategy", "unknown"),
                "sources": package.get("implementation_sources", []),
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
                    "configured": configured,
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
                "configured": configured,
                "driver_object": str(driver_object),
                "used_stub": used_stub,
                "inputs": [str(path) for path in link_inputs],
            }
        )

    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())