#!/usr/bin/env python3

# Shared helpers for the two historical-boot build tools (uts_build_boot.py and
# uts_boot_initprog.py). Both compile a fixed list of boot sources "the way the
# old makefiles did": preprocess each legacy .s with cpp, normalize its comment
# syntax for modern GNU as, then assemble. The per-tool source lists, cpp define
# sets and link steps differ and stay in their respective modules; the mechanics
# below are identical and live here.

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def run(command: list[str], cwd: Path | None = None) -> None:
    print(' '.join(command))
    subprocess.run(command, cwd=cwd, check=True)


def resolve_linker(linker: str) -> str:
    # mold cannot do the relocatable/script links these tools need; prefer GNU
    # ld.bfd when the toolchain `ld` is the generic name.
    if Path(linker).name == 'ld':
        bfd_linker = shutil.which('ld.bfd')
        if bfd_linker:
            return bfd_linker
    return linker


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


def rewrite_legacy_comment_syntax(source_text: str) -> str:
    rewritten: list[str] = []
    for line in source_text.splitlines():
        comment_index = find_comment_index(line)
        if comment_index == -1:
            rewritten.append(line.replace('\\*', '*'))
            continue
        rewritten.append(f'{line[:comment_index]}#{line[comment_index + 1:]}'.replace('\\*', '*'))
    return '\n'.join(rewritten) + '\n'


def preprocess_and_assemble(source: Path, output: Path, *, cpp_flags: list[str], cpp: str, assembler: str, build_dir: Path, prepend: Path | None = None) -> None:
    """Preprocess a legacy .s with cpp, normalize comments, then assemble (--32).

    If `prepend` is given its text is concatenated ahead of the source before
    preprocessing (used to make a symbol table visible to the fragment).
    """
    if prepend is not None:
        combined = build_dir / f'{source.stem}.combined.s'
        try:
            with combined.open('w', encoding='utf-8') as handle:
                handle.write(prepend.read_text(encoding='utf-8'))
                handle.write(source.read_text(encoding='utf-8'))
            _cpp_normalize_assemble(combined, output, cpp_flags=cpp_flags, cpp=cpp, assembler=assembler, build_dir=build_dir, stem=source.stem)
        finally:
            combined.unlink(missing_ok=True)
    else:
        _cpp_normalize_assemble(source, output, cpp_flags=cpp_flags, cpp=cpp, assembler=assembler, build_dir=build_dir, stem=source.stem)


def _cpp_normalize_assemble(source: Path, output: Path, *, cpp_flags: list[str], cpp: str, assembler: str, build_dir: Path, stem: str) -> None:
    preprocessed = build_dir / f'{stem}.i'
    sanitized = build_dir / f'{stem}.s'
    run([cpp, *cpp_flags, '-P', str(source), '-o', str(preprocessed)])
    sanitized.write_text(rewrite_legacy_comment_syntax(preprocessed.read_text(encoding='utf-8')), encoding='utf-8')
    run([assembler, '--32', '-o', str(output), str(sanitized)])
