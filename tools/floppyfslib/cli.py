from __future__ import annotations

import argparse
from pathlib import Path

from .core import detect_layout
from .ops import (
    build_hybrid_image,
    diff_s5_file,
    extract_s5_file,
    load_replacement_set,
    print_layout,
    replace_s5_file,
    validate_replacements,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Inspect and build SVR4 boot floppy images.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    inspect_parser = subparsers.add_parser('inspect', help='Inspect a floppy image layout and list root entries when possible')
    inspect_parser.add_argument('--image', required=True)
    inspect_parser.add_argument('--report-json')

    hybrid_parser = subparsers.add_parser('build-hybrid', help='Build a hybrid image using a reference floppy and a locally built bootloader')
    hybrid_parser.add_argument('--reference-image', required=True)
    hybrid_parser.add_argument('--bootloader', required=True)
    hybrid_parser.add_argument('--output', required=True)
    hybrid_parser.add_argument('--report-json')
    hybrid_parser.add_argument('--replacement-manifest')
    hybrid_parser.add_argument('--replacement-set')
    hybrid_parser.add_argument('--replace-s5-file', action='append', default=[], metavar='PATH=SOURCE')

    replace_parser = subparsers.add_parser('replace-s5-file', help='Replace an existing file inside the first detected s5 filesystem')
    replace_parser.add_argument('--image', required=True)
    replace_parser.add_argument('--target-path', required=True)
    replace_parser.add_argument('--source', required=True)
    replace_parser.add_argument('--output')

    validate_parser = subparsers.add_parser('validate-replacements', help='Validate one or more s5 replacements against an image without writing changes')
    validate_parser.add_argument('--image', required=True)
    validate_parser.add_argument('--replacement-manifest')
    validate_parser.add_argument('--replacement-set')
    validate_parser.add_argument('--replace-s5-file', action='append', default=[], metavar='PATH=SOURCE')

    extract_parser = subparsers.add_parser('extract-s5-file', help='Extract an existing file from the first detected s5 filesystem')
    extract_parser.add_argument('--image', required=True)
    extract_parser.add_argument('--target-path', required=True)
    extract_parser.add_argument('--output', required=True)

    diff_parser = subparsers.add_parser('diff-s5-file', help='Compare an existing file inside the first detected s5 filesystem with a host file')
    diff_parser.add_argument('--image', required=True)
    diff_parser.add_argument('--target-path', required=True)
    diff_parser.add_argument('--source', required=True)
    return parser.parse_args()


def parse_replacements(values: list[str]) -> list[tuple[str, Path]]:
    replacements: list[tuple[str, Path]] = []
    for value in values:
        if '=' not in value:
            raise SystemExit(f'error: invalid replacement specification {value!r}; expected PATH=SOURCE')
        target, source = value.split('=', 1)
        if not target:
            raise SystemExit(f'error: invalid replacement specification {value!r}; missing target path')
        replacements.append((target, Path(source)))
    return replacements


def collect_replacements(cli_values: list[str], manifest: str | None, set_name: str | None) -> list[tuple[str, Path]]:
    replacements: list[tuple[str, Path]] = []
    if manifest or set_name:
        if not manifest or not set_name:
            raise SystemExit('error: --replacement-manifest and --replacement-set must be provided together')
        replacements.extend(load_replacement_set(Path(manifest), set_name))
    replacements.extend(parse_replacements(cli_values))
    return replacements


def main() -> int:
    args = parse_args()
    if args.command == 'inspect':
        layout = detect_layout(Path(args.image))
        print_layout(layout, Path(args.report_json) if args.report_json else None)
        return 0
    if args.command == 'build-hybrid':
        build_hybrid_image(
            Path(args.reference_image),
            Path(args.bootloader),
            Path(args.output),
            Path(args.report_json) if args.report_json else None,
            collect_replacements(getattr(args, 'replace_s5_file', []) or [], getattr(args, 'replacement_manifest', None), getattr(args, 'replacement_set', None)),
        )
        return 0
    if args.command == 'replace-s5-file':
        replace_s5_file(Path(args.image), args.target_path, Path(args.source), Path(args.output) if args.output else None)
        return 0
    if args.command == 'validate-replacements':
        validate_replacements(Path(args.image), collect_replacements(getattr(args, 'replace_s5_file', []) or [], getattr(args, 'replacement_manifest', None), getattr(args, 'replacement_set', None)))
        return 0
    if args.command == 'extract-s5-file':
        extract_s5_file(Path(args.image), args.target_path, Path(args.output))
        return 0
    if args.command == 'diff-s5-file':
        return 0 if diff_s5_file(Path(args.image), args.target_path, Path(args.source)) else 1
    raise SystemExit(f'error: unsupported command {args.command}')
