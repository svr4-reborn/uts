#!/usr/bin/env python3

from __future__ import annotations

import argparse
import struct
from pathlib import Path


COFF_FILE_HEADER_SIZE = 20
COFF_SECTION_HEADER_SIZE = 40
ELF_HEADER_SIZE = 52
ELF_PROGRAM_HEADER_SIZE = 32
PT_LOAD = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Strip the container header from a linked boot image.')
    parser.add_argument('input_path')
    parser.add_argument('output_path')
    parser.add_argument('--pad-to', type=lambda value: int(value, 0))
    parser.add_argument('--pad-byte', type=lambda value: int(value, 0), default=0)
    return parser.parse_args()


def coff_payload_offset(payload: bytes) -> int:
    if len(payload) < COFF_FILE_HEADER_SIZE:
        raise ValueError('COFF image is too small to contain a file header')
    f_magic, f_nscns, _f_timdat, _f_symptr, _f_nsyms, f_opthdr, _f_flags = struct.unpack_from('<HHLLLHH', payload, 0)
    if f_magic != 0x14C:
        raise ValueError(f'Unsupported COFF magic: 0x{f_magic:04x}')
    return COFF_FILE_HEADER_SIZE + f_opthdr + (f_nscns * COFF_SECTION_HEADER_SIZE)


def elf_payload_offset(payload: bytes) -> int:
    if len(payload) < ELF_HEADER_SIZE:
        raise ValueError('ELF image is too small to contain a file header')
    if payload[:4] != b'\x7fELF':
        raise ValueError('ELF image does not start with the ELF magic bytes')

    ei_class = payload[4]
    ei_data = payload[5]
    if ei_class != 1 or ei_data != 1:
        raise ValueError('Only 32-bit little-endian ELF boot images are supported')

    e_phoff = struct.unpack_from('<L', payload, 28)[0]
    e_phentsize = struct.unpack_from('<H', payload, 42)[0]
    e_phnum = struct.unpack_from('<H', payload, 44)[0]

    if e_phnum == 0:
        raise ValueError('ELF image contains no program headers')
    if e_phentsize < ELF_PROGRAM_HEADER_SIZE:
        raise ValueError('ELF program header entry is smaller than expected')

    load_offsets: list[int] = []
    for index in range(e_phnum):
        entry_offset = e_phoff + (index * e_phentsize)
        if entry_offset + ELF_PROGRAM_HEADER_SIZE > len(payload):
            raise ValueError('ELF image is truncated in the program header table')
        p_type, p_offset = struct.unpack_from('<LL', payload, entry_offset)
        if p_type == PT_LOAD:
            load_offsets.append(p_offset)

    if not load_offsets:
        raise ValueError('ELF image contains no PT_LOAD program headers')
    return min(load_offsets)


def payload_offset(payload: bytes) -> int:
    if payload.startswith(b'\x7fELF'):
        return elf_payload_offset(payload)
    return coff_payload_offset(payload)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_path)
    output_path = Path(args.output_path)

    payload = input_path.read_bytes()
    offset = payload_offset(payload)
    if offset < 0 or offset > len(payload):
        raise ValueError(f'Computed payload offset {offset} is outside the image')

    binary = payload[offset:]
    if args.pad_to is not None:
        if args.pad_byte < 0 or args.pad_byte > 0xFF:
            raise ValueError(f'Pad byte must fit in one byte, got {args.pad_byte}')
        if len(binary) > args.pad_to:
            raise ValueError(
                f'Boot payload is larger than the requested padded size '
                f'({len(binary)} > {args.pad_to})'
            )
        binary = binary + bytes([args.pad_byte]) * (args.pad_to - len(binary))

    output_path.write_bytes(binary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())