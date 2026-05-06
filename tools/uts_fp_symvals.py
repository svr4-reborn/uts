#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
except ImportError:
    from pathing import resolve_kernel_root


SYMBOL_LABELS = {
    'sym_u_fps': 'u_fps',
    'sym_u_fpvalid': 'u_fpvalid',
}
LABEL_PATTERN = re.compile(r'^(sym_[A-Za-z0-9_]+):$')
LONG_PATTERN = re.compile(r'^\s*\.long\s+([0-9]+)\s*$')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate uts/i386/fp/symvals.h without relying on historical compiler debug records.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--fp-root')
    parser.add_argument('--cc', default='gcc')
    return parser.parse_args()


def compile_probe(workspace_root: Path, compiler: str) -> str:
    kernel_root = resolve_kernel_root(workspace_root)
    source = '\n'.join([
        '#include "sys/types.h"',
        '#include "sys/user.h"',
        '#include "sys/seg.h"',
        'int sym_u_fps = __builtin_offsetof(struct user, u_fps);',
        'int sym_u_fpvalid = __builtin_offsetof(struct user, u_fpvalid);',
        'int sym_USER_FP = USER_FP;',
        '',
    ])
    with tempfile.TemporaryDirectory(prefix='svr4-fp-symvals-') as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        source_path = temp_dir / 'fpvals.c'
        assembly_path = temp_dir / 'fpvals.s'
        source_path.write_text(source, encoding='utf-8')
        subprocess.run(
            [
                compiler,
                '-m32',
                '-std=gnu89',
                '-fcommon',
                '-fno-builtin',
                '-D_KERNEL',
                '-nostdinc',
                f'-I{kernel_root / "i386"}',
                '-S',
                str(source_path),
                '-o',
                str(assembly_path),
            ],
            check=True,
        )
        return assembly_path.read_text(encoding='utf-8')


def extract_values(assembly_text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    current_label: str | None = None
    for line in assembly_text.splitlines():
        label_match = LABEL_PATTERN.match(line)
        if label_match:
            current_label = label_match.group(1)
            continue
        if current_label is None:
            continue
        long_match = LONG_PATTERN.match(line)
        if not long_match:
            continue
        values[current_label] = int(long_match.group(1), 10)
        current_label = None

    missing = [label for label in SYMBOL_LABELS if label not in values]
    if missing:
        raise SystemExit(f'error: could not extract fp symvals for: {", ".join(missing)}')
    return values


def find_user_fp_define(seg_header: Path) -> str:
    for line in seg_header.read_text(encoding='utf-8', errors='replace').splitlines():
        stripped = line.strip()
        parts = stripped.split(None, 2)
        if len(parts) >= 2 and parts[0] == '#define' and parts[1] == 'USER_FP':
            return stripped
    raise SystemExit(f'error: could not locate USER_FP in {seg_header}')


def write_symvals(fp_root: Path, values: dict[str, int], user_fp_define: str) -> None:
    lines = [
        f'\t.set\tu_fps,\t{values["sym_u_fps"]}',
        f'\t.set\tu_fpvalid,\t{values["sym_u_fpvalid"]}',
        user_fp_define,
        '',
    ]
    (fp_root / 'symvals.h').write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    kernel_root = resolve_kernel_root(workspace_root)
    fp_root = Path(args.fp_root).resolve() if args.fp_root else kernel_root / 'i386/fp'
    values = extract_values(compile_probe(workspace_root, args.cc))
    user_fp_define = find_user_fp_define(kernel_root / 'i386/sys/seg.h')
    write_symvals(fp_root, values, user_fp_define)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())