from __future__ import annotations

from typing import Any

from .core import (
    FilesystemCandidate,
    S5_DINODE_SIZE,
    S5_DIRECT_BLOCKS,
    S5_FBLK_FREE_OFFSET,
    S5_FBLK_NFREE_OFFSET,
    S5_INDIRECT_POINTER_SIZE,
    S5_NICFREE,
    S5_SUPER_FMOD_OFFSET,
    S5_SUPER_FREE_OFFSET,
    S5_SUPER_NFREE_OFFSET,
    S5_SUPER_TIME_OFFSET,
    S5_SUPER_TFREE_OFFSET,
    _u16,
    _u32,
    read_s5_path_bytes,
    s5_indirect_capacity,
    s5_read_indirect_block,
)


def s5_blocks_for_size(size: int, block_size: int) -> int:
    if size <= 0:
        return 0
    return (size + block_size - 1) // block_size


def s5_inode_offset(fs_start: int, block_size: int, inode_number: int) -> int:
    inodes_per_block = block_size // S5_DINODE_SIZE
    block_number = (inode_number + (2 * inodes_per_block - 1)) // inodes_per_block
    inode_index = (inode_number + (2 * inodes_per_block - 1)) % inodes_per_block
    return fs_start + (block_number * block_size) + (inode_index * S5_DINODE_SIZE)


def read_s5_superblock(image: bytes, filesystem: FilesystemCandidate) -> dict[str, int | list[int]]:
    super_offset = filesystem.super_offset
    superblock = image[super_offset:super_offset + 512]
    return {
        'isize': _u16(superblock, 0),
        'fsize': _u32(superblock, 4),
        'nfree': _u16(superblock, S5_SUPER_NFREE_OFFSET),
        'free': [_u32(superblock, S5_SUPER_FREE_OFFSET + (index * 4)) for index in range(S5_NICFREE)],
        'tfree': _u32(superblock, S5_SUPER_TFREE_OFFSET),
    }


def write_s5_superblock(image: bytearray, filesystem: FilesystemCandidate, superblock: dict[str, int | list[int]]) -> None:
    nfree = int(superblock['nfree'])
    free_list = superblock['free']
    if not isinstance(free_list, list):
        raise SystemExit('error: s5 superblock free list is malformed')
    if nfree < 0 or nfree > S5_NICFREE:
        raise SystemExit(f'error: invalid s5 free count {nfree}')
    offset = filesystem.super_offset
    image[offset + S5_SUPER_NFREE_OFFSET:offset + S5_SUPER_NFREE_OFFSET + 2] = nfree.to_bytes(2, 'little', signed=False)
    image[offset + S5_SUPER_FMOD_OFFSET] = 1
    image[offset + S5_SUPER_TIME_OFFSET:offset + S5_SUPER_TIME_OFFSET + 4] = (0).to_bytes(4, 'little', signed=False)
    image[offset + S5_SUPER_TFREE_OFFSET:offset + S5_SUPER_TFREE_OFFSET + 4] = int(superblock['tfree']).to_bytes(4, 'little', signed=False)
    for index in range(S5_NICFREE):
        value = int(free_list[index]) if index < len(free_list) else 0
        entry_offset = offset + S5_SUPER_FREE_OFFSET + (index * 4)
        image[entry_offset:entry_offset + 4] = value.to_bytes(4, 'little', signed=False)


def s5_bad_block(superblock: dict[str, int | list[int]], block_number: int) -> bool:
    return block_number < int(superblock['isize']) or block_number >= int(superblock['fsize'])


def s5_read_free_block(image: bytes, filesystem: FilesystemCandidate, block_number: int) -> tuple[int, list[int]]:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    block_offset = filesystem.start_offset + (block_number * block_size)
    if block_offset < filesystem.start_offset or block_offset + block_size > len(image):
        raise SystemExit(f'error: s5 free-list block {block_number} is outside the image')
    nfree = _u32(image, block_offset + S5_FBLK_NFREE_OFFSET)
    if nfree > S5_NICFREE:
        raise SystemExit(f'error: s5 free-list block {block_number} has invalid count {nfree}')
    free_list = [_u32(image, block_offset + S5_FBLK_FREE_OFFSET + (index * 4)) for index in range(S5_NICFREE)]
    return nfree, free_list


def s5_zero_block(image: bytearray, filesystem: FilesystemCandidate, block_number: int) -> None:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    block_offset = filesystem.start_offset + (block_number * block_size)
    image[block_offset:block_offset + block_size] = b'\0' * block_size


def s5_alloc_block(image: bytearray, filesystem: FilesystemCandidate, superblock: dict[str, int | list[int]]) -> int:
    free_list = superblock['free']
    if not isinstance(free_list, list):
        raise SystemExit('error: s5 superblock free list is malformed')
    while True:
        nfree = int(superblock['nfree'])
        if nfree <= 0:
            raise SystemExit('error: no free s5 blocks remain in the image')
        block_number = int(free_list[nfree - 1])
        superblock['nfree'] = nfree - 1
        if block_number == 0:
            raise SystemExit('error: encountered end of s5 free list while allocating a block')
        if s5_bad_block(superblock, block_number):
            continue
        if int(superblock['nfree']) <= 0:
            next_nfree, next_free = s5_read_free_block(image, filesystem, block_number)
            superblock['nfree'] = next_nfree
            superblock['free'] = next_free
            free_list = next_free
        tfree = int(superblock['tfree'])
        if tfree > 0:
            superblock['tfree'] = tfree - 1
        return block_number


def s5_free_block(image: bytearray, filesystem: FilesystemCandidate, superblock: dict[str, int | list[int]], block_number: int) -> None:
    free_list = superblock['free']
    if not isinstance(free_list, list):
        raise SystemExit('error: s5 superblock free list is malformed')
    if block_number == 0 or s5_bad_block(superblock, block_number):
        return
    nfree = int(superblock['nfree'])
    if nfree <= 0:
        free_list[0] = 0
        nfree = 1
    if nfree >= S5_NICFREE:
        block_size = filesystem.block_size
        if block_size is None:
            raise SystemExit('error: s5 filesystem is missing a block size')
        block_offset = filesystem.start_offset + (block_number * block_size)
        image[block_offset:block_offset + block_size] = b'\0' * block_size
        image[block_offset:block_offset + 4] = nfree.to_bytes(4, 'little', signed=False)
        for index in range(S5_NICFREE):
            entry_offset = block_offset + S5_FBLK_FREE_OFFSET + (index * 4)
            image[entry_offset:entry_offset + 4] = int(free_list[index]).to_bytes(4, 'little', signed=False)
        nfree = 0
    free_list[nfree] = block_number
    superblock['nfree'] = nfree + 1
    superblock['tfree'] = int(superblock['tfree']) + 1


def s5_indirect_block_is_empty(image: bytes, filesystem: FilesystemCandidate, block_number: int) -> bool:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    return all(entry == 0 for entry in s5_read_indirect_block(image, filesystem.start_offset, block_size, block_number))


def s5_indirect_index_path(block_size: int, levels: int, relative_index: int) -> list[int]:
    entries_per_block = block_size // S5_INDIRECT_POINTER_SIZE
    indices: list[int] = []
    remainder = relative_index
    for depth in range(levels - 1, -1, -1):
        divisor = entries_per_block ** depth
        indices.append(remainder // divisor)
        remainder %= divisor
    return indices


def s5_read_indirect_entry(image: bytes, filesystem: FilesystemCandidate, block_number: int, entry_index: int) -> int:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    entries_per_block = block_size // S5_INDIRECT_POINTER_SIZE
    if entry_index < 0 or entry_index >= entries_per_block:
        raise SystemExit(f'error: s5 indirect entry index {entry_index} is out of range')
    block_offset = filesystem.start_offset + (block_number * block_size)
    entry_offset = block_offset + (entry_index * S5_INDIRECT_POINTER_SIZE)
    return _u32(image, entry_offset)


def s5_write_indirect_entry(image: bytearray, filesystem: FilesystemCandidate, block_number: int, entry_index: int, value: int) -> None:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    entries_per_block = block_size // S5_INDIRECT_POINTER_SIZE
    if entry_index < 0 or entry_index >= entries_per_block:
        raise SystemExit(f'error: s5 indirect entry index {entry_index} is out of range')
    block_offset = filesystem.start_offset + (block_number * block_size)
    entry_offset = block_offset + (entry_index * S5_INDIRECT_POINTER_SIZE)
    image[entry_offset:entry_offset + 4] = value.to_bytes(4, 'little', signed=False)


def s5_ensure_block_number_by_index(image: bytearray, filesystem: FilesystemCandidate, superblock: dict[str, int | list[int]], addresses: list[int], logical_index: int) -> tuple[int, int]:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    allocated_blocks = 0
    if logical_index < S5_DIRECT_BLOCKS:
        block_number = int(addresses[logical_index])
        if block_number == 0:
            block_number = s5_alloc_block(image, filesystem, superblock)
            s5_zero_block(image, filesystem, block_number)
            addresses[logical_index] = block_number
            allocated_blocks += 1
        return block_number, allocated_blocks
    relative_index = logical_index - S5_DIRECT_BLOCKS
    for levels in range(1, 4):
        capacity = s5_indirect_capacity(block_size, levels)
        if relative_index < capacity:
            root_index = S5_DIRECT_BLOCKS + levels - 1
            root_block = int(addresses[root_index])
            if root_block == 0:
                root_block = s5_alloc_block(image, filesystem, superblock)
                s5_zero_block(image, filesystem, root_block)
                addresses[root_index] = root_block
                allocated_blocks += 1
            current = root_block
            path = s5_indirect_index_path(block_size, levels, relative_index)
            for entry_index in path[:-1]:
                next_block = s5_read_indirect_entry(image, filesystem, current, entry_index)
                if next_block == 0:
                    next_block = s5_alloc_block(image, filesystem, superblock)
                    s5_zero_block(image, filesystem, next_block)
                    s5_write_indirect_entry(image, filesystem, current, entry_index, next_block)
                    allocated_blocks += 1
                current = next_block
            data_index = path[-1]
            data_block = s5_read_indirect_entry(image, filesystem, current, data_index)
            if data_block == 0:
                data_block = s5_alloc_block(image, filesystem, superblock)
                s5_zero_block(image, filesystem, data_block)
                s5_write_indirect_entry(image, filesystem, current, data_index, data_block)
                allocated_blocks += 1
            return data_block, allocated_blocks
        relative_index -= capacity
    raise SystemExit(f'error: s5 logical block index {logical_index} is too large for a 13-address inode')


def s5_release_logical_block(image: bytearray, filesystem: FilesystemCandidate, superblock: dict[str, int | list[int]], addresses: list[int], logical_index: int) -> int:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    freed_blocks = 0
    if logical_index < S5_DIRECT_BLOCKS:
        block_number = int(addresses[logical_index])
        if block_number != 0:
            addresses[logical_index] = 0
            s5_free_block(image, filesystem, superblock, block_number)
            freed_blocks += 1
        return freed_blocks
    relative_index = logical_index - S5_DIRECT_BLOCKS
    for levels in range(1, 4):
        capacity = s5_indirect_capacity(block_size, levels)
        if relative_index < capacity:
            root_index = S5_DIRECT_BLOCKS + levels - 1
            root_block = int(addresses[root_index])
            if root_block == 0:
                return freed_blocks
            path = s5_indirect_index_path(block_size, levels, relative_index)
            current = root_block
            parents: list[tuple[int | None, int | None, int]] = [(None, None, root_block)]
            for entry_index in path[:-1]:
                next_block = s5_read_indirect_entry(image, filesystem, current, entry_index)
                if next_block == 0:
                    return freed_blocks
                parents.append((current, entry_index, next_block))
                current = next_block
            data_index = path[-1]
            data_block = s5_read_indirect_entry(image, filesystem, current, data_index)
            if data_block == 0:
                return freed_blocks
            s5_write_indirect_entry(image, filesystem, current, data_index, 0)
            s5_free_block(image, filesystem, superblock, data_block)
            freed_blocks += 1
            for parent_block, parent_entry, child_block in reversed(parents):
                if not s5_indirect_block_is_empty(image, filesystem, child_block):
                    break
                if parent_block is None or parent_entry is None:
                    addresses[root_index] = 0
                else:
                    s5_write_indirect_entry(image, filesystem, parent_block, parent_entry, 0)
                s5_free_block(image, filesystem, superblock, child_block)
                freed_blocks += 1
            return freed_blocks
        relative_index -= capacity
    raise SystemExit(f'error: s5 logical block index {logical_index} is too large for a 13-address inode')


def write_s5_inode(image: bytearray, filesystem: FilesystemCandidate, inode_number: int, size: int, addresses: list[int]) -> None:
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    inode_offset = s5_inode_offset(filesystem.start_offset, block_size, inode_number)
    image[inode_offset + 8:inode_offset + 12] = size.to_bytes(4, 'little', signed=False)
    for index, address in enumerate(addresses[:13]):
        start = inode_offset + 12 + (index * 3)
        image[start:start + 3] = int(address).to_bytes(4, 'little', signed=False)[:3]


def apply_s5_replacement(image: bytearray, filesystem: FilesystemCandidate, target_path: str, new_data: bytes) -> dict[str, int | str]:
    inode_number, inode, _ = read_s5_path_bytes(image, filesystem, target_path)
    addresses = inode['addresses']
    if not isinstance(addresses, list):
        raise SystemExit(f'error: inode {inode_number} has no address list')
    mutable_addresses = [int(address) for address in addresses]
    block_size = filesystem.block_size
    if block_size is None:
        raise SystemExit('error: s5 filesystem is missing a block size')
    old_size = int(inode['size'])
    old_blocks = s5_blocks_for_size(old_size, block_size)
    new_blocks = s5_blocks_for_size(len(new_data), block_size)
    superblock = read_s5_superblock(image, filesystem)
    allocated_blocks = 0
    freed_blocks = 0
    for block_index in range(new_blocks):
        block_number, newly_allocated = s5_ensure_block_number_by_index(image, filesystem, superblock, mutable_addresses, block_index)
        allocated_blocks += newly_allocated
        chunk = new_data[block_index * block_size:(block_index + 1) * block_size]
        block_offset = filesystem.start_offset + (block_number * block_size)
        image[block_offset:block_offset + block_size] = chunk.ljust(block_size, b'\0')
    for block_index in range(old_blocks - 1, new_blocks - 1, -1):
        freed_blocks += s5_release_logical_block(image, filesystem, superblock, mutable_addresses, block_index)
    write_s5_inode(image, filesystem, inode_number, len(new_data), mutable_addresses)
    write_s5_superblock(image, filesystem, superblock)
    return {
        'target_path': target_path,
        'inode': inode_number,
        'old_size': old_size,
        'new_size': len(new_data),
        'old_blocks': old_blocks,
        'new_blocks': new_blocks,
        'allocated_blocks': allocated_blocks,
        'freed_blocks': freed_blocks,
    }
