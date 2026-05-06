#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


FP_SOURCES = [
    'dcode.s',
    'arith.s',
    'divmul.s',
    'lipsq.s',
    'reg.s',
    'remsc.s',
    'round.s',
    'status.s',
    'store.s',
    'subadd.s',
    'trans.s',
]

CPP_DEFINES = ['-DAT386', '-DWEITEK', '-DWEITEK_EMULATOR']


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build uts/i386/fp without invoking the historical makefile.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--fp-root')
    parser.add_argument('--build-root', required=True)
    parser.add_argument('--system-root', required=True)
    parser.add_argument('--cpp', default='cpp')
    parser.add_argument('--as', dest='assembler', default='as')
    parser.add_argument('--ld', default='ld')
    return parser.parse_args()


def run(command: list[str], cwd: Path | None = None) -> None:
    print(' '.join(command))
    subprocess.run(command, cwd=cwd, check=True)


def compile_source(workspace_root: Path, fp_root: Path, build_root: Path, cpp: str, assembler: str, source_name: str) -> Path:
    source_path = fp_root / source_name
    stem = source_path.stem
    preprocessed = build_root / f'{stem}.i'
    sanitized = build_root / f'{stem}.s'
    object_path = build_root / f'{stem}.o'
    run([
        cpp,
        *CPP_DEFINES,
        f'-I{workspace_root / "uts/i386"}',
        f'-I{fp_root}',
        '-P',
        str(source_path),
        str(preprocessed),
    ])
    shutil.copyfile(preprocessed, sanitized)
    run([assembler, '--32', '-o', str(object_path), str(sanitized)])
    return object_path


def link_emulator(workspace_root: Path, fp_root: Path, build_root: Path, ld: str, object_paths: list[Path]) -> Path:
    output_path = build_root / 'emulator.rel1'
    command = [
        sys.executable,
        str(workspace_root / 'uts/tools/legacy_ld.py'),
        '-M' + str(fp_root / 'mapfile'),
        '-dn',
        '-s',
        '-e',
        'e80387',
        '-o',
        str(output_path),
        *[str(path) for path in object_paths],
    ]
    if ld:
        os.environ.setdefault('LD', ld)
    run(command)
    return output_path


def install_emulator(system_root: Path, emulator_path: Path) -> None:
    sbin_dir = system_root / 'sbin'
    etc_dir = system_root / 'etc'
    sbin_dir.mkdir(parents=True, exist_ok=True)
    etc_dir.mkdir(parents=True, exist_ok=True)
    target = sbin_dir / 'emulator.rel1'
    shutil.copyfile(emulator_path, target)
    os.chmod(target, 0o755)

    for link_path, link_target in [
        (sbin_dir / 'emulator', 'emulator.rel1'),
        (etc_dir / 'emulator', '../sbin/emulator'),
        (etc_dir / 'emulator.rel1', '../sbin/emulator.rel1'),
    ]:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(link_target)


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    fp_root = Path(args.fp_root).resolve() if args.fp_root else workspace_root / 'uts/i386/fp'
    build_root = Path(args.build_root).resolve()
    system_root = Path(args.system_root).resolve()

    if not (fp_root / 'symvals.h').exists():
        raise SystemExit(f'error: expected {fp_root / "symvals.h"} to exist before building fp')

    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)

    objects = [compile_source(workspace_root, fp_root, build_root, args.cpp, args.assembler, name) for name in FP_SOURCES]
    emulator = link_emulator(workspace_root, fp_root, build_root, args.ld, objects)
    install_emulator(system_root, emulator)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())