#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import re


PREFIX_BYTES = {
    'addr16': '0x67',
    'data16': '0x66',
}

AMBIGUOUS_MNEMONICS = {
    'adc',
    'add',
    'and',
    'cmp',
    'dec',
    'div',
    'inc',
    'mov',
    'mul',
    'neg',
    'not',
    'or',
    'rcl',
    'shl',
    'sub',
    'test',
}
REGISTER_TOKEN = re.compile(r'%[A-Za-z][A-Za-z0-9]*')
MEMORY_ADDRESSING = re.compile(r'\([^)]*\)|\[[^]]*\]')
SEGMENT_PREFIX = re.compile(r'%(?:[cdefgs]s):')
INSTRUCTION_LINE = re.compile(
    r'^(?P<indent>\s*)(?:(?P<label>[A-Za-z_.$][\w.$]*):\s*)?(?P<mnemonic>[A-Za-z]+)(?P<rest>\s+.*)?$'
)


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
            if index == 0 or line[index - 1] != '\\':
                return index
    return -1


def rewrite_legacy_comment_syntax(source_text: str) -> str:
    rewritten: list[str] = []
    for line in source_text.splitlines():
        comment_index = find_comment_index(line)
        if comment_index == -1:
            rewritten.append(line.replace('\\*', '*').replace('\\/', '/'))
            continue
        normalized = f'{line[:comment_index]}#{line[comment_index + 1:]}'
        rewritten.append(normalized.replace('\\*', '*').replace('\\/', '/'))
    return '\n'.join(rewritten) + '\n'


def normalize_prefix_line(line: str) -> str:
    stripped = line.strip()
    prefix_byte = PREFIX_BYTES.get(stripped)
    if prefix_byte is None:
        return line
    indent = line[: len(line) - len(line.lstrip())]
    return f'{indent}.byte\t{prefix_byte}'


def register_tokens(operand_text: str) -> list[str]:
    return REGISTER_TOKEN.findall(operand_text)


def explicit_register_tokens(operand_text: str) -> list[str]:
    scrubbed = MEMORY_ADDRESSING.sub('', operand_text)
    scrubbed = SEGMENT_PREFIX.sub('', scrubbed)
    return register_tokens(scrubbed)


def is_ambiguous_memory_operation(mnemonic: str, operands: str) -> bool:
    if mnemonic not in AMBIGUOUS_MNEMONICS:
        return False
    if '(' not in operands and '[' not in operands and '%gs:' not in operands and '%fs:' not in operands:
        return False
    tokens = explicit_register_tokens(operands)
    for token in tokens:
        if token in {'%gs', '%fs', '%cs', '%ds', '%es', '%ss'}:
            continue
        if token.startswith('%e'):
            return False
    return True


def normalize_ambiguous_instruction(line: str) -> str:
    match = INSTRUCTION_LINE.match(line)
    if match is None:
        return line

    mnemonic = match.group('mnemonic')
    if mnemonic[-1] in {'b', 'w', 'l'} and mnemonic[:-1] in AMBIGUOUS_MNEMONICS:
        return line

    rest = match.group('rest') or ''
    operands = rest.split('#', 1)[0]
    if not is_ambiguous_memory_operation(mnemonic, operands):
        return line

    label = match.group('label')
    prefix = match.group('indent')
    if label:
        prefix = f'{prefix}{label}: '
    return f'{prefix}{mnemonic}l{rest}'


def normalize_legacy_assembly(source_text: str) -> str:
    normalized: list[str] = []
    for line in rewrite_legacy_comment_syntax(source_text).splitlines():
        updated = normalize_prefix_line(line)
        updated = normalize_ambiguous_instruction(updated)
        normalized.append(updated)
    return '\n'.join(normalized) + '\n'


def main() -> int:
    args = sys.argv[1:]
    real_as = '/usr/bin/as'
    if not Path(real_as).exists():
        resolved = shutil.which('as')
        if not resolved:
            raise SystemExit('error: could not locate system assembler')
        real_as = resolved

    source_index = None
    for index in range(len(args) - 1, -1, -1):
        if not args[index].startswith('-'):
            source_index = index
            break

    temp_path: Path | None = None
    if source_index is not None:
        source_path = Path(args[source_index])
        if source_path.suffix in {'.s', '.S', '.i'} and source_path.exists():
            temp_file = tempfile.NamedTemporaryFile('w', suffix=source_path.suffix, delete=False)
            temp_path = Path(temp_file.name)
            temp_file.write(normalize_legacy_assembly(source_path.read_text(encoding='utf-8', errors='replace')))
            temp_file.close()
            args[source_index] = str(temp_path)

    command = [real_as]
    if '--32' not in args:
        command.append('--32')
    command.extend(args)
    try:
        subprocess.run(command, check=True)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())