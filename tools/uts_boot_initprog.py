#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
except ImportError:
    from pathing import resolve_kernel_root


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
    parser.add_argument('--build-root', required=True)
    parser.add_argument('--system-root', required=True)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cpp', default='cpp')
    parser.add_argument('--as', dest='assembler', default='as')
    parser.add_argument('--ld', default='ld')
    return parser.parse_args()


def run(command: list[str], cwd: Path | None = None) -> None:
    rendered = ' '.join(command)
    print(rendered)
    subprocess.run(command, cwd=cwd, check=True)


def resolve_linker(linker: str) -> str:
    if Path(linker).name == 'ld':
        bfd_linker = shutil.which('ld.bfd')
        if bfd_linker:
            return bfd_linker
    return linker


def rewrite_legacy_comment_syntax(source_text: str) -> str:
    rewritten: list[str] = []
    for line in source_text.splitlines():
        comment_index = find_comment_index(line)
        if comment_index == -1:
            rewritten.append(line)
            continue
        rewritten.append(f'{line[:comment_index]}#{line[comment_index + 1:]}')
    return '\n'.join(rewritten) + '\n'


def find_comment_index(line: str) -> int:
    quote: str | None = None
    for index, char in enumerate(line):
        if char in {'"', "'"}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == '/' and quote is None:
            if index == 0 or line[:index].strip() == '' or line[index - 1].isspace():
                return index
    return -1


def compile_assembly(source: Path, output: Path, *, cpp: str, assembler: str, include_root: Path, build_dir: Path) -> None:
    preprocessed = build_dir / f'{source.stem}.i'
    sanitized = build_dir / f'{source.stem}.s'
    run([cpp, '-P', *CPP_DEFINES, f'-I{include_root}', str(source), '-o', str(preprocessed)])
    sanitized.write_text(rewrite_legacy_comment_syntax(preprocessed.read_text()), encoding='utf-8')
    run([assembler, '--32', '-o', str(output), str(sanitized)])


def compile_c(source: Path, output: Path, *, cc: str, include_root: Path) -> None:
    run([
        cc,
        '-m32',
        *COMMON_CFLAGS,
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


def build_program(name: str, sources: list[str], *, source_dir: Path, build_dir: Path, include_root: Path, cc: str, cpp: str, assembler: str, ld: str) -> Path:
    object_paths: list[Path] = []
    for source_name in sources:
        source = source_dir / source_name
        object_path = build_dir / f'{Path(source_name).stem}.o'
        if source.suffix == '.s':
            compile_assembly(source, object_path, cpp=cpp, assembler=assembler, include_root=include_root, build_dir=build_dir)
        elif source.suffix == '.c':
            compile_c(source, object_path, cc=cc, include_root=include_root)
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

    if not (source_dir.parent / 'bsymvals.h').exists():
        raise SystemExit('error: expected uts/i386/boot/at386/bsymvals.h to exist before building initprog')

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