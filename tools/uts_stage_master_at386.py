#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


ID_DIRS = [
    "init.d",
    "mfsys.d",
    "node.d",
    "rc.d",
    "sd.d",
    "mdevice.d",
    "sdevice.d",
    "sfsys.d",
]

CFFILES = ["mdevice", "sassign", "stune", "mtune", "init.base"]
STD_CONF_FILES = ["mfsys", "sfsys", "node", "rc", "sd", "init"]

COMMODS = [
    "nfs",
    "fp",
    "gentty",
    "kernel",
    "weitek",
    "mem",
    "merge",
    "osm",
    "async",
    "ldterm",
    "ansi",
    "char",
    "sad",
    "events",
    "nmi",
    "shm",
    "sem",
    "ipc",
    "msg",
    "pic",
    "specfs",
    "fifofs",
    "fdfs",
    "kma",
    "kmacct",
    "hrt",
    "nfa",
    "prf",
    "sxt",
    "nsxt",
    "xt",
    "nxt",
    "cpyrt",
    "pipemod",
    "ttcompat",
    "s5",
    "ufs",
    "xnamfs",
    "RFS",
    "namefs",
    "bfs",
    "elf",
    "coff",
    "xout",
    "intp",
    "i286x",
    "dosx",
    "rt",
    "ts",
    "clist",
    "connld",
    "gendisp",
    "proc",
    "rmc",
    "xque",
    "ws",
    "sysmsg",
    "vx",
    "raio",
    "app",
    "arp",
    "clone",
    "des",
    "icmp",
    "ip",
    "klm",
    "krpc",
    "ktli",
    "llcloop",
    "log",
    "pckt",
    "ptem",
    "ptm",
    "pts",
    "ramd",
    "rawip",
    "sockmod",
    "tcp",
    "ticlts",
    "ticots",
    "ticotsor",
    "timod",
    "tirdwr",
    "udp",
    "gdebugger",
    "kdb",
    "kdb-util",
]

AT386MODS = ["asy", "dma", "rtc", "cram", "hd", "fd", "lp", "kd", "kdvm", "cmux", "gvid"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage the historical AT386 master.d tree into a synthetic conf tree.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--conf-root", required=True)
    parser.add_argument("--cpp", required=True)
    parser.add_argument("--cpp-flag", action="append", default=[])
    return parser.parse_args()


def _run_cpp(cpp: str, cpp_flags: list[str], source_text: str) -> str:
    with tempfile.TemporaryDirectory(prefix="svr4-master-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_path = temp_dir / "input.txt"
        output_path = temp_dir / "output.txt"
        input_path.write_text(source_text)
        subprocess.run([cpp, *cpp_flags, str(input_path), "-o", str(output_path)], check=True)
        return output_path.read_text()


def _filter_ident_and_blank(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("*ident") or stripped.startswith("#ident"):
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _preprocess_file(path: Path, cpp: str, cpp_flags: list[str]) -> str:
    return _run_cpp(cpp, cpp_flags, path.read_text())


def _preprocess_cf_file(path: Path, cpp: str, cpp_flags: list[str]) -> str:
    transformed_lines = []
    for line in path.read_text().splitlines():
        if line.startswith("# "):
            transformed_lines.append("+" + line[1:])
        else:
            transformed_lines.append(line)
    preprocessed = _run_cpp(cpp, cpp_flags, "\n".join(transformed_lines) + "\n")
    result_lines = []
    for line in preprocessed.splitlines():
        if not line.strip():
            continue
        if line.startswith("+"):
            result_lines.append("#" + line[1:])
        else:
            result_lines.append(line)
    return "\n".join(result_lines) + ("\n" if result_lines else "")


def _ensure_clean_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_module_sources(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_dir.glob("*.c")):
        shutil.copy2(source_path, destination_dir / source_path.name)


def _refresh_cf_mdevice(conf_root: Path) -> None:
    cf_mdevice = conf_root / "cf.d" / "mdevice"
    chunks: list[str] = []
    for path in sorted((conf_root / "mdevice.d").glob("*")):
        if path.is_file():
            chunks.append(path.read_text())

    cf_mdevice.write_text("".join(chunks))


def _stage_common_modules(workspace_root: Path, conf_root: Path, cpp: str, cpp_flags: list[str]) -> None:
    master_root = workspace_root / "uts/i386/master.d"
    cf_dir = conf_root / "cf.d"

    for name in CFFILES:
        source_path = master_root / name
        destination_path = cf_dir / name
        if source_path.exists():
            destination_path.write_text(_preprocess_cf_file(source_path, cpp, cpp_flags))
        elif destination_path.exists():
            destination_path.unlink()

    mdevice_chunks: list[str] = []
    for module in COMMODS:
        source_dir = master_root / module
        if not source_dir.is_dir():
            continue

        pack_dir = conf_root / "pack.d" / module
        _copy_module_sources(source_dir, pack_dir)

        for name in STD_CONF_FILES:
            source_path = source_dir / name
            if not source_path.exists():
                continue
            destination_path = conf_root / f"{name}.d" / module
            destination_path.write_text(_filter_ident_and_blank(_preprocess_file(source_path, cpp, cpp_flags)))

        mdev_path = source_dir / "mdev"
        if mdev_path.exists():
            rendered = _filter_ident_and_blank(_preprocess_file(mdev_path, cpp, cpp_flags))
            (conf_root / "mdevice.d" / module).write_text(rendered)
            if rendered:
                mdevice_chunks.append(rendered)

        sdev_path = source_dir / "sdev"
        if sdev_path.exists():
            rendered = _filter_ident_and_blank(_preprocess_file(sdev_path, cpp, cpp_flags))
            (conf_root / "sdevice.d" / module).write_text(rendered)

    _refresh_cf_mdevice(conf_root)


def _stage_at386_overlay(workspace_root: Path, conf_root: Path, cpp: str, cpp_flags: list[str]) -> None:
    overlay_root = workspace_root / "uts/arch/at/i386/master.d"
    for module in AT386MODS:
        source_dir = overlay_root / module
        if not source_dir.is_dir():
            continue

        pack_dir = conf_root / "pack.d" / module
        _copy_module_sources(source_dir, pack_dir)

        for name in ["mfsys", "sfsys", "node", "init"]:
            source_path = source_dir / name
            if not source_path.exists():
                continue
            destination_path = conf_root / f"{name}.d" / module
            destination_path.write_text(_filter_ident_and_blank(_preprocess_file(source_path, cpp, cpp_flags)))

        mdev_path = source_dir / "mdev"
        if mdev_path.exists():
            rendered = _filter_ident_and_blank(_preprocess_file(mdev_path, cpp, cpp_flags))
            if rendered:
                (conf_root / "mdevice.d" / module).write_text(rendered)

        sdev_path = source_dir / "sdev"
        if sdev_path.exists():
            rendered = _filter_ident_and_blank(_preprocess_file(sdev_path, cpp, cpp_flags))
            (conf_root / "sdevice.d" / module).write_text(rendered)

    _refresh_cf_mdevice(conf_root)


def main() -> int:
    args = _parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    conf_root = Path(args.conf_root).resolve()

    (conf_root / "pack.d").mkdir(parents=True, exist_ok=True)
    (conf_root / "cf.d").mkdir(parents=True, exist_ok=True)
    for name in ID_DIRS:
        _ensure_clean_dir(conf_root / name)

    _stage_common_modules(workspace_root, conf_root, args.cpp, list(args.cpp_flag))
    _stage_at386_overlay(workspace_root, conf_root, args.cpp, list(args.cpp_flag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())