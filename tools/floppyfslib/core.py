from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SECTOR_SIZE = 512
S5_MAGIC = 0xFD187E20
S5_MAGIC_OFFSET = 504
S5_SUPER_OFFSET = 512
BFS_MAGIC = 0x1BADFACE
UFS_MAGIC = 0x00011954
S5_ROOT_INODE = 2
S5_DINODE_SIZE = 64
S5_DIR_ENTRY_SIZE = 16
S5_DIR_NAME_SIZE = 14
S5_DIRECT_BLOCKS = 10
S5_INDIRECT_POINTER_SIZE = 4
S5_NICFREE = 50
S5_SUPER_NFREE_OFFSET = 8
S5_SUPER_FREE_OFFSET = 12
S5_SUPER_FMOD_OFFSET = 416
S5_SUPER_TIME_OFFSET = 420
S5_SUPER_TFREE_OFFSET = 432
S5_FBLK_NFREE_OFFSET = 0
S5_FBLK_FREE_OFFSET = 4
BFS_ROOT_INODE = 2
BFS_SUPER_SIZE = 512
BFS_DIRENT_SIZE = 56
BFS_LDIR_SIZE = 16
UFS_ROOT_INODE = 2
UFS_SB_OFFSET = 8192
UFS_SB_SIZE = 8192
UFS_DIRBLKSIZ = 512
UFS_DINODE_SIZE = 128
UFS_NDADDR = 12
UFS_FS_MAGIC_OFFSET = 1372
UFS_FS_BSIZE_OFFSET = 48
UFS_FS_FSIZE_OFFSET = 52
UFS_FS_FRAG_OFFSET = 56
UFS_FS_FSBTODB_OFFSET = 100
UFS_FS_INOPB_OFFSET = 120
UFS_FS_CGOFFSET_OFFSET = 24
UFS_FS_CGMASK_OFFSET = 28
UFS_FS_IBLKNO_OFFSET = 16
UFS_FS_IPG_OFFSET = 184
UFS_FS_FPG_OFFSET = 188
UFS_DI_MODE_OFFSET = 112
UFS_DI_SIZE_OFFSET = 8
UFS_DI_DB_OFFSET = 40
UFS_DI_IB_OFFSET = 88


def _i32(buffer: bytes, offset: int) -> int:
    return int.from_bytes(buffer[offset:offset + 4], 'little', signed=True)


def _u16(buffer: bytes, offset: int) -> int:
    return int.from_bytes(buffer[offset:offset + 2], 'little', signed=False)


def _u32(buffer: bytes, offset: int) -> int:
    return int.from_bytes(buffer[offset:offset + 4], 'little', signed=False)


@dataclass(frozen=True)
class FilesystemCandidate:
    kind: str
    start_offset: int
    super_offset: int
    block_size: int | None = None
    details: dict[str, int | str] = field(default_factory=dict)
    root_entries: list[dict[str, int | str]] = field(default_factory=list)


@dataclass(frozen=True)
class ImageLayout:
    image_path: str
    image_size: int
    boot_region_size: int
    filesystems: list[FilesystemCandidate]
    root_entries: list[dict[str, int | str]] = field(default_factory=list)


def detect_s5(image: bytes) -> list[FilesystemCandidate]:
    candidates: list[FilesystemCandidate] = []
    magic = S5_MAGIC.to_bytes(4, 'little')
    search_from = 0
    while True:
        magic_offset = image.find(magic, search_from)
        if magic_offset < 0:
            break
        super_offset = magic_offset - S5_MAGIC_OFFSET
        fs_start = super_offset - S5_SUPER_OFFSET
        search_from = magic_offset + 1
        if fs_start < 0 or fs_start % SECTOR_SIZE != 0:
            continue
        if super_offset < 0 or super_offset + 512 > len(image):
            continue
        superblock = image[super_offset:super_offset + 512]
        s_type = _u32(superblock, 508)
        block_size = {1: 512, 2: 1024, 4: 2048}.get(s_type)
        if block_size is None:
            continue
        s_isize = _u16(superblock, 0)
        if s_isize < 2:
            continue
        candidates.append(
            FilesystemCandidate(
                kind='s5',
                start_offset=fs_start,
                super_offset=super_offset,
                block_size=block_size,
                details={
                    's_type': s_type,
                    's_isize': s_isize,
                    's_fsize': _u32(superblock, 4),
                },
            )
        )
    return _unique_candidates(candidates)


def detect_bfs(image: bytes) -> list[FilesystemCandidate]:
    candidates: list[FilesystemCandidate] = []
    magic = BFS_MAGIC.to_bytes(4, 'little')
    search_from = 0
    while True:
        offset = image.find(magic, search_from)
        if offset < 0:
            break
        search_from = offset + 1
        if offset % SECTOR_SIZE != 0:
            continue
        if offset + BFS_SUPER_SIZE > len(image):
            continue
        data_start = _u32(image, offset + 4)
        data_end = _u32(image, offset + 8)
        if data_start < BFS_SUPER_SIZE or data_end < data_start or offset + data_end >= len(image):
            continue
        candidates.append(
            FilesystemCandidate(
                kind='bfs',
                start_offset=offset,
                super_offset=offset,
                block_size=SECTOR_SIZE,
                details={'data_start': data_start, 'data_end': data_end},
            )
        )
    return _unique_candidates(candidates)


def detect_ufs(image: bytes) -> list[FilesystemCandidate]:
    candidates: list[FilesystemCandidate] = []
    for fs_start in range(0, max(0, len(image) - (UFS_SB_OFFSET + UFS_FS_MAGIC_OFFSET + 4)) + 1, SECTOR_SIZE):
        super_offset = fs_start + UFS_SB_OFFSET
        if super_offset + UFS_SB_SIZE > len(image):
            break
        if _u32(image, super_offset + UFS_FS_MAGIC_OFFSET) != UFS_MAGIC:
            continue
        block_size = _u32(image, super_offset + UFS_FS_BSIZE_OFFSET)
        fragment_size = _u32(image, super_offset + UFS_FS_FSIZE_OFFSET)
        inodes_per_block = _u32(image, super_offset + UFS_FS_INOPB_OFFSET)
        inodes_per_group = _u32(image, super_offset + UFS_FS_IPG_OFFSET)
        fragments_per_group = _u32(image, super_offset + UFS_FS_FPG_OFFSET)
        if block_size < 4096 or block_size > UFS_SB_SIZE:
            continue
        if fragment_size < SECTOR_SIZE or fragment_size > block_size:
            continue
        if inodes_per_block == 0 or inodes_per_group == 0 or fragments_per_group == 0:
            continue
        candidates.append(
            FilesystemCandidate(
                kind='ufs',
                start_offset=fs_start,
                super_offset=super_offset,
                block_size=block_size,
                details={
                    'bsize': block_size,
                    'fsize': fragment_size,
                    'frag': _u32(image, super_offset + UFS_FS_FRAG_OFFSET),
                    'ipg': inodes_per_group,
                    'fpg': fragments_per_group,
                    'inopb': inodes_per_block,
                    'fsbtodb': _u32(image, super_offset + UFS_FS_FSBTODB_OFFSET),
                    'cgoffset': _u32(image, super_offset + UFS_FS_CGOFFSET_OFFSET),
                    'cgmask': _u32(image, super_offset + UFS_FS_CGMASK_OFFSET),
                    'iblkno': _u32(image, super_offset + UFS_FS_IBLKNO_OFFSET),
                    'fragshift': _i32(image, super_offset + 96),
                },
            )
        )
    return _unique_candidates(candidates)


def _unique_candidates(candidates: list[FilesystemCandidate]) -> list[FilesystemCandidate]:
    seen: set[tuple[str, int, int]] = set()
    unique: list[FilesystemCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.start_offset, item.kind, item.super_offset)):
        key = (candidate.kind, candidate.start_offset, candidate.super_offset)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def detect_layout(image_path: Path) -> ImageLayout:
    image = image_path.read_bytes()
    filesystems = [*detect_s5(image), *detect_bfs(image), *detect_ufs(image)]
    filesystems.sort(key=lambda item: (item.start_offset, item.kind))
    if not filesystems:
        raise SystemExit(f'error: no supported filesystem signatures found in {image_path}')
    populated_filesystems: list[FilesystemCandidate] = []
    for filesystem in filesystems:
        entries: list[dict[str, int | str]] = []
        if filesystem.kind == 's5':
            entries = list_s5_root(image, filesystem)
        elif filesystem.kind == 'bfs':
            entries = list_bfs_root(image, filesystem)
        elif filesystem.kind == 'ufs':
            entries = list_ufs_root(image, filesystem)
        populated_filesystems.append(
            FilesystemCandidate(
                kind=filesystem.kind,
                start_offset=filesystem.start_offset,
                super_offset=filesystem.super_offset,
                block_size=filesystem.block_size,
                details=filesystem.details,
                root_entries=entries,
            )
        )
    root_entries = populated_filesystems[0].root_entries if populated_filesystems else []
    return ImageLayout(
        image_path=str(image_path),
        image_size=len(image),
        boot_region_size=populated_filesystems[0].start_offset,
        filesystems=populated_filesystems,
        root_entries=root_entries,
    )


def list_s5_root(image: bytes, filesystem: FilesystemCandidate) -> list[dict[str, int | str]]:
    block_size = filesystem.block_size
    if block_size is None:
        return []
    root_inode = read_s5_inode(image, filesystem.start_offset, block_size, S5_ROOT_INODE)
    if root_inode is None:
        return []
    entries: list[dict[str, int | str]] = []
    directory_bytes = read_s5_file(image, filesystem.start_offset, block_size, root_inode)
    for offset in range(0, min(len(directory_bytes), int(root_inode['size'])), S5_DIR_ENTRY_SIZE):
        inode_number = _u16(directory_bytes, offset)
        if inode_number == 0:
            continue
        raw_name = directory_bytes[offset + 2:offset + 2 + S5_DIR_NAME_SIZE]
        name = raw_name.split(b'\0', 1)[0].decode('ascii', errors='replace').strip()
        if not name:
            continue
        inode = read_s5_inode(image, filesystem.start_offset, block_size, inode_number)
        entry: dict[str, int | str] = {'name': name, 'inode': inode_number}
        if inode is not None:
            entry['size'] = inode['size']
        entries.append(entry)
    entries.sort(key=lambda item: str(item['name']))
    return entries


def list_bfs_root(image: bytes, filesystem: FilesystemCandidate) -> list[dict[str, int | str]]:
    root_dirent = read_bfs_dirent(image, filesystem.start_offset, BFS_ROOT_INODE)
    if root_dirent is None:
        return []
    directory_start = filesystem.start_offset + (root_dirent['d_sblock'] * SECTOR_SIZE)
    directory_end = filesystem.start_offset + root_dirent['d_eoffset'] + 1
    if directory_end <= directory_start or directory_end > len(image):
        return []
    entries: list[dict[str, int | str]] = []
    directory_bytes = image[directory_start:directory_end]
    for offset in range(0, len(directory_bytes), BFS_LDIR_SIZE):
        inode_number = _u16(directory_bytes, offset)
        if inode_number == 0:
            continue
        name = directory_bytes[offset + 2:offset + 16].split(b'\0', 1)[0].decode('ascii', errors='replace').strip()
        if not name:
            continue
        inode = read_bfs_dirent(image, filesystem.start_offset, inode_number)
        entry: dict[str, int | str] = {'name': name, 'inode': inode_number}
        if inode is not None and inode['d_sblock'] != 0:
            entry['size'] = (inode['d_eoffset'] - (inode['d_sblock'] * SECTOR_SIZE)) + 1
        entries.append(entry)
    entries.sort(key=lambda item: str(item['name']))
    return entries


def list_ufs_root(image: bytes, filesystem: FilesystemCandidate) -> list[dict[str, int | str]]:
    fs = filesystem.details
    root_inode = read_ufs_inode(image, filesystem.start_offset, fs, UFS_ROOT_INODE)
    if root_inode is None:
        return []
    entries: list[dict[str, int | str]] = []
    directory_bytes = read_ufs_file(image, filesystem.start_offset, fs, root_inode)
    offset = 0
    max_length = min(len(directory_bytes), int(root_inode['size']))
    while offset + 8 <= max_length:
        inode_number = _u32(directory_bytes, offset)
        record_length = _u16(directory_bytes, offset + 4)
        name_length = _u16(directory_bytes, offset + 6)
        if record_length == 0:
            break
        if inode_number != 0 and 0 < name_length <= 255 and offset + 8 + name_length <= max_length:
            name = directory_bytes[offset + 8:offset + 8 + name_length].decode('ascii', errors='replace')
            inode = read_ufs_inode(image, filesystem.start_offset, fs, inode_number)
            entry: dict[str, int | str] = {'name': name, 'inode': inode_number}
            if inode is not None:
                entry['size'] = int(inode['size'])
            entries.append(entry)
        offset += record_length
    entries.sort(key=lambda item: str(item['name']))
    return entries


def read_s5_inode(image: bytes, fs_start: int, block_size: int, inode_number: int) -> dict[str, int | list[int]] | None:
    inodes_per_block = block_size // S5_DINODE_SIZE
    block_number = (inode_number + (2 * inodes_per_block - 1)) // inodes_per_block
    inode_index = (inode_number + (2 * inodes_per_block - 1)) % inodes_per_block
    inode_offset = fs_start + (block_number * block_size) + (inode_index * S5_DINODE_SIZE)
    if inode_offset + S5_DINODE_SIZE > len(image):
        return None
    raw = image[inode_offset:inode_offset + S5_DINODE_SIZE]
    addresses = [int.from_bytes(raw[12 + (index * 3):15 + (index * 3)] + b'\0', 'little', signed=False) for index in range(13)]
    return {'mode': _u16(raw, 0), 'size': _u32(raw, 8), 'addresses': addresses}


def read_bfs_dirent(image: bytes, fs_start: int, inode_number: int) -> dict[str, int] | None:
    inode_offset = fs_start + BFS_SUPER_SIZE + ((inode_number - BFS_ROOT_INODE) * BFS_DIRENT_SIZE)
    if inode_offset < fs_start or inode_offset + BFS_DIRENT_SIZE > len(image):
        return None
    raw = image[inode_offset:inode_offset + BFS_DIRENT_SIZE]
    return {'d_ino': _u16(raw, 0), 'd_sblock': _u32(raw, 4), 'd_eblock': _u32(raw, 8), 'd_eoffset': _u32(raw, 12)}


def read_ufs_inode(image: bytes, fs_start: int, fs: dict[str, Any], inode_number: int) -> dict[str, int | list[int]] | None:
    inode_block = ufs_itod(fs, inode_number)
    inode_offset = fs_start + ufs_fsbtobytes(fs, inode_block) + (ufs_itoo(fs, inode_number) * UFS_DINODE_SIZE)
    if inode_offset < fs_start or inode_offset + UFS_DINODE_SIZE > len(image):
        return None
    raw = image[inode_offset:inode_offset + UFS_DINODE_SIZE]
    direct_blocks = [_u32(raw, UFS_DI_DB_OFFSET + (index * 4)) for index in range(UFS_NDADDR)]
    indirect_blocks = [_u32(raw, UFS_DI_IB_OFFSET + (index * 4)) for index in range(3)]
    size = int.from_bytes(raw[UFS_DI_SIZE_OFFSET:UFS_DI_SIZE_OFFSET + 8], 'little', signed=False)
    return {'mode': _u32(raw, UFS_DI_MODE_OFFSET), 'size': size, 'direct_blocks': direct_blocks, 'indirect_blocks': indirect_blocks}


def read_s5_file(image: bytes, fs_start: int, block_size: int, inode: dict[str, int | list[int]]) -> bytes:
    size = int(inode['size'])
    data = bytearray()
    for address in s5_file_block_numbers(image, fs_start, block_size, inode):
        if address == 0:
            data.extend(b'\0' * block_size)
        else:
            block_offset = fs_start + (address * block_size)
            data.extend(image[block_offset:block_offset + block_size])
        if len(data) >= size:
            return bytes(data[:size])
    return bytes(data[:size])


def s5_file_block_numbers(image: bytes, fs_start: int, block_size: int, inode: dict[str, int | list[int]]) -> list[int]:
    addresses = inode['addresses']
    if not isinstance(addresses, list):
        return []
    size = int(inode['size'])
    if size <= 0:
        return []
    blocks_needed = (size + block_size - 1) // block_size
    block_numbers: list[int] = []
    direct_count = min(S5_DIRECT_BLOCKS, blocks_needed)
    block_numbers.extend(int(address) for address in addresses[:direct_count])
    remaining = blocks_needed - len(block_numbers)
    for levels, address in enumerate(addresses[S5_DIRECT_BLOCKS:S5_DIRECT_BLOCKS + 3], start=1):
        if remaining <= 0:
            break
        block_numbers.extend(s5_expand_indirect_block_numbers(image, fs_start, block_size, int(address), levels, remaining))
        remaining = blocks_needed - len(block_numbers)
    return block_numbers[:blocks_needed]


def s5_expand_indirect_block_numbers(image: bytes, fs_start: int, block_size: int, block_address: int, levels: int, remaining: int) -> list[int]:
    if remaining <= 0 or levels <= 0:
        return []
    capacity = s5_indirect_capacity(block_size, levels)
    take = min(remaining, capacity)
    if block_address == 0:
        return [0] * take
    entries = s5_read_indirect_block(image, fs_start, block_size, block_address)
    if levels == 1:
        result = [int(entry) for entry in entries[:take]]
        if len(result) < take:
            result.extend([0] * (take - len(result)))
        return result
    result: list[int] = []
    subtree_capacity = s5_indirect_capacity(block_size, levels - 1)
    for entry in entries:
        if len(result) >= take:
            break
        result.extend(s5_expand_indirect_block_numbers(image, fs_start, block_size, int(entry), levels - 1, min(take - len(result), subtree_capacity)))
    if len(result) < take:
        result.extend([0] * (take - len(result)))
    return result


def s5_indirect_capacity(block_size: int, levels: int) -> int:
    return (block_size // S5_INDIRECT_POINTER_SIZE) ** levels


def s5_read_indirect_block(image: bytes, fs_start: int, block_size: int, block_address: int) -> list[int]:
    block_offset = fs_start + (block_address * block_size)
    if block_offset < fs_start or block_offset + block_size > len(image):
        return []
    return [_u32(image, block_offset + offset) for offset in range(0, block_size, S5_INDIRECT_POINTER_SIZE)]


def read_ufs_file(image: bytes, fs_start: int, fs: dict[str, Any], inode: dict[str, int | list[int]]) -> bytes:
    direct_blocks = inode['direct_blocks']
    if not isinstance(direct_blocks, list):
        return b''
    size = int(inode['size'])
    block_size = int(fs['bsize'])
    data = bytearray()
    for fs_block in direct_blocks:
        if fs_block == 0:
            continue
        block_offset = fs_start + ufs_fsbtobytes(fs, fs_block)
        data.extend(image[block_offset:block_offset + block_size])
        if len(data) >= size:
            return bytes(data[:size])
    return bytes(data[:size])


def ufs_fsbtobytes(fs: dict[str, Any], fs_block: int) -> int:
    return (fs_block << int(fs['fsbtodb'])) * SECTOR_SIZE


def ufs_itoo(fs: dict[str, Any], inode_number: int) -> int:
    return inode_number % int(fs['inopb'])


def ufs_itog(fs: dict[str, Any], inode_number: int) -> int:
    return inode_number // int(fs['ipg'])


def ufs_blkstofrags(fs: dict[str, Any], blocks: int) -> int:
    return blocks << int(fs['fragshift'])


def ufs_cgbase(fs: dict[str, Any], cg: int) -> int:
    return int(fs['fpg']) * cg


def ufs_cgstart(fs: dict[str, Any], cg: int) -> int:
    return ufs_cgbase(fs, cg) + int(fs['cgoffset']) * (cg & ~int(fs['cgmask']))


def ufs_cgimin(fs: dict[str, Any], cg: int) -> int:
    return ufs_cgstart(fs, cg) + int(fs['iblkno'])


def ufs_itod(fs: dict[str, Any], inode_number: int) -> int:
    group = ufs_itog(fs, inode_number)
    return ufs_cgimin(fs, group) + ufs_blkstofrags(fs, ((inode_number % int(fs['ipg'])) // int(fs['inopb'])))


def resolve_s5_path(image: bytes, filesystem: FilesystemCandidate, path: str) -> tuple[int, dict[str, int | list[int]]] | None:
    block_size = filesystem.block_size
    if block_size is None:
        return None
    current_inode_number = S5_ROOT_INODE
    current_inode = read_s5_inode(image, filesystem.start_offset, block_size, current_inode_number)
    if current_inode is None:
        return None
    parts = [part for part in path.split('/') if part]
    if not parts:
        return current_inode_number, current_inode
    for part in parts:
        directory_bytes = read_s5_file(image, filesystem.start_offset, block_size, current_inode)
        next_inode_number = None
        for offset in range(0, min(len(directory_bytes), int(current_inode['size'])), S5_DIR_ENTRY_SIZE):
            inode_number = _u16(directory_bytes, offset)
            if inode_number == 0:
                continue
            name = directory_bytes[offset + 2:offset + 2 + S5_DIR_NAME_SIZE].split(b'\0', 1)[0].decode('ascii', errors='replace').strip()
            if name == part:
                next_inode_number = inode_number
                break
        if next_inode_number is None:
            return None
        current_inode_number = next_inode_number
        current_inode = read_s5_inode(image, filesystem.start_offset, block_size, current_inode_number)
        if current_inode is None:
            return None
    return current_inode_number, current_inode


def get_s5_filesystem(image_path: Path) -> tuple[bytes, FilesystemCandidate]:
    image = image_path.read_bytes()
    layout = detect_layout(image_path)
    filesystem = next((item for item in layout.filesystems if item.kind == 's5'), None)
    if filesystem is None or filesystem.block_size is None:
        raise SystemExit(f'error: no s5 filesystem found in {image_path}')
    return image, filesystem


def read_s5_path_bytes(image: bytes, filesystem: FilesystemCandidate, target_path: str) -> tuple[int, dict[str, int | list[int]], bytes]:
    if filesystem.block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    resolved = resolve_s5_path(image, filesystem, target_path)
    if resolved is None:
        raise SystemExit(f'error: could not resolve {target_path} inside the s5 filesystem')
    inode_number, inode = resolved
    return inode_number, inode, read_s5_file(image, filesystem.start_offset, filesystem.block_size, inode)
