#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
KERNEL_ROOT = SCRIPT_ROOT.parent
REWRITER = SCRIPT_ROOT / 'ansi_c_rewrite.py'


def shell_join(parts: list[str]) -> str:
    return ' '.join(subprocess.list2cmdline([part]) for part in parts)


def auto_flags_for(source: Path) -> list[str]:
    resolved = source.resolve()
    source_text = str(resolved)
    if '/uts/i386/os/' in source_text:
        return [
            '-std=gnu89',
            '-fcommon',
            '-fno-builtin',
            '-O2',
            '-m32',
            f'-I{KERNEL_ROOT / "i386"}',
            '-D_KERNEL',
            '-DAT386',
            '-DWEITEK',
        ]
    raise SystemExit(f'error: no automatic validation flags known for {source}')


def run_checked(command: list[str], description: str) -> None:
    print(f'==> {description}')
    print(shell_join(command))
    subprocess.run(command, check=True)


def run_report_only(command: list[str], description: str) -> int:
    print(f'==> {description}')
    print(shell_join(command))
    completed = subprocess.run(command, check=False)
    print(f'{description} exited with status {completed.returncode}')
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Run the staged SVR4 legacy-C normalization workflow on a single translation unit.'
    )
    parser.add_argument('source', type=Path, help='Path to the source file to process')
    parser.add_argument('--output', type=Path, help='Write the transformed file to this path')
    parser.add_argument('--keep-output', action='store_true', help='Keep the transformed temp file when no --output is given')
    parser.add_argument('--skip-rewrite', action='store_true', help='Do not run the ANSI rewriter')
    parser.add_argument('--skip-syntax', action='store_true', help='Do not run clang -fsyntax-only validation')
    parser.add_argument('--skip-tidy', action='store_true', help='Do not run clang-tidy')
    parser.add_argument('--strict-syntax', action='store_true', help='Fail if clang -fsyntax-only reports diagnostics')
    parser.add_argument('--cocci', action='append', default=[], help='Path to a .cocci patch to apply; can be repeated')
    parser.add_argument(
        '--clang-tidy-checks',
        default='bugprone-assignment-in-if-condition',
        help='Comma-separated clang-tidy checks to run after normalization',
    )
    parser.add_argument('--strict-tidy', action='store_true', help='Fail if clang-tidy reports diagnostics')
    parser.add_argument(
        '--extra-clang-arg',
        action='append',
        default=[],
        help='Additional arguments to pass to both clang and clang-tidy',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f'error: source file not found: {source}')

    flags = auto_flags_for(source)
    flags.extend(args.extra_clang_arg)

    cocci_paths = [Path(item).resolve() for item in args.cocci]

    for patch in cocci_paths:
        if not patch.exists():
            raise SystemExit(f'error: .cocci patch not found: {patch}')

    with tempfile.TemporaryDirectory(prefix='legacy-c-pipeline-') as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        destination = args.output.resolve() if args.output is not None else temp_dir / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

        if not args.skip_rewrite:
            run_checked(
                [sys.executable, str(REWRITER), str(destination), '--in-place'],
                'Normalize old-style definitions and declarations',
            )

        for patch in cocci_paths:
            run_checked(
                ['spatch', '--sp-file', str(patch), '--in-place', str(destination)],
                f'Apply semantic patch {patch.name}',
            )

        if not args.skip_syntax:
            syntax_status = run_report_only(
                ['clang', *flags, '-fsyntax-only', str(destination)],
                'Validate transformed file with clang -fsyntax-only',
            )
            if args.strict_syntax and syntax_status != 0:
                raise SystemExit(syntax_status)

        if not args.skip_tidy:
            tidy_status = run_report_only(
                ['clang-tidy', str(destination), f'--checks=-*,{args.clang_tidy_checks}', '--', *flags],
                'Run clang-tidy on transformed file',
            )
            if args.strict_tidy and tidy_status != 0:
                raise SystemExit(tidy_status)

        if args.output is None and args.keep_output:
            kept = source.with_suffix(source.suffix + '.normalized.c')
            shutil.copy2(destination, kept)
            print(f'Kept transformed file at {kept}')
        elif args.output is not None:
            print(f'Wrote transformed file to {destination}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())