#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from .pathing import resolve_kernel_root
except ImportError:
    from pathing import resolve_kernel_root


BOOT_SOURCES = [
    'start.s',
    'prot.s',
    'GDT.s',
    'util.s',
    'pit.s',
    'boot.c',
    'printf.c',
    'gets.c',
    'load.c',
    'disk.c',
    'string.c',
    'default.c',
    'memcpy.s',
    'touchpage.s',
    'e820.s',
    'physaddr.c',
    'memsize.c',
    'bstart.s',
]

BOOTLIB_SOURCES = [
    'blfile.c',
    'filesys.c',
    's5filesys.c',
    'elf.c',
    'bfsfilesys.c',
]

CPP_DEFINES = ['-DAT386', '-DDEBUG', '-DWEITEK', '-DWEITEK_EMULATOR']
COMMON_CFLAGS = [
    '-m32',
    '-std=gnu89',
    '-fcommon',
    '-fno-builtin',
    '-fno-stack-protector',
    '-fomit-frame-pointer',
    '-fno-unwind-tables',
    '-fno-asynchronous-unwind-tables',
    '-fno-pic',
    '-falign-functions=1',
    '-falign-jumps=1',
    '-falign-labels=1',
    '-falign-loops=1',
    '-mgeneral-regs-only',
    '-nostdinc',
    '-nostdlib',
    '-Os',
]

AT386_FDBOOT_LOADED_SECTORS = 30
AT386_SECTOR_SIZE = 512
AT386_BOOT_FILL_BYTE = 0xF6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build uts/i386/boot without invoking the historical makefiles.')
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--boot-root')
    parser.add_argument('--build-root', required=True)
    parser.add_argument('--system-root', required=True)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cpp', default='cpp')
    parser.add_argument('--as', dest='assembler', default='as')
    parser.add_argument('--strip', default='strip')
    return parser.parse_args()


def run(command: list[str], cwd: Path | None = None) -> None:
    print(' '.join(command))
    subprocess.run(command, cwd=cwd, check=True)


def rewrite_legacy_comment_syntax(source_text: str) -> str:
    rewritten: list[str] = []
    for line in source_text.splitlines():
        comment_index = find_comment_index(line)
        if comment_index == -1:
            rewritten.append(line.replace('\\*', '*'))
            continue
        rewritten.append(f'{line[:comment_index]}#{line[comment_index + 1:]}'.replace('\\*', '*'))
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


def apply_boot_sed(source_text: str) -> str:
    output: list[str] = []
    for line in source_text.splitlines():
        if line.startswith('\t.ident'):
            continue
        updated = line.replace('.data1,"aw"', '.text')
        updated = updated.replace('.data1', '.text')
        updated = updated.replace('.data', '.text')
        output.append(updated)
    return '\n'.join(output) + '\n'


def common_cpp_flags(workspace_root: Path, include_root: Path, extra_define: str | None = None) -> list[str]:
    flags = [
        *CPP_DEFINES,
        f'-I{include_root}',
    ]
    if extra_define:
        flags.append(extra_define)
    return flags


def assemble_with_cpp(source: Path, output: Path, *, workspace_root: Path, include_root: Path, cpp: str, assembler: str, build_dir: Path, extra_define: str | None = None, prepend: Path | None = None) -> None:
    combined = source.parent / f'.{source.stem}.combined.s'
    try:
        with combined.open('w', encoding='utf-8') as handle:
            if prepend is not None:
                handle.write(prepend.read_text(encoding='utf-8'))
            handle.write(source.read_text(encoding='utf-8'))

        preprocessed = build_dir / f'{source.stem}.i'
        sanitized = build_dir / f'{source.stem}.s'
        run([
            cpp,
            *common_cpp_flags(workspace_root, include_root, extra_define),
            '-P',
            str(combined),
            '-o',
            str(preprocessed),
        ])
        sanitized.write_text(rewrite_legacy_comment_syntax(preprocessed.read_text(encoding='utf-8')), encoding='utf-8')
        run([assembler, '--32', '-o', str(output), str(sanitized)])
    finally:
        combined.unlink(missing_ok=True)


def compile_c_to_object(source: Path, output: Path, *, workspace_root: Path, include_root: Path, cc: str, assembler: str, build_dir: Path, extra_define: str | None = None) -> None:
    assembly = build_dir / f'{source.stem}.gen.s'
    filtered = build_dir / f'{source.stem}.i'
    run([
        cc,
        *COMMON_CFLAGS,
        *common_cpp_flags(workspace_root, include_root, extra_define),
        '-S',
        '-c',
        str(source),
        '-o',
        str(assembly),
    ])
    filtered.write_text(apply_boot_sed(assembly.read_text(encoding='utf-8')), encoding='utf-8')
    run([assembler, '--32', '-o', str(output), str(filtered)])


def compile_variant_objects(source_dir: Path, source_names: list[str], *, workspace_root: Path, include_root: Path, cc: str, cpp: str, assembler: str, build_dir: Path, extra_define: str | None = None, prepend: Path | None = None) -> list[Path]:
    build_dir.mkdir(parents=True, exist_ok=True)
    object_paths: list[Path] = []
    for source_name in source_names:
        source = source_dir / source_name
        suffix = 'o'
        object_path = build_dir / f'{source.stem}.{suffix}'
        if source.suffix == '.s':
            assemble_with_cpp(source, object_path, workspace_root=workspace_root, include_root=include_root, cpp=cpp, assembler=assembler, build_dir=build_dir, extra_define=extra_define, prepend=prepend)
        elif source.suffix == '.c':
            compile_c_to_object(source, object_path, workspace_root=workspace_root, include_root=include_root, cc=cc, assembler=assembler, build_dir=build_dir, extra_define=extra_define)
        else:
            raise ValueError(f'unsupported source type: {source}')
        object_paths.append(object_path)
    return object_paths


def link_boot_image(workspace_root: Path, mapfile: Path, output_path: Path, object_paths: list[Path]) -> None:
    kernel_root = resolve_kernel_root(workspace_root)
    run([
        sys.executable,
        str(kernel_root / 'tools/legacy_ld.py'),
        '-M' + str(mapfile),
        '-dn',
        '-o',
        str(output_path),
        *[str(path) for path in object_paths],
    ])


def install_boot_artifacts(system_root: Path, fdboot: Path, hdboot: Path, default_dir: Path) -> None:
    etc_dir = system_root / 'etc'
    defaults_dir = etc_dir / 'default'
    etc_dir.mkdir(parents=True, exist_ok=True)
    defaults_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fdboot, etc_dir / '.fboot')
    shutil.copyfile(hdboot, etc_dir / '.wboot')
    os.chmod(etc_dir / '.fboot', 0o644)
    os.chmod(etc_dir / '.wboot', 0o644)
    for name in ['default.at386', 'default.cpq', 'default.att', 'default.att512']:
        shutil.copyfile(default_dir / name, defaults_dir / name)
        os.chmod(defaults_dir / name, 0o644)
    shutil.copyfile(default_dir / 'default.at386', defaults_dir / 'boot')
    os.chmod(defaults_dir / 'boot', 0o644)


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    kernel_root = resolve_kernel_root(workspace_root)
    boot_root = Path(args.boot_root).resolve() if args.boot_root else kernel_root / 'i386/boot'
    build_root = Path(args.build_root).resolve()
    system_root = Path(args.system_root).resolve()
    boot_at386_root = boot_root / 'at386'
    bootlib_root = boot_root / 'bootlib'
    include_root = kernel_root / 'i386'
    bsymvals = boot_at386_root / 'bsymvals.s'

    if not bsymvals.exists():
        raise SystemExit(f'error: expected {bsymvals} to exist before building boot')

    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)

    fd_bootlib = compile_variant_objects(bootlib_root, BOOTLIB_SOURCES, workspace_root=workspace_root, include_root=include_root, cc=args.cc, cpp=args.cpp, assembler=args.assembler, build_dir=build_root / 'bootlib/fd')
    hd_bootlib = compile_variant_objects(bootlib_root, BOOTLIB_SOURCES, workspace_root=workspace_root, include_root=include_root, cc=args.cc, cpp=args.cpp, assembler=args.assembler, build_dir=build_root / 'bootlib/hd', extra_define='-DWINI')
    fd_boot = compile_variant_objects(boot_at386_root, BOOT_SOURCES, workspace_root=workspace_root, include_root=include_root, cc=args.cc, cpp=args.cpp, assembler=args.assembler, build_dir=build_root / 'at386/fd', prepend=bsymvals)
    hd_boot = compile_variant_objects(boot_at386_root, BOOT_SOURCES, workspace_root=workspace_root, include_root=include_root, cc=args.cc, cpp=args.cpp, assembler=args.assembler, build_dir=build_root / 'at386/hd', extra_define='-DWINI', prepend=bsymvals)

    fdboot_path = build_root / 'fdboot.elf'
    hdboot_path = build_root / 'hdboot'
    link_boot_image(workspace_root, boot_at386_root / 'mapfile', fdboot_path, fd_boot + fd_bootlib)
    link_boot_image(workspace_root, boot_at386_root / 'mapfile', hdboot_path, hd_boot + hd_bootlib)

    # Preserve linked, unstripped images for source-level boot debugging.
    shutil.copyfile(fdboot_path, build_root / 'fdboot.debug.elf')
    shutil.copyfile(hdboot_path, build_root / 'hdboot.debug.elf')

    run([args.strip, str(fdboot_path)])
    run([args.strip, str(hdboot_path)])

    fdboot_binary = build_root / 'fdboot'
    run([
        sys.executable,
        str(kernel_root / 'tools/boot_rmhdr.py'),
        '--pad-to',
        str(AT386_FDBOOT_LOADED_SECTORS * AT386_SECTOR_SIZE),
        '--pad-byte',
        hex(AT386_BOOT_FILL_BYTE),
        str(fdboot_path),
        str(fdboot_binary),
    ])

    install_boot_artifacts(system_root, fdboot_binary, hdboot_path, boot_at386_root / 'default')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())