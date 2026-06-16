#!/usr/bin/env python3
"""Partial-link a set of objects into one relocatable object (ld -Ur).

Replaces uts_driver_compose.py's _link_driver/_link_relocatable. The only
non-obvious part is preferring ld.bfd: mold does not allocate COMMON symbols
during -r, which the kernel's symbol+offset asm references rely on.

Usage: partial_link.py --ld LD -o OUT IN.o [IN.o ...]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ld', default='ld')
    parser.add_argument('-o', dest='output', required=True)
    parser.add_argument('inputs', nargs='+')
    args = parser.parse_args()

    linker = args.ld
    extra: list[str] = ['-Ur']
    if Path(args.ld).name == 'ld':
        bfd = shutil.which('ld.bfd')
        if bfd is not None:
            linker = bfd
        extra = ['-m', 'elf_i386', '-Ur']

    cmd = [linker, *extra, *args.inputs, '-o', args.output]
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    sys.exit(main())
