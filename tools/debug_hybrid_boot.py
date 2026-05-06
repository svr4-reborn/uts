#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


DEFAULT_IMAGE = Path('build/boot-media/base01-hybrid-labeled.img')
DEFAULT_SYMBOL_FILE = Path('build/uts/i386/boot/build/fdboot.debug.elf')
DEFAULT_GDB_PORT = 1234
DEFAULT_GDB = 'gdb'
DEFAULT_QEMU = 'qemu-system-i386'
DEFAULT_FDBOOT_PROTECTED_BASE = 0x1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Launch or probe the hybrid AT386 boot floppy under QEMU and GDB.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    launch = subparsers.add_parser('launch', help='Launch QEMU halted at reset with the hybrid floppy attached.')
    add_common_args(launch)
    launch.add_argument('--foreground', action='store_true', help='Run QEMU in the foreground instead of replacing this process.')

    probe = subparsers.add_parser('probe', help='Run a canned GDB probe against the hybrid floppy.')
    add_common_args(probe)
    probe.add_argument(
        '--mode',
        choices=['entry', 'handoff', 'main'],
        default='handoff',
        help='Which built-in GDB probe to run.',
    )
    probe.add_argument('--timeout', type=float, default=20.0, help='Timeout in seconds for the GDB probe.')
    return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--image', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--symbol-file', type=Path, default=DEFAULT_SYMBOL_FILE)
    parser.add_argument('--gdb-port', type=int, default=DEFAULT_GDB_PORT)
    parser.add_argument('--qemu', default=DEFAULT_QEMU)
    parser.add_argument('--gdb', default=DEFAULT_GDB)
    parser.add_argument('--fdboot-base', type=lambda value: int(value, 0), default=DEFAULT_FDBOOT_PROTECTED_BASE)


def build_qemu_command(args: argparse.Namespace) -> list[str]:
    return [
        args.qemu,
        '-display',
        'none',
        '-no-reboot',
        '-no-shutdown',
        '-boot',
        'a',
        '-S',
        '-gdb',
        f'tcp::{args.gdb_port}',
        '-drive',
        f'file={args.image},format=raw,if=floppy',
    ]


def wait_for_port(port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                return
        time.sleep(0.1)
    raise SystemExit(f'error: GDB port {port} did not open within {timeout:.1f}s')


def read_symbol_offsets(symbol_file: Path) -> dict[str, int]:
    result = subprocess.run(
        ['nm', '-n', str(symbol_file)],
        check=True,
        capture_output=True,
        text=True,
    )
    offsets: dict[str, int] = {}
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split()
        if len(parts) < 3:
            continue
        value_text, _, name = parts[:3]
        if name == 'main':
            offsets[name] = int(value_text, 16)
    return offsets


def read_section_offsets(symbol_file: Path) -> dict[str, int]:
    result = subprocess.run(
        ['objdump', '-h', str(symbol_file)],
        check=True,
        capture_output=True,
        text=True,
    )
    offsets: dict[str, int] = {}
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split()
        if len(parts) < 7:
            continue
        name = parts[1]
        if name not in {'.text', '.data', '.bss'}:
            continue
        offsets[name] = int(parts[3], 16)
    return offsets


def build_gdb_commands(mode: str, symbol_file: Path, fdboot_base: int) -> list[str]:
    commands = [
        'set pagination off',
        'set confirm off',
        'set disassemble-next-line on',
        'set breakpoint pending on',
        'set remote hardware-breakpoint-limit 0',
        'set architecture i8086',
        'target remote :1234',
        'tbreak *0x7c00',
        'continue',
        'printf "\\n== boot entry ==\\n"',
        'x/12i $pc',
        'info registers',
    ]
    if mode == 'entry':
        return commands

    commands.extend(
        [
            'tbreak *0x7c1e',
            'continue',
            'printf "\\n== before readboot call ==\\n"',
            'x/8i $pc',
            'info registers',
            'tbreak *0x7c29',
            'continue',
            'printf "\\n== at lret handoff ==\\n"',
            'x/8i $pc',
            'info registers',
            'si',
            'printf "\\n== after lret ==\\n"',
            'x/12i $pc',
            'info registers',
        ]
    )
    if mode == 'handoff':
        return commands

    symbol_offsets = read_symbol_offsets(symbol_file)
    section_offsets = read_section_offsets(symbol_file)
    main_address = fdboot_base + symbol_offsets['main']
    data_address = fdboot_base + section_offsets['.data']
    bss_address = fdboot_base + section_offsets['.bss']

    commands.extend(
        [
            'set architecture i386',
            'set $eflags = $eflags & ~0x100',
            f'add-symbol-file {symbol_file} 0x{fdboot_base:x} -s .data 0x{data_address:x} -s .bss 0x{bss_address:x}',
            f'tbreak *0x{main_address:x}',
            'continue',
            'printf "\\n== after main breakpoint attempt ==\\n"',
            'info symbol $pc',
            'bt',
            'info registers eip esp eax ebx ecx edx esi edi ebp cs ds es ss eflags',
        ]
    )
    return commands


def run_gdb_probe(args: argparse.Namespace) -> int:
    qemu_command = build_qemu_command(args)
    qemu = subprocess.Popen(qemu_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for_port(args.gdb_port, 5.0)
        gdb_commands = build_gdb_commands(args.mode, args.symbol_file.resolve(), args.fdboot_base)
        gdb_commands = [command.replace(':1234', f':{args.gdb_port}') for command in gdb_commands]
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
            for command in gdb_commands:
                handle.write(command)
                handle.write('\n')
            command_file = Path(handle.name)
        try:
            result = subprocess.run(
                [args.gdb, '-q', '-batch', '-x', str(command_file)],
                check=False,
                timeout=args.timeout,
                text=True,
            )
        finally:
            command_file.unlink(missing_ok=True)
        return result.returncode
    finally:
        qemu.terminate()
        try:
            qemu.wait(timeout=3)
        except subprocess.TimeoutExpired:
            qemu.kill()
            qemu.wait(timeout=3)
        if qemu.stdout is not None:
            output = qemu.stdout.read().strip()
            if output:
                print('\n== qemu output ==')
                print(output)


def run_launch(args: argparse.Namespace) -> int:
    qemu_command = build_qemu_command(args)
    attach = f"{args.gdb} -ex 'set architecture i8086' -ex 'target remote :{args.gdb_port}'"
    print('QEMU command:')
    print(' '.join(qemu_command))
    print('\nGDB attach command:')
    print(attach)
    if args.foreground:
        return subprocess.call(qemu_command)
    os.execvp(qemu_command[0], qemu_command)
    return 0


def main() -> int:
    args = parse_args()
    if not args.image.exists():
        raise SystemExit(f'error: image not found: {args.image}')
    if args.command == 'probe' and args.mode == 'main' and not args.symbol_file.exists():
        raise SystemExit(f'error: symbol file not found: {args.symbol_file}')
    if args.command == 'launch':
        return run_launch(args)
    return run_gdb_probe(args)


if __name__ == '__main__':
    raise SystemExit(main())