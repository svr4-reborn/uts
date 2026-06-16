#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
    from .uts_boot_common import preprocess_and_assemble, resolve_linker, run
except ImportError:
    from pathing import resolve_kernel_root
    from uts_boot_common import preprocess_and_assemble, resolve_linker, run


PROGRAM_SOURCES: dict[str, list[str]] = {
    'compaq': ['compaq.s'],
    'att': ['att.s', 'misc.c', 'inout.s', 'video.c'],
    'at386': ['at386.s', 'misc.c', 'inout.s'],
}

CPP_DEFINES = ['-D_KERNEL', '-DAT386', '-DWEITEK', '-DWEITEK_EMULATOR']
COMMON_CFLAGS = ['-std=gnu89', '-fcommon', '-fno-builtin', '-O']


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build uts/i386/boot/at386/initprog without the historical makefile suffix rules.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--boot-root')
    parser.add_argument('--symvals-root')
    parser.add_argument('--build-root', required=True)
    parser.add_argument('--system-root', required=True)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cpp', default='cpp')
    parser.add_argument('--as', dest='assembler', default='as')
    parser.add_argument('--ld', default='ld')
    return parser.parse_args()


def compile_c(source: Path, output: Path, *, cc: str, include_root: Path, symvals_root: Path) -> None:
    run([
        cc,
        '-m32',
        *COMMON_CFLAGS,
        f'-I{symvals_root}',
        f'-I{include_root}',
        '-include',
        str(include_root / 'sys/types.h'),
        *CPP_DEFINES,
        '-c',
        str(source),
        '-o',
        str(output),
    ])


def write_linker_script(build_dir: Path) -> Path:
    linker_script = build_dir / 'binimap.ld'
    linker_script.write_text(
        '\n'.join([
            'OUTPUT_FORMAT(elf32-i386)',
            'ENTRY(initprog)',
            'SECTIONS',
            '{',
            '  . = 0x0;',
            '  .text : { *(.text .text.*) }',
            '  . = ALIGN(0x1000);',
            '  .rodata : { *(.rodata .rodata.*) }',
            '  . = ALIGN(0x1000);',
            '  .data : { *(.data .data.*) }',
            '  . = ALIGN(0x1000);',
            '  .bss : { *(.bss .bss.* COMMON) }',
            '}',
            '',
        ]),
        encoding='utf-8',
    )
    return linker_script


def build_program(name: str, sources: list[str], *, source_dir: Path, build_dir: Path, include_root: Path, symvals_root: Path, cc: str, cpp: str, assembler: str, ld: str) -> Path:
    object_paths: list[Path] = []
    asm_cpp_flags = [*CPP_DEFINES, f'-I{symvals_root}', f'-I{include_root}']
    for source_name in sources:
        source = source_dir / source_name
        object_path = build_dir / f'{Path(source_name).stem}.o'
        if source.suffix == '.s':
            preprocess_and_assemble(source, object_path, cpp_flags=asm_cpp_flags, cpp=cpp, assembler=assembler, build_dir=build_dir)
        elif source.suffix == '.c':
            compile_c(source, object_path, cc=cc, include_root=include_root, symvals_root=symvals_root)
        else:
            raise ValueError(f'unsupported source type: {source}')
        object_paths.append(object_path)

    output = build_dir / name
    linker_script = write_linker_script(build_dir)
    run([
        ld,
        '-m',
        'elf_i386',
        '-T',
        str(linker_script),
        '-e',
        'initprog',
        '-o',
        str(output),
        *[str(path) for path in object_paths],
    ])
    return output


def install_programs(programs: list[Path], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for program in programs:
        target = destination / program.name
        shutil.copyfile(program, target)
        os.chmod(target, 0o644)


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    kernel_root = resolve_kernel_root(workspace_root)
    boot_root = Path(args.boot_root).resolve() if args.boot_root else kernel_root / 'i386/boot'
    build_root = Path(args.build_root).resolve()
    system_root = Path(args.system_root).resolve()
    source_dir = boot_root / 'at386/initprog'
    include_root = kernel_root / 'i386'
    symvals_root = Path(args.symvals_root).resolve() if args.symvals_root else source_dir.parent

    if not (symvals_root / 'bsymvals.h').exists():
        raise SystemExit(f'error: expected {symvals_root / "bsymvals.h"} to exist before building initprog')

    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)

    linker = resolve_linker(args.ld)
    outputs = [
        build_program(
            name,
            sources,
            source_dir=source_dir,
            build_dir=build_root,
            include_root=include_root,
            symvals_root=symvals_root,
            cc=args.cc,
            cpp=args.cpp,
            assembler=args.assembler,
            ld=linker,
        )
        for name, sources in PROGRAM_SOURCES.items()
    ]
    install_programs(outputs, system_root / 'etc/initprog')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
