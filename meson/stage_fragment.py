#!/usr/bin/env python3
"""Preprocess one master.d metadata fragment into its staged conf-tree form.

This is the per-file transform half of the old uts_stage_master_at386.py, split
out so Meson can drive it once per fragment via custom_target. Two modes:

  --mode frag : module fragments (mdev/sdev/node/mfsys/sfsys). Run through cpp,
                then strip *ident/#ident lines and blank lines.
  --mode cf   : top-level cf.d inputs (sassign/stune/mtune/init.base). The "# "
                comment lines are protected across cpp by a +/# swap, then cpp,
                then blanks dropped.

cpp flags mirror the build: -P -DAT386 -DWEITEK -DWEITEK_EMULATOR (passed in).
Byte-for-byte equivalent to the old tool (verified against its output tree).
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_cpp(cpp: list[str], cpp_flags: list[str], text: str) -> str:
    # cpp is the C compiler driver invoked as a preprocessor (-E -P -x c): the
    # cross "cpp" binary in the meson cross-file is actually g++, so we use the C
    # compiler in -E mode instead, which is unambiguous and equivalent for these
    # plain-text metadata fragments. Input is fed as -x c so the extensionless
    # temp file is treated as C source.
    with tempfile.TemporaryDirectory(prefix='uts-frag-') as d:
        ip = Path(d) / 'in.c'
        op = Path(d) / 'out'
        ip.write_text(text)
        subprocess.run([*cpp, '-E', '-P', '-x', 'c', *cpp_flags, str(ip), '-o', str(op)],
                       check=True)
        return op.read_text()


def _filter_ident_and_blank(text: str) -> str:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('*ident') or s.startswith('#ident'):
            continue
        lines.append(line)
    return '\n'.join(lines) + ('\n' if lines else '')


def _preprocess_cf(path: Path, cpp: list[str], cpp_flags: list[str]) -> str:
    transformed = []
    for line in path.read_text().splitlines():
        transformed.append('+' + line[1:] if line.startswith('# ') else line)
    pp = _run_cpp(cpp, cpp_flags, '\n'.join(transformed) + '\n')
    out = []
    for line in pp.splitlines():
        if not line.strip():
            continue
        out.append('#' + line[1:] if line.startswith('+') else line)
    return '\n'.join(out) + ('\n' if out else '')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=('frag', 'cf'), required=True)
    ap.add_argument('--cpp', required=True, help='C compiler driver (shell-split); used as -E -P preprocessor')
    ap.add_argument('--cpp-flag', action='append', default=[])
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    cpp = shlex.split(args.cpp)
    src = Path(args.inp)
    if args.mode == 'cf':
        result = _preprocess_cf(src, cpp, args.cpp_flag)
    else:
        result = _filter_ident_and_blank(_run_cpp(cpp, args.cpp_flag, src.read_text()))
    Path(args.out).write_text(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
