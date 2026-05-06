#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


STRING_PATTERN = re.compile(r'^\s*\.string\s+"([^"]+)"')
FOURBYTE_PATTERN = re.compile(r'\.4byte\s+([^;\s]+)')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Extract .set directives from compiler-generated assembly debug data.')
    parser.add_argument('assembly_path')
    return parser.parse_args()


def load_requested_symbols() -> list[str]:
    symbols: list[str] = []
    for raw_line in sys.stdin:
        symbol = raw_line.strip()
        if symbol:
            symbols.append(symbol)
    return symbols


def extract_symbol_values(lines: list[str], wanted: set[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        match = STRING_PATTERN.match(line)
        if not match:
            index += 1
            continue

        symbol = match.group(1)
        if symbol not in wanted or symbol in values:
            index += 1
            continue

        probe = index + 1
        while probe < len(lines):
            fourbyte = FOURBYTE_PATTERN.search(lines[probe])
            if fourbyte:
                values[symbol] = fourbyte.group(1)
                break
            if STRING_PATTERN.match(lines[probe]):
                break
            probe += 1
        index = probe
    return values


def main() -> int:
    args = parse_args()
    assembly_path = Path(args.assembly_path)
    symbols = load_requested_symbols()
    if not symbols:
        return 0

    lines = assembly_path.read_text(encoding='utf-8', errors='replace').splitlines()
    values = extract_symbol_values(lines, set(symbols))

    missing = [symbol for symbol in symbols if symbol not in values]
    if missing:
        raise SystemExit(f'error: setfilter could not find values for: {", ".join(missing)}')

    for symbol in symbols:
        print(f'\t.set\t{symbol},\t{values[symbol]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())