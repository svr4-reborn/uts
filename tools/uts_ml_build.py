#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
except ImportError:
    from pathing import resolve_kernel_root

try:
    from .legacy_as import normalize_legacy_assembly
except ImportError:
    from legacy_as import normalize_legacy_assembly


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
    'BKI_MAGIC', 'BOOTINFO_LOC', 'CPPTSHIFT', 'FPESEL', 'FP_NO', 'FP_287', 'FP_387', 'FP_SW',
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
CAST_PATTERNS = [
    re.compile(r'\(\(unsigned\)\s*([^\)]+)\)'),
    re.compile(r'\(\(paddr_t\)\s*([^\)]+)\)'),
]
LONG_SUFFIX_PATTERN = re.compile(r'(?<![A-Za-z0-9_])([0-9A-Fa-fx]+)[Ll](?![A-Za-z0-9_])')
AND_NOT_ALL_PATTERN = re.compile(r'(?<![A-Za-z0-9_.])-1\s*!\s*(\([^\n]+?\)|\[[^\n]+?\]|[A-Za-z_.$][\w.$|]*|0x[0-9A-Fa-f]+|\d+)')
AND_NOT_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_.$-])'
    r'([A-Za-z_.$][\w.$]*|0x[0-9A-Fa-f]+|\d+|\([^\n]+?\)|\[[^\n]+?\])'
    r'\s*!\s*'
    r'(\([^\n]+?\)|\[[^\n]+?\]|[A-Za-z_.$][\w.$]*|0x[0-9A-Fa-f]+|\d+)'
)
BYTE_REGISTER_PATTERNS = {
    '%a': '%al',
    '%b': '%bl',
    '%c': '%cl',
    '%d': '%dl',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build uts/i386/ml machine-layer objects.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--obj-root', required=True)
    parser.add_argument('--pack-root', required=True)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--cpp', required=True)
    parser.add_argument('--ld', required=True)
    parser.add_argument('--cflag', action='append', default=[])
    parser.add_argument('--cpp-flag', action='append', default=[])
    parser.add_argument('--ld-flag', action='append', default=[])
    return parser.parse_args()


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    rendered = ' '.join(command)
    print(f'    {rendered}')
    subprocess.run(command, cwd=cwd, env=env, check=True)


def choose_partial_linker(default_ld: str) -> list[str]:
    version = subprocess.run(
        [default_ld, '--version'],
        check=True,
        capture_output=True,
        text=True,
    )
    if 'mold' in version.stdout:
        bfd = shutil.which('ld.bfd')
        if bfd is not None:
            # GNU ld.bfd with -d allocates COMMONs during -r links, which keeps
            # assembly references like symbol+offset from collapsing to absolutes.
            return [bfd, '-m', 'elf_i386', '-d']
    return [default_ld]


def compile_generated_assembly(cc: str, cflags: list[str], source: Path, output: Path, cwd: Path) -> None:
    run([cc, *cflags, '-c', str(source), '-o', str(output)], cwd=cwd)


def write_setfilter_wrapper(work_ml_root: Path, workspace_root: Path) -> None:
    tool_dir = work_ml_root / 'tool'
    tool_dir.mkdir(parents=True, exist_ok=True)
    wrapper = tool_dir / 'setfilter'
    target = resolve_kernel_root(workspace_root) / 'tools' / 'legacy_setfilter.py'
    wrapper.write_text(
        '#!/usr/bin/env python3\n'
        'import os\n'
        'import sys\n'
        f'os.execv(sys.executable, [sys.executable, {str(target)!r}, *sys.argv[1:]])\n',
        encoding='utf-8',
    )
    wrapper.chmod(0o755)


def gensymvals_cflags(cflags: list[str]) -> list[str]:
    return [flag for flag in cflags if not flag.startswith('-O')]


def should_emit_vpix_symbols(cflags: list[str]) -> bool:
    return any('VPIX' in flag for flag in cflags)


def generate_symvals_source(work_ml_root: Path, include_vpix: bool) -> Path:
    source = work_ml_root / 'symvals-direct.c'
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


def generate_symvals_assembly(cc: str, cflags: list[str], work_ml_root: Path, include_vpix: bool) -> None:
    source = generate_symvals_source(work_ml_root, include_vpix)
    assembly = work_ml_root / 'symvals-direct.s'
    run([cc, *cflags, '-S', source.name, '-o', assembly.name], cwd=work_ml_root)

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

    symvals = work_ml_root / 'symvals.s'
    symvals.write_text(
        ''.join(f'\t.set\t{name},\t{extracted[name]}\n' for name in requested),
        encoding='utf-8',
    )


def generate_symvals_header(cc: str, cflags: list[str], work_ml_root: Path) -> None:
    requested = set(SYMVAL_HEADER_NAMES)
    source = work_ml_root / 'symvals-header-direct.c'
    source.write_text(
        ''.join(f'#include "{relative_path.split("uts/i386/", 1)[1]}"\n' for relative_path in SYMVAL_HEADER_PATHS),
        encoding='utf-8',
    )

    result = subprocess.run(
        [cc, *cflags, '-E', '-dM', source.name],
        check=True,
        cwd=work_ml_root,
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
        lines.append(line)

    (work_ml_root / 'symvals.h').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def sanitize_symvals_assembly(work_ml_root: Path) -> None:
    source = work_ml_root / 'symvals.s'
    lines = source.read_text(encoding='utf-8').splitlines()
    filtered = [line for line in lines if line not in {'#APP', '#NO_APP'}]
    source.write_text('\n'.join(filtered) + '\n', encoding='utf-8')


def sanitize_symvals_header(work_ml_root: Path) -> None:
    source = work_ml_root / 'symvals.h'
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


def normalize_legacy_generated_assembly(source: Path) -> None:
    text = source.read_text(encoding='utf-8', errors='replace')
    text = normalize_legacy_assembly(text)
    for pattern in CAST_PATTERNS:
        text = pattern.sub(r'\1', text)
    text = LONG_SUFFIX_PATTERN.sub(r'\1', text)
    text = AND_NOT_ALL_PATTERN.sub(r'~(\1)', text)
    text = AND_NOT_PATTERN.sub(r'((\1) & ~(\2))', text)
    text = text.replace('[', '').replace(']', '')
    for legacy_name, gas_name in BYTE_REGISTER_PATTERNS.items():
        text = re.sub(rf'{re.escape(legacy_name)}(?![A-Za-z0-9])', gas_name, text)
    source.write_text(text, encoding='utf-8')


def write_locore_source(work_ml_root: Path) -> Path:
    output = work_ml_root / 'locore-temp.c'
    inputs = [
        work_ml_root / 'symvals.s',
        work_ml_root / 'ttrap.s',
        work_ml_root / 'cswitch.s',
        work_ml_root / 'misc.s',
        work_ml_root / 'intr.s',
        work_ml_root / 'weitek.s',
        work_ml_root / 'v86gptrap.s',
        work_ml_root / 'oemsup.s',
        work_ml_root / 'string.s',
    ]
    with output.open('w', encoding='utf-8') as handle:
        handle.write('\t.file\t"locore.s"\n')
        for source in inputs:
            content = source.read_text(encoding='utf-8')
            handle.write(content)
            if not content.endswith('\n'):
                handle.write('\n')
    return output


def write_start_source(work_ml_root: Path) -> Path:
    output = work_ml_root / 'start-temp.c'
    inputs = [work_ml_root / 'symvals.s', work_ml_root / 'uprt.s']
    with output.open('w', encoding='utf-8') as handle:
        handle.write('\t.file\t"uprt.s"\n')
        for source in inputs:
            content = source.read_text(encoding='utf-8')
            handle.write(content)
            if not content.endswith('\n'):
                handle.write('\n')
    return output


def rewrite_tables2_assembly(work_ml_root: Path) -> Path:
    source = work_ml_root / 'tables2.s'
    output = work_ml_root / 'tables2-temp.s'
    lines = source.read_text(encoding='utf-8').splitlines()
    with output.open('w', encoding='utf-8') as handle:
        for line in lines:
            if line == '\t.data':
                handle.write('\t.text\n')
                handle.write('\t.align\t8\n')
                continue
            handle.write(f'{line}\n')
    return output


def prepare_worktree(source_root: Path, obj_root: Path) -> Path:
    work_root = obj_root / '_workroot'
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)
    for name in ('sys', 'vm'):
        (work_root / name).symlink_to(source_root / name, target_is_directory=True)
    shutil.copytree(source_root / 'ml', work_root / 'ml')
    return work_root / 'ml'


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    kernel_root = resolve_kernel_root(workspace_root)
    obj_root = Path(args.obj_root).resolve()
    pack_root = Path(args.pack_root).resolve()
    uts_root = kernel_root / 'i386'
    ml_root = uts_root / 'ml'

    obj_root.mkdir(parents=True, exist_ok=True)
    pack_root.mkdir(parents=True, exist_ok=True)

    work_ml_root = prepare_worktree(uts_root, obj_root)
    write_setfilter_wrapper(work_ml_root, workspace_root)
    symval_cflags = gensymvals_cflags(args.cflag)
    include_vpix = should_emit_vpix_symbols(args.cflag)
    partial_ld = choose_partial_linker(args.ld)

    env = dict(os.environ)
    env['CC'] = args.cc
    env['CFLAGS'] = ' '.join(symval_cflags)
    env['INCRT'] = '..'
    env['CCSTYPE'] = 'ELF'

    generate_symvals_assembly(args.cc, symval_cflags, work_ml_root, include_vpix)
    generate_symvals_header(args.cc, symval_cflags, work_ml_root)
    sanitize_symvals_assembly(work_ml_root)
    sanitize_symvals_header(work_ml_root)

    for source_name in ('tables1.c', 'pit.c', 'pic.c'):
        output = obj_root / f'{Path(source_name).stem}.o'
        run([args.cc, *args.cflag, '-c', source_name, '-o', str(output)], cwd=work_ml_root)

    run([args.cc, *args.cflag, '-S', 'tables2.c', '-o', 'tables2.s'], cwd=work_ml_root)
    tables2_temp = rewrite_tables2_assembly(work_ml_root)
    tables2_obj = obj_root / 'tables2.o'
    compile_generated_assembly(args.cc, args.cflag, tables2_temp, tables2_obj, work_ml_root)

    syms_source = work_ml_root / 'syms-preprocessed.s'
    run([args.cc, '-x', 'assembler-with-cpp', '-E', *args.cpp_flag, 'syms.s', '-o', str(syms_source)], cwd=work_ml_root)
    normalize_legacy_generated_assembly(syms_source)
    syms_obj = obj_root / 'syms.o'
    compile_generated_assembly(args.cc, args.cflag, syms_source, syms_obj, work_ml_root)

    locore_temp = write_locore_source(work_ml_root)
    locore_source = work_ml_root / 'locore.s'
    run([args.cc, '-x', 'assembler-with-cpp', '-E', *args.cpp_flag, str(locore_temp), '-o', str(locore_source)], cwd=work_ml_root)
    normalize_legacy_generated_assembly(locore_source)
    locore_asm_obj = work_ml_root / 'locore-asm.o'
    compile_generated_assembly(args.cc, args.cflag, locore_source, locore_asm_obj, work_ml_root)

    locore_obj = obj_root / 'locore.o'
    run(
        [
            *partial_ld,
            *args.ld_flag,
            '-r',
            '-o',
            str(locore_obj),
            str(obj_root / 'tables1.o'),
            str(locore_asm_obj),
            str(obj_root / 'pit.o'),
            str(obj_root / 'pic.o'),
        ],
        cwd=work_ml_root,
    )

    start_temp = write_start_source(work_ml_root)
    start_source = work_ml_root / 'start.s'
    run([args.cc, '-x', 'assembler-with-cpp', '-E', *args.cpp_flag, str(start_temp), '-o', str(start_source)], cwd=work_ml_root)
    normalize_legacy_generated_assembly(start_source)
    start_asm_obj = work_ml_root / 'start-asm.o'
    compile_generated_assembly(args.cc, args.cflag, start_source, start_asm_obj, work_ml_root)

    start_obj = obj_root / 'start.o'
    run(
        [
            *partial_ld,
            *args.ld_flag,
            '-r',
            '-o',
            str(start_obj),
            str(start_asm_obj),
            str(tables2_obj),
        ],
        cwd=work_ml_root,
    )

    for output in (locore_obj, start_obj, syms_obj):
        shutil.copy2(output, pack_root / output.name)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())