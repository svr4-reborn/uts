#!/usr/bin/env python3

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


TEXT_ASSIGNMENT = re.compile(r'^text\s*=\s*V(0x[0-9A-Fa-f]+)\s+A(0x[0-9A-Fa-f]+);$')
DATA_ASSIGNMENT = re.compile(r'^data\s*=\s*A(0x[0-9A-Fa-f]+);$')
BSS_ASSIGNMENT = re.compile(r'^bss\s*=\s*A(0x[0-9A-Fa-f]+);$')
SECTION_MAPPING = re.compile(r'^(text|data|bss):(\.[A-Za-z0-9_]+);$')


def resolve_linker() -> str:
    for candidate in ('ld.bfd', '/usr/bin/ld.bfd', '/usr/bin/ld'):
        resolved = shutil.which(candidate) if '/' not in candidate else candidate
        if resolved and Path(resolved).exists():
            return resolved
    raise SystemExit('error: could not locate a compatible system linker')


def translate_mapfile(mapfile_path: Path) -> Path:
    text_start = '0x0'
    data_align = '0x1000'
    bss_align = '0x4'
    text_sections = ['*(.text .text.*)']
    data_sections = ['*(.data .data.*)', '*(.rodata .rodata.*)']
    bss_sections = ['*(.bss .bss.* COMMON)']

    for raw_line in mapfile_path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if match := TEXT_ASSIGNMENT.match(line):
            text_start = match.group(1)
            continue
        if match := DATA_ASSIGNMENT.match(line):
            data_align = match.group(1)
            continue
        if match := BSS_ASSIGNMENT.match(line):
            bss_align = match.group(1)
            continue
        if match := SECTION_MAPPING.match(line):
            region, section = match.groups()
            target = {
                'text': text_sections,
                'data': data_sections,
                'bss': bss_sections,
            }[region]
            target.append(f'*({section})')

    script = '\n'.join([
        'OUTPUT_FORMAT(elf32-i386)',
        'SECTIONS',
        '{',
        f'  . = {text_start};',
        f'  .text : {{ {' '.join(text_sections)} }}',
        f'  . = ALIGN({data_align});',
        f'  .data : {{ {' '.join(data_sections)} }}',
        f'  . = ALIGN({bss_align});',
        f'  .bss : {{ {' '.join(bss_sections)} }}',
        '}',
        '',
    ])
    temp_file = tempfile.NamedTemporaryFile('w', suffix='.ld', delete=False)
    temp_file.write(script)
    temp_file.close()
    return Path(temp_file.name)


def main() -> int:
    args = sys.argv[1:]
    linker = resolve_linker()
    translated_mapfile: Path | None = None
    rewritten_args: list[str] = []
    index = 0
    while index < len(args):
        argument = args[index]
        if argument.startswith('-M') and len(argument) > 2:
            translated_mapfile = translate_mapfile(Path(argument[2:]))
            rewritten_args.extend(['-T', str(translated_mapfile)])
            index += 1
            continue
        if argument == '-M' and index + 1 < len(args):
            translated_mapfile = translate_mapfile(Path(args[index + 1]))
            rewritten_args.extend(['-T', str(translated_mapfile)])
            index += 2
            continue
        rewritten_args.append(argument)
        index += 1

    command = [linker]
    if '-m' not in rewritten_args:
        command.extend(['-m', 'elf_i386'])
    command.extend(rewritten_args)
    try:
        subprocess.run(command, check=True)
    finally:
        if translated_mapfile is not None and translated_mapfile.exists():
            translated_mapfile.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())