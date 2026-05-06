from __future__ import annotations

import difflib
import json
from dataclasses import asdict
from pathlib import Path

from .core import ImageLayout, detect_layout, get_s5_filesystem, read_s5_path_bytes
from .s5 import apply_s5_replacement


def decode_text_payload(data: bytes) -> str | None:
    for encoding in ('utf-8', 'ascii'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def first_mismatch_offset(left: bytes, right: bytes) -> int | None:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    if len(left) != len(right):
        return limit
    return None


def format_byte(value: int | None) -> str:
    if value is None:
        return 'EOF'
    return f'0x{value:02x}'


def print_replacement_summary(prefix: str, result: dict[str, int | str]) -> None:
    print(
        f'{prefix} {result["target_path"]}: '
        f'size {result["old_size"]} -> {result["new_size"]} bytes, '
        f'blocks {result["old_blocks"]} -> {result["new_blocks"]}, '
        f'allocated {result["allocated_blocks"]}, '
        f'freed {result["freed_blocks"]}'
    )


def extract_s5_file(image_path: Path, target_path: str, output_path: Path) -> None:
    image, filesystem = get_s5_filesystem(image_path)
    _, _, file_bytes = read_s5_path_bytes(image, filesystem, target_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(file_bytes)
    print(f'Extracted {target_path} from {image_path} to {output_path}')


def diff_s5_file(image_path: Path, target_path: str, source_path: Path) -> bool:
    image, filesystem = get_s5_filesystem(image_path)
    _, _, image_bytes = read_s5_path_bytes(image, filesystem, target_path)
    source_bytes = source_path.read_bytes()
    if image_bytes == source_bytes:
        print(f'{target_path} in {image_path} matches {source_path}')
        return True
    image_text = decode_text_payload(image_bytes)
    source_text = decode_text_payload(source_bytes)
    if image_text is not None and source_text is not None:
        diff_lines = list(
            difflib.unified_diff(
                source_text.splitlines(),
                image_text.splitlines(),
                fromfile=str(source_path),
                tofile=f'{image_path}:{target_path}',
                lineterm='',
            )
        )
        if diff_lines:
            print('\n'.join(diff_lines))
    else:
        mismatch = first_mismatch_offset(source_bytes, image_bytes)
        print(f'{target_path} in {image_path} differs from {source_path}')
        print(f'Source size: {len(source_bytes)} bytes')
        print(f'Image size: {len(image_bytes)} bytes')
        if mismatch is not None:
            source_byte = source_bytes[mismatch] if mismatch < len(source_bytes) else None
            image_byte = image_bytes[mismatch] if mismatch < len(image_bytes) else None
            print(f'First mismatch at byte {mismatch}: source={format_byte(source_byte)} image={format_byte(image_byte)}')
    return False


def replace_s5_file(image_path: Path, target_path: str, source_path: Path, output_path: Path | None) -> None:
    image_bytes, filesystem = get_s5_filesystem(image_path)
    image = bytearray(image_bytes)
    result = apply_s5_replacement(image, filesystem, target_path, source_path.read_bytes())
    destination = output_path or image_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    print(f'Replaced {target_path} in {destination} using {source_path}')
    print_replacement_summary('Updated', result)


def _layout_to_json(layout: ImageLayout) -> str:
    return f'{json.dumps(asdict(layout), indent=2)}\n'


def print_layout(layout: ImageLayout, report_json: Path | None) -> None:
    print(f'Image: {layout.image_path}')
    print(f'Size: {layout.image_size} bytes')
    print(f'Detected boot region: {layout.boot_region_size} bytes')
    for filesystem in layout.filesystems:
        print(f'- {filesystem.kind} start={filesystem.start_offset} super={filesystem.super_offset} block_size={filesystem.block_size}')
        if filesystem.root_entries:
            print(f'  {filesystem.kind} root entries:')
            for entry in filesystem.root_entries:
                size_suffix = f' size={entry["size"]}' if 'size' in entry else ''
                print(f'    {entry["name"]} inode={entry["inode"]}{size_suffix}')
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(_layout_to_json(layout), encoding='utf-8')
        print(f'Wrote report to {report_json}')


def load_replacement_set(manifest_path: Path, set_name: str) -> list[tuple[str, Path]]:
    payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise SystemExit(f'error: replacement manifest {manifest_path} must contain a top-level object')
    raw_sets = payload.get('sets')
    if not isinstance(raw_sets, dict):
        raise SystemExit(f'error: replacement manifest {manifest_path} is missing an object-valued "sets" field')
    raw_entries = raw_sets.get(set_name)
    if raw_entries is None:
        raise SystemExit(f'error: replacement manifest {manifest_path} does not define set {set_name!r}')
    if not isinstance(raw_entries, list):
        raise SystemExit(f'error: replacement set {set_name!r} in {manifest_path} must be a list')
    replacements: list[tuple[str, Path]] = []
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f'error: replacement set {set_name!r} entry {index} in {manifest_path} must be an object')
        target = entry.get('target') or entry.get('target_path')
        source = entry.get('source')
        if not isinstance(target, str) or not target:
            raise SystemExit(f'error: replacement set {set_name!r} entry {index} in {manifest_path} is missing a target')
        if not isinstance(source, str) or not source:
            raise SystemExit(f'error: replacement set {set_name!r} entry {index} in {manifest_path} is missing a source')
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = (manifest_path.parent / source_path).resolve()
        if not source_path.exists():
            raise SystemExit(f'error: replacement set {set_name!r} entry {index} in {manifest_path} refers to missing source {source_path}')
        replacements.append((target, source_path))
    return replacements


def validate_replacements(image_path: Path, replacements: list[tuple[str, Path]], label: str = 'Validated') -> list[dict[str, int | str]]:
    image_bytes, filesystem = get_s5_filesystem(image_path)
    image = bytearray(image_bytes)
    results: list[dict[str, int | str]] = []
    for target_path, source_path in replacements:
        result = apply_s5_replacement(image, filesystem, target_path, source_path.read_bytes())
        result['source_path'] = str(source_path)
        results.append(result)
        print_replacement_summary(label, result)
    return results


def build_hybrid_image(reference_image: Path, bootloader_image: Path, output_image: Path, report_json: Path | None, replacements: list[tuple[str, Path]]) -> None:
    layout = detect_layout(reference_image)
    bootloader = bootloader_image.read_bytes()
    if len(bootloader) > layout.boot_region_size:
        raise SystemExit('error: built bootloader is larger than detected boot region ' f'({len(bootloader)} > {layout.boot_region_size})')
    if replacements:
        validate_replacements(reference_image, replacements, label='Preflight')
    hybrid = bytearray(reference_image.read_bytes())
    hybrid[:len(bootloader)] = bootloader
    output_image.parent.mkdir(parents=True, exist_ok=True)
    output_image.write_bytes(hybrid)
    for target_path, replacement_path in replacements:
        replace_s5_file(output_image, target_path, replacement_path, output_image)
    result = detect_layout(output_image)
    if result.boot_region_size != layout.boot_region_size:
        raise SystemExit('error: hybrid image layout no longer matches the reference boot boundary')
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(_layout_to_json(result), encoding='utf-8')
    print(f'Wrote hybrid floppy image to {output_image}')
    print(f'Boot region: {layout.boot_region_size} bytes')
    print(f'Bootloader bytes written: {len(bootloader)}')
