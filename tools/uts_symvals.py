#!/usr/bin/env python3

# Generate the machine-layer symbol-value inputs consumed by the ml assembly:
#
#   symvals.s  - a table of `.set NAME, VALUE` directives giving struct-member
#                offsets (and a few derived addresses) that locore/start/syms
#                reference. The values are computed by the C compiler via
#                __builtin_offsetof, then lifted back out of the generated .s.
#   symvals.h  - the same kind of thing for plain preprocessor #defines pulled
#                from the kernel headers, for the assembly fragments that
#                #include "symvals.h".
#
# This used to live inside the much larger uts_ml_build.py alongside a legacy
# GNU-as normalizer and the locore/start link orchestration. The .s sources are
# now modern-gas-clean, so that orchestration is expressed directly in the build
# spec and only this offset/define generation - which genuinely needs the C
# compiler - remains in Python.

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
except ImportError:
    from pathing import resolve_kernel_root

SYMVAL_MEMBER_EXPRESSIONS: list[tuple[str, str]] = [
    ('i_flag', '__builtin_offsetof(struct inode, i_flag)'),
    ('memused', '__builtin_offsetof(struct bootinfo, memused)'),
    ('memusedcnt', '__builtin_offsetof(struct bootinfo, memusedcnt)'),
    ('p_as', '__builtin_offsetof(proc_t, p_as)'),
    ('p_sysid', '__builtin_offsetof(proc_t, p_sysid)'),
    ('p_ubptbl', '__builtin_offsetof(proc_t, p_ubptbl)'),
    ('p_usize', '__builtin_offsetof(proc_t, p_usize)'),
    ('p_sdp', '__builtin_offsetof(proc_t, p_sdp)'),
    ('a_hat', '__builtin_offsetof(struct as, a_hat)'),
    ('hat_pts', '__builtin_offsetof(hat_t, hat_pts)'),
    ('hatpt_forw', '__builtin_offsetof(hatpt_t, hatpt_forw)'),
    ('hatpt_pde', '__builtin_offsetof(hatpt_t, hatpt_pde)'),
    ('hatpt_pdtep', '__builtin_offsetof(hatpt_t, hatpt_pdtep)'),
    ('t_eax', '__builtin_offsetof(struct tss386, t_eax)'),
    ('t_ebx', '__builtin_offsetof(struct tss386, t_ebx)'),
    ('t_edx', '__builtin_offsetof(struct tss386, t_edx)'),
    ('t_esi', '__builtin_offsetof(struct tss386, t_esi)'),
    ('t_esp', '__builtin_offsetof(struct tss386, t_esp)'),
    ('t_edi', '__builtin_offsetof(struct tss386, t_edi)'),
    ('t_esp0', '__builtin_offsetof(struct tss386, t_esp0)'),
    ('t_ldt', '__builtin_offsetof(struct tss386, t_ldt)'),
    ('u_tss', '(UVUBLK + __builtin_offsetof(struct user, u_tss))'),
    ('u_procp', '(UVUBLK + __builtin_offsetof(struct user, u_procp))'),
    ('u_callgatep', '(UVUBLK + __builtin_offsetof(struct user, u_callgatep))'),
    ('u_callgate', '(UVUBLK + __builtin_offsetof(struct user, u_callgate))'),
    ('u_weitek', '(UVUBLK + __builtin_offsetof(struct user, u_weitek))'),
    ('u_weitek_reg', '(UVUBLK + __builtin_offsetof(struct user, u_weitek_reg))'),
    ('u_fpintgate', '(UVUBLK + __builtin_offsetof(struct user, u_fpintgate))'),
    ('u_ldtlimit', '(UVUBLK + __builtin_offsetof(struct user, u_ldtlimit))'),
    ('u_debugreg', '(UVUBLK + __builtin_offsetof(struct user, u_debugreg))'),
    ('u_debugon', '(UVUBLK + __builtin_offsetof(struct user, u_debugon))'),
    ('u_sigfault', '(UVUBLK + __builtin_offsetof(struct user, u_sigfault))'),
    ('u_renv', '(UVUBLK + __builtin_offsetof(struct user, u_renv))'),
    ('u_fault_catch', '(UVUBLK + __builtin_offsetof(struct user, u_fault_catch))'),
    ('fc_flags', '__builtin_offsetof(fault_catch_t, fc_flags)'),
    ('fc_errno', '__builtin_offsetof(fault_catch_t, fc_errno)'),
    ('fc_func', '__builtin_offsetof(fault_catch_t, fc_func)'),
]

SYMVAL_VPIX_EXPRESSIONS: list[tuple[str, str]] = [
    ('xt_vflptr', '__builtin_offsetof(xtss_t, xt_vflptr)'),
    ('xt_magictrap', '__builtin_offsetof(xtss_t, xt_magictrap)'),
    ('xt_magicstat', '__builtin_offsetof(xtss_t, xt_magicstat)'),
    ('xt_intr_pin', '__builtin_offsetof(xtss_t, xt_intr_pin)'),
    ('xt_timer_count', '__builtin_offsetof(xtss_t, xt_timer_count)'),
    ('xt_timer_bound', '__builtin_offsetof(xtss_t, xt_timer_bound)'),
    ('xt_imaskbits', '__builtin_offsetof(xtss_t, xt_imaskbits)'),
    ('xt_lbolt', '__builtin_offsetof(xtss_t, xt_lbolt)'),
    ('xt_op_emul', '__builtin_offsetof(xtss_t, xt_op_emul)'),
    ('XTSSADDR', '__builtin_offsetof(struct Gen_XTSSADDR, XTSSADDR)'),
]

SYMVAL_HEADER_NAMES: list[str] = [
    'BKI_MAGIC', 'BOOTINFO_LOC', 'CPPTSHIFT', 'FP_NO', 'FP_287', 'FP_387',
    'GDTSZ', 'IDTSZ', 'JTSSSEL', 'KDSSEL', 'KPTBL_LOC', 'KSTKSZ', 'KTSSSEL', 'KVBASE', 'KVXBASE',
    'KVSBASE', 'LDTSEL', 'MAXUSIZE', 'MAXUVADR', 'MINUVADR', 'MONIDTSZ', 'NCPPT', 'PF_RDONLY',
    'PG_ADDR', 'PG_P', 'PG_V', 'PG_M', 'PG_REF', 'PG_RW', 'PG_US', 'PINOD', 'PNUMSHFT', 'PT_STACK',
    'PTNUMSHFT', 'PTOFFMASK', 'USER_CS', 'USER_DS', 'USER_SCALL', 'UB_XSDSWTCH', 'UVBASE',
    'UVTEXT', 'WEITEK_HW', 'WEITEK_SW', 'WEITEK_NO', 'XMEM_BIT', 'XTSSSEL',
]

SYMVAL_HEADER_PATHS: list[str] = [
    'uts/i386/sys/bootinfo.h',
    'uts/i386/sys/fp.h',
    'uts/i386/sys/immu.h',
    'uts/i386/sys/fs/s5inode.h',
    'uts/i386/sys/param.h',
    'uts/i386/sys/seg.h',
    'uts/i386/sys/user.h',
    'uts/i386/sys/weitek.h',
]

SET_PATTERN = re.compile(r'^\s*\.set\s+([A-Za-z0-9_]+),\s*(.+)$')
DEFINE_PATTERN = re.compile(r'^\s*#define\s+([A-Za-z0-9_]+)\b')

# The header constants (immu.h, bootinfo.h, ...) are written as C expressions with
# casts and long-integer suffixes, e.g. `((unsigned)0xD0000000L)` or `((paddr_t)0x1000)`.
# GNU as cannot parse those, so strip the C-isms from the values we lift into the
# assembly-facing symvals.h. (Only the asm fragments consume symvals.h; the C kernel
# includes the original headers directly.)
CAST_PATTERNS = [
    re.compile(r'\(\(unsigned\)\s*([^\)]+)\)'),
    re.compile(r'\(\(paddr_t\)\s*([^\)]+)\)'),
]
LONG_SUFFIX_PATTERN = re.compile(r'(?<![A-Za-z0-9_])(0x[0-9A-Fa-f]+|\d+)[Ll](?![A-Za-z0-9_])')


def sanitize_header_value(text: str) -> str:
    for pattern in CAST_PATTERNS:
        text = pattern.sub(r'\1', text)
    return LONG_SUFFIX_PATTERN.sub(r'\1', text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate the ml symvals.s / symvals.h inputs.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--out-dir', required=True, help='Directory to write symvals.s and symvals.h into.')
    parser.add_argument('--cc', required=True)
    parser.add_argument('--cflag', action='append', default=[])
    parser.add_argument('--cflags', action='append', default=[], help='Space-joined compiler flags; shell-split and appended to --cflag.')
    parser.add_argument('--define', action='append', default=[], help='Extra cpp define names (e.g. VPIX) to enable.')
    args = parser.parse_args()
    for group in args.cflags:
        args.cflag.extend(shlex.split(group))
    return args


def run(command: list[str], cwd: Path) -> None:
    print('    ' + ' '.join(command))
    subprocess.run(command, cwd=cwd, check=True)


def gensymvals_cflags(cflags: list[str]) -> list[str]:
    # The offsetof probe is a pure compile-time computation; optimization level
    # is irrelevant and -O can reorder the emitted .set directives, so drop it.
    return [flag for flag in cflags if not flag.startswith('-O')]


def generate_symvals_source(out_dir: Path, include_vpix: bool) -> Path:
    source = out_dir / 'symvals-direct.c'
    symbol_lines = [
        f'    __asm__(".set {name},%c0" : : "i"({expr}));'
        for name, expr in SYMVAL_MEMBER_EXPRESSIONS + (SYMVAL_VPIX_EXPRESSIONS if include_vpix else [])
    ]
    vpix_helper = (
        'struct Gen_XTSSADDR {\n'
        '#define caddr_t int\n'
        '    char filler[XTSSADDR];\n'
        '#undef XTSSADDR\n'
        '    xtss_t XTSSADDR;\n'
        '};\n\n'
    ) if include_vpix else ''
    source.write_text(
        '#include "sys/param.h"\n'
        '#include "sys/types.h"\n'
        '#include "sys/immu.h"\n'
        '#include "sys/tss.h"\n'
        '#include "sys/seg.h"\n'
        '#include "sys/signal.h"\n'
        '#include "sys/vnode.h"\n'
        '#include "sys/fs/s5dir.h"\n'
        '#include "sys/fs/s5inode.h"\n'
        '#include "sys/user.h"\n'
        '#include "sys/systm.h"\n'
        '#include "sys/sysinfo.h"\n'
        '#include "sys/var.h"\n'
        '#include "sys/errno.h"\n'
        '#include "sys/cmn_err.h"\n'
        '#include "sys/proc.h"\n'
        '#include "sys/sysmacros.h"\n'
        '#include "sys/v86.h"\n'
        '#include "sys/bootinfo.h"\n'
        '#include "vm/as.h"\n'
        '#include "vm/vm_hat.h"\n'
        '#include "vm/faultcatch.h"\n\n'
        f'{vpix_helper}'
        'static void gen_symvals(void)\n'
        '{\n'
        + '\n'.join(symbol_lines)
        + '\n}\n',
        encoding='utf-8',
    )
    return source


def generate_symvals_assembly(cc: str, cflags: list[str], out_dir: Path, include_vpix: bool) -> None:
    source = generate_symvals_source(out_dir, include_vpix)
    assembly = out_dir / 'symvals-direct.s'
    run([cc, *cflags, '-S', source.name, '-o', assembly.name], cwd=out_dir)

    extracted: dict[str, str] = {}
    for line in assembly.read_text(encoding='utf-8', errors='replace').splitlines():
        match = SET_PATTERN.match(line)
        if not match:
            continue
        extracted[match.group(1)] = match.group(2)

    requested = [name for name, _ in SYMVAL_MEMBER_EXPRESSIONS]
    if include_vpix:
        requested.extend(name for name, _ in SYMVAL_VPIX_EXPRESSIONS)
    missing = [name for name in requested if name not in extracted]
    if missing:
        raise RuntimeError(f'failed to generate symvals entries for: {", ".join(missing)}')

    symvals = out_dir / 'symvals.s'
    symvals.write_text(
        ''.join(f'\t.set\t{name},\t{extracted[name]}\n' for name in requested),
        encoding='utf-8',
    )


def generate_symvals_header(cc: str, cflags: list[str], out_dir: Path) -> None:
    requested = set(SYMVAL_HEADER_NAMES)
    source = out_dir / 'symvals-header-direct.c'
    source.write_text(
        ''.join(f'#include "{relative_path.split("uts/i386/", 1)[1]}"\n' for relative_path in SYMVAL_HEADER_PATHS),
        encoding='utf-8',
    )

    result = subprocess.run(
        [cc, *cflags, '-E', '-dM', source.name],
        check=True,
        cwd=out_dir,
        capture_output=True,
        text=True,
    )

    lines: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        match = DEFINE_PATTERN.match(line)
        if not match:
            continue
        name = match.group(1)
        if name not in requested or name in seen:
            continue
        seen.add(name)
        lines.append(sanitize_header_value(line))

    (out_dir / 'symvals.h').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def sanitize_symvals_assembly(out_dir: Path) -> None:
    source = out_dir / 'symvals.s'
    lines = source.read_text(encoding='utf-8').splitlines()
    filtered = [line for line in lines if line not in {'#APP', '#NO_APP'}]
    source.write_text('\n'.join(filtered) + '\n', encoding='utf-8')


def sanitize_symvals_header(out_dir: Path) -> None:
    source = out_dir / 'symvals.h'
    filtered: list[str] = []
    seen_defines: set[str] = set()
    for line in source.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped:
            filtered.append('')
            continue
        if not stripped.startswith('#define'):
            continue
        if stripped.endswith('\\'):
            continue
        parts = stripped.split(None, 2)
        if len(parts) < 2:
            continue
        name = parts[1]
        if name in seen_defines:
            continue
        seen_defines.add(name)
        filtered.append(line)
    source.write_text('\n'.join(filtered) + '\n', encoding='utf-8')


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    kernel_root = resolve_kernel_root(workspace_root)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cflags = gensymvals_cflags([*args.cflag, f'-I{kernel_root / "i386"}'])
    cflags.extend(f'-D{name}' for name in args.define)
    include_vpix = 'VPIX' in args.define

    generate_symvals_assembly(args.cc, cflags, out_dir, include_vpix)
    generate_symvals_header(args.cc, cflags, out_dir)
    sanitize_symvals_assembly(out_dir)
    sanitize_symvals_header(out_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
