#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
except ImportError:
    from pathing import resolve_kernel_root


OFFSET_FIELDS = ['hdp_ncyl', 'hdp_nhead', 'hdp_nsect', 'hdp_precomp', 'hdp_lz']
HEADER_LINE_TOKENS = [
    'BOOTIND',
    'GDTSIZE',
    'RELSECT',
    'HDBIOS_NCYL',
    'HDBIOS_NHEAD',
    'HDBIOS_SPT',
    'HDBIOS_PRECOMP',
    'HDBIOS_LZ',
    'BKI_MAGIC',
    'SECSIZE',
    'PROTMASK',
    'NOPROTMASK',
    'STACK',
    'BOOTDRIVE',
    'NUMPART',
    'BOOTSZ',
    'ACTIVE',
    'DISKBUF',
    'KB_STAT',
    'KB_INBF',
    'KB_WOP',
    'KB_OUT',
    'KB_IDAT',
]

CAST_PATTERNS = [
    re.compile(r'\(\(unsigned\)\s*([^\)]+)\)'),
    re.compile(r'\(\(paddr_t\)\s*([^\)]+)\)'),
]
LONG_SUFFIX_PATTERN = re.compile(r'(?<![A-Za-z0-9_])([0-9A-Fa-fx]+)[Ll](?![A-Za-z0-9_])')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate uts/i386/boot/at386/bsymvals.{s,h} without relying on historical compiler debug record layouts.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--boot-root')
    parser.add_argument('--cc', default='gcc')
    return parser.parse_args()


def run(command: list[str], cwd: Path | None = None) -> str:
    rendered = ' '.join(command)
    print(rendered)
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end='')
    if completed.stderr:
        print(completed.stderr, end='')
    return completed.stdout


def normalize_define_line(line: str) -> str:
    normalized = line.rstrip()
    for pattern in CAST_PATTERNS:
        normalized = pattern.sub(r'\1', normalized)
    normalized = LONG_SUFFIX_PATTERN.sub(r'\1', normalized)
    return normalized


def collect_header_lines(header_paths: list[Path]) -> list[str]:
    output: list[str] = []
    for header_path in header_paths:
        for raw_line in header_path.read_text(encoding='utf-8', errors='replace').splitlines():
            stripped = raw_line.lstrip()
            if stripped.startswith('#if') or stripped.startswith('#e'):
                output.append(stripped)
                continue
            if stripped.startswith('#define') and any(token in stripped for token in HEADER_LINE_TOKENS):
                output.append(normalize_define_line(stripped))
    return output


def write_offset_program(source_path: Path) -> None:
    lines = [
        '#include <stddef.h>',
        '#include <stdio.h>',
        '#include "sys/types.h"',
        '#include "sys/bootinfo.h"',
        '#include "boot/sys/boot.h"',
        '',
        'int main(void) {',
    ]
    for field in OFFSET_FIELDS:
        lines.append(f'    printf("\\t.set\\t{field},\\t%zu\\n", offsetof(struct hdparams, {field}));')
    lines.extend([
        '    return 0;',
        '}',
        '',
    ])
    source_path.write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    kernel_root = resolve_kernel_root(workspace_root)
    boot_root = Path(args.boot_root).resolve() if args.boot_root else kernel_root / 'i386/boot/at386'
    boot_dir = boot_root
    temp_dir = boot_root / '.bsymvals-build'
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    program_source = temp_dir / 'boot_offsets.c'
    program_binary = temp_dir / 'boot_offsets'
    write_offset_program(program_source)

    run([
        args.cc,
        '-std=gnu89',
        '-fcommon',
        '-fno-builtin',
        '-O2',
        '-D_KERNEL',
        '-DAT386',
        '-DWEITEK',
        '-DWEITEK_EMULATOR',
        f'-I{kernel_root / "i386"}',
        str(program_source),
        '-o',
        str(program_binary),
    ])
    offsets = run([str(program_binary)])
    (boot_dir / 'bsymvals.s').write_text(offsets, encoding='utf-8')

    header_lines = collect_header_lines([
        kernel_root / 'i386/sys/bootinfo.h',
        kernel_root / 'i386/sys/fdisk.h',
        kernel_root / 'i386/boot/sys/boot.h',
        kernel_root / 'i386/sys/hd.h',
        kernel_root / 'i386/sys/kd.h',
    ])
    (boot_dir / 'bsymvals.h').write_text('\n'.join(header_lines) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())