#!/usr/bin/env python3
"""Build the low-level machine-layer objects locore.o / start.o / syms.o.

This is the ml-at386 build-spec target ported verbatim (same steps, same input
order, same flags). It is a single script because the work is a fixed pipeline
with generated intermediates on the include path -- not naturally expressible as
independent Meson custom_targets:

  1. uts_symvals.py generates symvals.s (.set offset table) + symvals.h (#define
     table) into a scratch dir. locore.s/start.s #include symvals.s and the
     ttrap/uprt fragments #include symvals.h, so the scratch dir is on -I.
  2. Compile the ml C sources (tables1/pit/pic/tables2) with kernel_recompile
     cflags (NOT hardened: the legacy ml sources are not -Werror/-nostdinc clean).
  3. Assemble locore/start/syms via cc -x assembler-with-cpp.
  4. Partial-link (ld -r) the final objects. Input order matters: tables1.o must
     lead locore.o (early boot depends on it). syms.o is a single object, copied.

Outputs <out-dir>/{locore.o,start.o,syms.o}. ld.bfd is preferred for the -r
links so COMMON symbols stay allocated (symbol+offset asm refs); see partial_link.
"""
from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CPPDEFS = ['-D_KERNEL', '-DLOCORE', '-DAT386', '-DWEITEK', '-DWEITEK_EMULATOR']


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--kernel-root', required=True)
    ap.add_argument('--cc', required=True)
    ap.add_argument('--ld', required=True)
    ap.add_argument('--cflags', required=True, help='space-joined kernel recompile cflags')
    ap.add_argument('--symvals', required=True, help='path to uts_symvals.py')
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()

    kroot = Path(args.kernel_root).resolve()
    mldir = kroot / 'i386' / 'ml'
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    base_cflags = shlex.split(args.cflags)

    linker = args.ld
    ld_extra = ['-r']
    if Path(args.ld).name == 'ld':
        bfd = shutil.which('ld.bfd')
        if bfd is not None:
            linker = bfd
        ld_extra = ['-m', 'elf_i386', '-r']

    def run(cmd: list[str]) -> None:
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit(r.returncode)

    with tempfile.TemporaryDirectory(prefix='uts-ml-') as scratch_name:
        scratch = Path(scratch_name)
        # (1) symvals.s / symvals.h
        run([sys.executable, args.symvals, '--workspace-root', str(kroot),
             '--out-dir', str(scratch), '--cc', args.cc, '--cflags', args.cflags])

        cflags = base_cflags + ['-I' + str(mldir.parent), '-I' + str(scratch)]

        # (2) ml C sources
        for src in ('tables1', 'pit', 'pic', 'tables2'):
            run([args.cc, *cflags, '-c', str(mldir / f'{src}.c'),
                 '-o', str(scratch / f'{src}.o')])

        # (3) assemble locore/start/syms
        for unit in ('locore', 'start', 'syms'):
            run([args.cc, '-x', 'assembler-with-cpp', *cflags, *CPPDEFS,
                 '-c', str(mldir / f'{unit}.s'), '-o', str(scratch / f'{unit}.o')])

        # (4) partial links (order matters) + copy syms.o
        run([linker, *ld_extra, '-o', str(out / 'locore.o'),
             str(scratch / 'tables1.o'), str(scratch / 'locore.o'),
             str(scratch / 'pit.o'), str(scratch / 'pic.o')])
        run([linker, *ld_extra, '-o', str(out / 'start.o'),
             str(scratch / 'start.o'), str(scratch / 'tables2.o')])
        shutil.copy2(scratch / 'syms.o', out / 'syms.o')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
