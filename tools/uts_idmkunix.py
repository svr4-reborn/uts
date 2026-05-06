#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _normalize_option_values(argv: list[str] | None, option_names: set[str]) -> list[str] | None:
    if argv is None:
        argv = sys.argv[1:]
    normalized: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in option_names and index + 1 < len(argv):
            normalized.append(f"{token}={argv[index + 1]}")
            index += 2
            continue
        normalized.append(token)
        index += 1
    return normalized


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = _normalize_option_values(argv, {"--cflag", "--include-dir"})
    parser = argparse.ArgumentParser(description="Build the AT386 unix image from the modern manifest-driven config outputs.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--ld", required=True)
    parser.add_argument("--output")
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--include-dir", action="append", default=[])
    return parser.parse_args(argv)


def _run(argv: list[str], cwd: Path | None = None) -> None:
    subprocess.run(argv, cwd=cwd, check=True)


def _compile_source(source_path: Path, object_path: Path, cc: str, cflags: list[str], include_dirs: list[str]) -> Path:
    object_path.parent.mkdir(parents=True, exist_ok=True)
    command = [cc, *cflags]
    for include_dir in include_dirs:
        command.append(f"-I{include_dir}")
    command.extend(["-c", str(source_path), "-o", str(object_path)])
    _run(command)
    return object_path


def _compile_entry(entry_path: Path, cc: str, cflags: list[str], include_dirs: list[str]) -> Path | None:
    if not entry_path.exists():
        return None
    if entry_path.suffix != ".c":
        return entry_path
    return _compile_source(entry_path, entry_path.with_suffix(".o"), cc, cflags, include_dirs)


def _append_unique(entries: list[Path], seen: set[Path], candidate: Path | None) -> None:
    if candidate is None:
        return
    resolved = candidate.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    entries.append(resolved)


def _gather_core_objects(pack_dir: Path, cc: str, cflags: list[str], include_dirs: list[str]) -> list[Path]:
    entries: list[Path] = []
    seen: set[Path] = set()
    for name in ("syms.o", "start.o", "locore.o"):
        candidate = pack_dir / name
        if candidate.exists():
            _append_unique(entries, seen, candidate)

    space_c = pack_dir / "space.c"
    if space_c.exists():
        _append_unique(entries, seen, _compile_entry(space_c, cc, cflags, include_dirs))

    driver_o = pack_dir / "Driver.o"
    if driver_o.exists():
        _append_unique(entries, seen, driver_o)
    else:
        stubs_c = pack_dir / "stubs.c"
        if stubs_c.exists():
            _append_unique(entries, seen, _compile_entry(stubs_c, cc, cflags, include_dirs))

    for name in ("os.o", "io.o", "fs.o", "vm.o"):
        candidate = pack_dir / name
        if candidate.exists():
            _append_unique(entries, seen, candidate)
    return entries


def _read_direct_entries(direct_path: Path) -> list[Path]:
    if not direct_path.exists():
        return []
    entries: list[Path] = []
    for raw_line in direct_path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        entries.append(Path(stripped))
    return entries


def _read_core_link_objects(manifest: dict[str, object]) -> list[Path]:
    return [Path(str(object_path)).resolve() for object_path in manifest.get("core_link_objects", [])]


def _link_unix(
    cf_dir: Path,
    output_path: Path,
    ld: str,
    object_paths: list[Path],
    conf_o: Path,
    fsconf_o: Path,
    vector_o: Path,
) -> None:
    filtered_object_paths = [
        path
        for path in object_paths
        if path.as_posix() not in {
            (cf_dir.parent / "pack.d" / "kernel" / "start.o").as_posix(),
            (cf_dir.parent / "pack.d" / "kernel" / "locore.o").as_posix(),
        }
    ]
    linker = ld
    if Path(ld).name == "ld":
        bfd_linker = shutil.which("ld.bfd")
        if bfd_linker is not None:
            linker = bfd_linker
    command = [
        linker,
        "-m",
        "elf_i386",
        "-dn",
        "-o",
        str(output_path),
        "-e",
        "_start",
        "-T",
        str(cf_dir / "vuifile"),
        *(str(path) for path in filtered_object_paths),
        str(conf_o),
        str(fsconf_o),
        str(vector_o),
    ]
    _run(command, cwd=cf_dir)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text())

    cf_dir = Path(manifest["cf_dir"]).resolve()
    pack_root = Path(manifest["pack_root"]).resolve()
    generated_files = manifest.get("generated_files", {})
    output_path = Path(args.output).resolve() if args.output else (cf_dir / "unix")
    include_dirs = [str(Path(include_dir).resolve()) for include_dir in args.include_dir]

    conf_o = _compile_source(cf_dir / "conf.c", cf_dir / "conf.o", args.cc, args.cflag, include_dirs)
    fsconf_o = _compile_source(cf_dir / "fsconf.c", cf_dir / "fsconf.o", args.cc, args.cflag, include_dirs)
    vector_o = _compile_source(cf_dir / "vector.c", cf_dir / "vector.o", args.cc, args.cflag, include_dirs)

    link_inputs: list[Path] = []
    seen_inputs: set[Path] = set()
    for core_name in ("kernel", "pic"):
        for entry in _gather_core_objects(pack_root / core_name, args.cc, args.cflag, include_dirs):
            _append_unique(link_inputs, seen_inputs, entry)

    direct_path = Path(generated_files.get("direct", cf_dir / "direct")).resolve()
    for direct_entry in _read_direct_entries(direct_path):
        resolved_entry = _compile_entry(direct_entry.resolve(), args.cc, args.cflag, include_dirs)
        _append_unique(link_inputs, seen_inputs, resolved_entry)

    for additional_object in _read_core_link_objects(manifest):
        _append_unique(link_inputs, seen_inputs, additional_object)

    _link_unix(cf_dir, output_path, args.ld, link_inputs, conf_o, fsconf_o, vector_o)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())