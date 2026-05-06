#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path


_SCRIPT_ROOT = Path(__file__).resolve().parent
if (_SCRIPT_ROOT.parent / 'i386').exists() and (_SCRIPT_ROOT.parent / 'build-specs').exists():
    WORKSPACE_ROOT = _SCRIPT_ROOT.parent.parent
else:
    WORKSPACE_ROOT = _SCRIPT_ROOT.parent


@dataclass(frozen=True)
class DeviceSpec:
    name: str
    mask: str
    type_flags: str
    handler: str
    block_major_start: int | None
    block_major_end: int | None
    char_major_start: int | None
    char_major_end: int | None
    minimum_units: int
    maximum_units: int
    channel: int


@dataclass(frozen=True)
class ControllerSpec:
    name: str
    configured: bool
    units: int
    ipl: int
    interrupt_type: int
    vector: int
    sioa: int
    eioa: int
    scma: int
    ecma: int


@dataclass(frozen=True)
class FileSystemSpec:
    name: str
    prefix: str
    configured: bool


@dataclass(frozen=True)
class SystemAssignment:
    name: str
    device: str
    minor: int
    pathname: str | None


PACKAGE_SOURCE_RULES: dict[str, list[dict[str, object]]] = {
    "RFS": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["rfs/*.c"]}],
    "app": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["app.c"]}],
    "arp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["arp.c"]}],
    "bfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["bfs/*.c"]}],
    "coff": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["coff/coff.c"]}],
    "cmux": [{"source_root": "uts/arch/at/i386/io", "output_root": "io/core", "patterns": ["chanmux.c"]}],
    "des": [{"source_root": "uts/i386/des", "output_root": "des", "patterns": ["*.c"]}],
    "dosx": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["dosx/dosx.c"]}],
    "elf": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["elf/elf.c"]}],
    "fdfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["fdfs/*.c"]}],
    "fifofs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["fifofs/*.c"]}],
    "gdebugger": [{"source_root": "uts/i386/kdb/gdebugger", "output_root": "kdb/gdebugger", "patterns": ["*.c"]}],
    "gvid": [{"source_root": "uts/arch/at/i386/io", "output_root": "io/core", "patterns": ["genvid.c"]}],
    "hrt": [{"source_root": "uts/i386/io", "output_root": "io/core", "patterns": ["hrtimers.c"]}],
    "i286x": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["i286x/i286x.c"]}],
    "icmp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["ip_icmp.c"]}],
    "intp": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["intp/intp.c"]}],
    "ip": [{
        "source_root": "uts/i386/netinet",
        "output_root": "netinet",
        "patterns": [
            "in.c",
            "in_cksum.c",
            "in_pcb.c",
            "in_switch.c",
            "in_transp.c",
            "ip_input.c",
            "ip_main.c",
            "ip_output.c",
            "ip_vers.c",
            "netlib.c",
            "route.c",
        ],
    }],
    "kdb": [{"source_root": "uts/i386/kdb/kdb", "output_root": "kdb/core", "patterns": ["*.c"]}],
    "kdb-util": [{"source_root": "uts/i386/kdb/kdb-util", "output_root": "kdb/kdb-util", "patterns": ["*.c"]}],
    "kd": [{"source_root": "uts/arch/at/i386/io/kd", "output_root": "io/kd", "patterns": ["*.c"]}],
    "kdvm": [{"source_root": "uts/arch/at/i386/io/kdvm", "output_root": "io/kdvm", "patterns": ["*.c"]}],
    "klm": [{"source_root": "uts/i386/klm", "output_root": "klm", "patterns": ["*.c"]}],
    "krpc": [{"source_root": "uts/i386/rpc", "output_root": "rpc", "patterns": ["*.c"]}],
    "ktli": [{"source_root": "uts/i386/ktli", "output_root": "ktli", "patterns": ["*.c"]}],
    "llcloop": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["llcloop.c"]}],
    "namefs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["namefs/*.c"]}],
    "nfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["nfs/*.c"]}],
    "pic": [{"source_root": "uts/i386/ml", "output_root": "ml", "patterns": ["pic.c"]}],
    "proc": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["proc/*.c"]}],
    "rawip": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["raw_ip.c", "raw_ip_cb.c", "raw_ip_main.c"]}],
    "rt": [{"source_root": "uts/i386/disp", "output_root": "disp", "patterns": ["rt.c"]}],
    "s5": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["s5/*.c"]}],
    "specfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["specfs/*.c"]}],
    "tcp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["tcp_*.c"]}],
    "ticotsor": [{"source_root": "uts/i386/io", "output_root": "io/core", "patterns": ["ticotsord.c"]}],
    "ts": [{"source_root": "uts/i386/disp", "output_root": "disp", "patterns": ["ts.c"]}],
    "udp": [{"source_root": "uts/i386/netinet", "output_root": "netinet", "patterns": ["udp_*.c"]}],
    "ufs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["ufs/*.c"]}],
    "vx": [{"source_root": "uts/i386/vx", "output_root": "vx", "patterns": ["*.c"]}],
    "ws": [{"source_root": "uts/i386/io/ws", "output_root": "io/ws", "patterns": ["*.c"]}],
    "xnamfs": [{"source_root": "uts/i386/fs", "output_root": "fs", "patterns": ["xnamfs/*.c"]}],
    "xout": [{"source_root": "uts/i386/exec", "output_root": "exec", "patterns": ["xout/xout.c"]}],
}

SINGLE_SOURCE_FALLBACKS: list[tuple[str, str]] = [
    ("uts/arch/at/i386/io", "io/core"),
    ("uts/i386/io", "io/core"),
    ("uts/i386/os", "os"),
    ("uts/i386/ml", "ml"),
    ("uts/i386/vx", "vx"),
    ("uts/i386/des", "des"),
    ("uts/i386/ktli", "ktli"),
    ("uts/i386/klm", "klm"),
    ("uts/i386/netinet", "netinet"),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a minimal modern replacement for the parts of idconfig needed by the prototype kernel build.")
    parser.add_argument("--conf-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--obj-root", required=True)
    parser.add_argument("--enable-module", action="append", default=[])
    parser.add_argument("--exclude-module", action="append", default=[])
    return parser.parse_args()


def _normalize_module_name(name: str) -> str:
    return name.strip().lower()


def _iter_metadata_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines: list[str] = []
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("*"):
            continue
        lines.append(stripped)
    return lines


def _parse_major_range(token: str) -> tuple[int | None, int | None]:
    if token == "-":
        return None, None
    if "-" in token:
        start_text, end_text = token.split("-", 1)
        return _parse_number(start_text), _parse_number(end_text)
    value = _parse_number(token)
    return value, value


def _parse_number(token: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        return int(token, 16)


def _parse_address(token: str) -> int:
    if token == "0":
        return 0
    return int(token, 16)


def _parse_mdevice(path: Path) -> list[DeviceSpec]:
    devices: list[DeviceSpec] = []
    for line in _iter_metadata_lines(path):
        parts = line.split()
        if len(parts) != 9:
            continue
        block_major_start, block_major_end = _parse_major_range(parts[4])
        char_major_start, char_major_end = _parse_major_range(parts[5])
        devices.append(
            DeviceSpec(
                name=parts[0],
                mask=parts[1],
                type_flags=parts[2],
                handler=parts[3],
                block_major_start=block_major_start,
                block_major_end=block_major_end,
                char_major_start=char_major_start,
                char_major_end=char_major_end,
                minimum_units=_parse_number(parts[6]),
                maximum_units=_parse_number(parts[7]),
                channel=_parse_number(parts[8]),
            )
        )
    return devices


def _parse_sdevice_dir(path: Path) -> list[ControllerSpec]:
    controllers: list[ControllerSpec] = []
    if not path.exists():
        return controllers
    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        for line in _iter_metadata_lines(entry):
            parts = line.split()
            if len(parts) != 10:
                continue
            controllers.append(
                ControllerSpec(
                    name=parts[0],
                    configured=parts[1].upper() == "Y",
                    units=_parse_number(parts[2]),
                    ipl=_parse_number(parts[3]),
                    interrupt_type=_parse_number(parts[4]),
                    vector=_parse_number(parts[5]),
                    sioa=_parse_address(parts[6]),
                    eioa=_parse_address(parts[7]),
                    scma=_parse_address(parts[8]),
                    ecma=_parse_address(parts[9]),
                )
            )
    return controllers


def _parse_mtune(path: Path) -> dict[str, int]:
    tunables: dict[str, int] = {}
    for line in _iter_metadata_lines(path):
        parts = line.split()
        if len(parts) < 2:
            continue
        tunables[parts[0]] = _parse_number(parts[1])
    return tunables


def _parse_stune(path: Path) -> dict[str, int]:
    overrides: dict[str, int] = {}
    for line in _iter_metadata_lines(path):
        parts = line.split()
        if len(parts) != 2:
            continue
        overrides[parts[0]] = _parse_number(parts[1])
    return overrides


def _parse_mfsys_dir(path: Path) -> list[FileSystemSpec]:
    filesystems: list[FileSystemSpec] = []
    if not path.exists():
        return filesystems
    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        lines = _iter_metadata_lines(entry)
        if not lines:
            continue
        parts = lines[0].split()
        if len(parts) != 2:
            continue
        filesystems.append(FileSystemSpec(name=parts[0], prefix=parts[1], configured=False))
    return filesystems


def _parse_sfsys_dir(path: Path) -> dict[str, bool]:
    configured: dict[str, bool] = {}
    if not path.exists():
        return configured
    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        for line in _iter_metadata_lines(entry):
            parts = line.split()
            if len(parts) != 2:
                continue
            configured[parts[0]] = parts[1].upper() == "Y"
    return configured


def _parse_sassign(path: Path) -> dict[str, SystemAssignment]:
    assignments: dict[str, SystemAssignment] = {}
    for line in _iter_metadata_lines(path):
        parts = line.split()
        if len(parts) < 3:
            continue
        assignments[parts[0]] = SystemAssignment(
            name=parts[0],
            device=parts[1],
            minor=_parse_number(parts[2]),
            pathname=parts[3] if len(parts) > 3 else None,
        )
    return assignments


def _uppermap(text: str) -> str:
    return "".join(character.upper() if "a" <= character <= "z" else character for character in text)


def _has_mask(device: DeviceSpec, flag: str) -> bool:
    return flag in device.mask


def _has_type(device: DeviceSpec, flag: str) -> bool:
    return flag in device.type_flags


def _controller_groups(controllers: list[ControllerSpec]) -> dict[str, list[ControllerSpec]]:
    groups: dict[str, list[ControllerSpec]] = {}
    for controller in controllers:
        groups.setdefault(controller.name, []).append(controller)
    return groups


def _configured_names(controllers: list[ControllerSpec], filesystems: list[FileSystemSpec]) -> set[str]:
    names = {controller.name for controller in controllers if controller.configured}
    names.update(filesystem.name for filesystem in filesystems if filesystem.configured)
    return names


def _interrupt_entries(devices: list[DeviceSpec], controllers: list[ControllerSpec]) -> dict[int, list[tuple[DeviceSpec, ControllerSpec]]]:
    devices_by_name = {device.name: device for device in devices}
    entries: dict[int, list[tuple[DeviceSpec, ControllerSpec]]] = {}
    for controller in controllers:
        if not controller.configured or controller.interrupt_type == 0:
            continue
        device = devices_by_name.get(controller.name)
        if device is None or _has_type(device, "G"):
            continue
        vector_entries = entries.setdefault(controller.vector, [])
        if any(existing_device.handler == device.handler for existing_device, _ in vector_entries):
            continue
        vector_entries.append((device, controller))
    return entries


def _write_config_header(output_path: Path, devices: list[DeviceSpec], controllers: list[ControllerSpec], tunables: dict[str, int]) -> None:
    controller_groups = _controller_groups(controllers)
    configured_names = {controller.name for controller in controllers if controller.configured}

    lines: list[str] = []
    lines.append("/* generated by uts_idconfig.py */")
    lines.append("/* defines for each device */")
    for device in devices:
        if device.name not in configured_names:
            continue
        symbol = _uppermap(device.handler)
        grouped = [controller for controller in controller_groups.get(device.name, []) if controller.configured]
        total_units = sum(controller.units for controller in grouped)
        inttype = grouped[-1].interrupt_type if grouped else 0
        lines.append("")
        lines.append(f"#define\t{symbol}\t\t1")
        lines.append(f"#define\t{symbol}_CNTLS\t{len(grouped)}")
        lines.append(f"#define\t{symbol}_UNITS\t{total_units}")
        lines.append(f"#define\t{symbol}_CHAN\t{device.channel}")
        lines.append(f"#define\t{symbol}_TYPE\t{inttype}")
        if "b" in device.type_flags and device.block_major_start is not None and device.block_major_end is not None:
            count = device.block_major_end - device.block_major_start + 1
            lines.append(f"#define\t{symbol}_BMAJORS\t{count}")
            for index in range(count):
                lines.append(f"#define\t{symbol}_BMAJOR_{index}\t{device.block_major_start + index}")
        if "c" in device.type_flags and device.char_major_start is not None and device.char_major_end is not None:
            count = device.char_major_end - device.char_major_start + 1
            lines.append(f"#define\t{symbol}_CMAJORS\t{count}")
            for index in range(count):
                lines.append(f"#define\t{symbol}_CMAJOR_{index}\t{device.char_major_start + index}")

    lines.append("")
    lines.append("")
    lines.append("/* defines for each controller */")
    for device in devices:
        symbol = _uppermap(device.handler)
        grouped = [controller for controller in controller_groups.get(device.name, []) if controller.configured]
        for index, controller in enumerate(grouped):
            lines.append("")
            lines.append(f"#define\t{symbol}_{index}\t\t{controller.units}")
            lines.append(f"#define\t{symbol}_{index}_VECT\t{controller.vector}")
            lines.append(f"#define\t{symbol}_{index}_SIOA\t{controller.sioa}")
            lines.append(f"#define\t{symbol}_{index}_EIOA\t{controller.eioa}")
            lines.append(f"#define\t{symbol}_{index}_SCMA\t{controller.scma}")
            lines.append(f"#define\t{symbol}_{index}_ECMA\t{controller.ecma}")

    lines.append("")
    lines.append("/* defines for each tunable parameter */")
    for name, value in sorted(tunables.items()):
        lines.append(f"#define\t{name}\t{value}")

    output_path.write_text("\n".join(lines) + "\n")


def _device_major_end(devices: list[DeviceSpec], flag: str) -> int:
    high = -1
    for device in devices:
        if flag == "b" and "b" in device.type_flags and device.block_major_end is not None:
            high = max(high, device.block_major_end)
        if flag == "c" and "c" in device.type_flags and device.char_major_end is not None:
            high = max(high, device.char_major_end)
    return high


def _build_major_table(devices: list[DeviceSpec], flag: str) -> list[DeviceSpec | None]:
    high = _device_major_end(devices, flag)
    if high < 0:
        return []
    table: list[DeviceSpec | None] = [None] * (high + 1)
    for device in devices:
        if flag not in device.type_flags:
            continue
        if flag == "b":
            start = device.block_major_start
            end = device.block_major_end
        else:
            start = device.char_major_start
            end = device.char_major_end
        if start is None or end is None:
            continue
        for index in range(start, end + 1):
            table[index] = device
    return table


def _append_extern(lines: list[str], text: str) -> None:
    if text not in lines:
        lines.append(text)


def _emit_major_dev(lines: list[str], assignment: SystemAssignment | None, devices_by_name: dict[str, DeviceSpec], symbol_name: str, require_block: bool, dump_handler: list[str]) -> None:
    if assignment is None:
        lines.append(f"dev_t\t{symbol_name} = makedevice(0, 0);")
        return
    device = devices_by_name.get(assignment.device)
    if device is None:
        lines.append(f"dev_t\t{symbol_name} = makedevice(0, 0);")
        return
    major = device.block_major_start if require_block else device.char_major_start
    if major is None:
        lines.append(f"dev_t\t{symbol_name} = makedevice(0, 0);")
        return
    lines.append(f"dev_t\t{symbol_name} = makedevice({major}, {assignment.minor});")
    if symbol_name == "dumpdev":
        dump_handler.append(device.handler)


def _device_externs(device: DeviceSpec) -> list[str]:
    externs: list[str] = []
    declarations: list[str] = []
    if _has_type(device, "f"):
        externs.append(f"extern int {device.handler}devflag;")
    if _has_mask(device, "o"):
        declarations.append(f"{device.handler}open()")
    if _has_mask(device, "c"):
        declarations.append(f"{device.handler}close()")
    if _has_mask(device, "r"):
        declarations.append(f"{device.handler}read()")
    if _has_mask(device, "w"):
        declarations.append(f"{device.handler}write()")
    if _has_mask(device, "i"):
        declarations.append(f"{device.handler}ioctl()")
    if _has_type(device, "b"):
        declarations.append(f"{device.handler}strategy()")
        declarations.append(f"{device.handler}print()")
        if _has_type(device, "f") and _has_mask(device, "z"):
            declarations.append(f"{device.handler}size()")
    if _has_mask(device, "f"):
        declarations.append(f"{device.handler}fork()")
    if _has_mask(device, "e"):
        declarations.append(f"{device.handler}exec()")
    if _has_mask(device, "x"):
        declarations.append(f"{device.handler}exit()")
    if _has_type(device, "R"):
        declarations.append(f"{device.handler}reset()")
    if _has_mask(device, "I"):
        declarations.append(f"{device.handler}init()")
    if _has_mask(device, "s"):
        declarations.append(f"{device.handler}start()")
    if _has_mask(device, "L"):
        declarations.append(f"{device.handler}chpoll()")
    if _has_mask(device, "p"):
        declarations.append(f"{device.handler}poll()")
    if _has_mask(device, "h"):
        declarations.append(f"{device.handler}halt()")
    if _has_mask(device, "E"):
        declarations.append(f"{device.handler}kenter()")
    if _has_mask(device, "X"):
        declarations.append(f"{device.handler}kexit()")
    if _has_mask(device, "M"):
        declarations.append(f"{device.handler}mmap()")
    if _has_mask(device, "S"):
        declarations.append(f"{device.handler}segmap()")
    if declarations:
        externs.append("extern int " + ", ".join(declarations) + ";")
    if _has_type(device, "t"):
        externs.append(f"extern struct tty {device.handler}_tty[];")
    if _has_type(device, "S"):
        externs.append(f"extern struct streamtab {device.handler}info;")
    if _has_type(device, "e"):
        externs.append(f"extern short {device.handler}magic[{max(device.maximum_units, 1)}];")
        externs.append(f"extern int {device.handler}exec();")
        externs.append(f"extern int {device.handler}core();")
    return externs


def _bdev_entry(device: DeviceSpec | None) -> str:
    if device is None:
        return 'nodev,\tnodev,\tnodev,\tnodev,\tnulldev,\tnodev,\tnodev,\t"nodev",\t0,\t&nodevflag'

    fields = [
        f"{device.handler}open" if _has_mask(device, "o") else "nodev",
        f"{device.handler}close" if _has_mask(device, "c") else "nodev",
        f"{device.handler}strategy",
        f"{device.handler}print",
    ]
    if _has_type(device, "f") and _has_mask(device, "z"):
        fields.append(f"{device.handler}size")
    else:
        fields.append("nulldev")
    fields.append(f"{device.handler}poll" if _has_mask(device, "p") else "nodev")
    fields.append(f"{device.handler}halt" if _has_mask(device, "h") else "nodev")
    fields.append(f'"{device.name}"')
    fields.append("(struct iobuf *)0")
    fields.append(f"&{device.handler}devflag" if _has_type(device, "f") else "&nodevflag")
    return ",\t".join(fields)


def _cdev_entry(device: DeviceSpec | None) -> str:
    if device is None:
        return '\tnodev, \tnodev, \tnodev, \tnodev, \tnodev, \tnodev, \tnodev, \tnodev, \tnodev, \tnodev, \t0,\t0,\t"nodev",\t&nodevflag,'

    fields = [
        f"{device.handler}open" if _has_mask(device, "o") else "nulldev",
        f"{device.handler}close" if _has_mask(device, "c") else "nulldev",
        f"{device.handler}read" if _has_mask(device, "r") else "nodev",
        f"{device.handler}write" if _has_mask(device, "w") else "nodev",
        f"{device.handler}ioctl" if _has_mask(device, "i") else "nodev",
        f"{device.handler}mmap" if _has_mask(device, "M") else "nodev",
        f"{device.handler}segmap" if _has_mask(device, "S") else "nodev",
        f"{device.handler}chpoll" if _has_mask(device, "L") else "nodev",
        f"{device.handler}poll" if _has_mask(device, "p") else "nodev",
        f"{device.handler}halt" if _has_mask(device, "h") else "nodev",
        f"{device.handler}_tty" if _has_type(device, "t") else "0",
        f"&{device.handler}info" if _has_type(device, "S") else "0",
        f'"{device.name}"',
        f"&{device.handler}devflag" if _has_type(device, "f") else "&nodevflag",
    ]
    return "\t" + ",\t".join(fields) + ","


def _write_conf_c(
    output_path: Path,
    devices: list[DeviceSpec],
    controllers: list[ControllerSpec],
    filesystems: list[FileSystemSpec],
    assignments: dict[str, SystemAssignment],
) -> None:
    controller_groups = _controller_groups(controllers)
    configured_names = _configured_names(controllers, filesystems)
    configured_devices = [device for device in devices if device.name in configured_names]
    devices_by_name = {device.name: device for device in devices}
    bdevices = _build_major_table(configured_devices, "b")
    cdevices = _build_major_table(configured_devices, "c")

    lines: list[str] = [
        "/* generated by uts_idconfig.py */",
        '#include\t"config.h"',
        '#include\t"sys/param.h"',
        '#include\t"sys/types.h"',
        '#include\t"sys/sysmacros.h"',
        '#include\t"sys/conf.h"',
        '#include\t"sys/stream.h"',
        '#include\t"sys/class.h"',
        '#include\t"sys/vnode.h"',
        '#include\t"sys/exec.h"',
        '#include\t"vm/bootconf.h"',
        "",
        "extern int nodev(), nulldev(), nuldevreset();",
        "extern int nodevflag;",
    ]

    for device in configured_devices:
        for extern_decl in _device_externs(device):
            _append_extern(lines, extern_decl)

    lines.append("")
    lines.append("struct bdevsw bdevsw[] = {")
    for index, device in enumerate(bdevices):
        trailer = "," if index + 1 < len(bdevices) else ""
        lines.append(f"/*{index:2d}*/\t{_bdev_entry(device)}{trailer}")
    lines.append("};")
    lines.append("")
    lines.append("struct cdevsw cdevsw[] = {")
    for index, device in enumerate(cdevices):
        lines.append(f"/*{index:2d}*/{_cdev_entry(device)}")
    lines.append("};")
    lines.append("")

    fmod_entries: list[str] = []
    for device in configured_devices:
        if not _has_type(device, "S"):
            continue
        is_driver = _has_type(device, "c")
        is_module = _has_type(device, "m") or not is_driver
        if not is_module:
            continue
        fmod_entries.append(
            f'\t"{device.name}", &{device.handler}info, ' + (f"&{device.handler}devflag" if _has_type(device, "f") else "&nodevflag")
        )
    lines.append("struct fmodsw fmodsw[] = {")
    if fmod_entries:
        for index, entry in enumerate(fmod_entries):
            trailer = "," if index + 1 < len(fmod_entries) else ""
            lines.append(f"{entry}{trailer}")
    else:
        lines.append('\t"", (struct streamtab *)0, &nodevflag')
    lines.append("};")
    lines.append(f"int fmodcnt = {len(fmod_entries)};")
    lines.append(f"int\tbdevcnt = {len(bdevices)};")
    lines.append(f"int\tcdevcnt = {len(cdevices)};")
    lines.append("")
    lines.append(f"struct bdevsw\tshadowbsw[{max(len(bdevices), 1)}];")
    lines.append(f"struct cdevsw\tshadowcsw[{max(len(cdevices), 1)}];")
    lines.append("")

    dump_handler: list[str] = []
    _emit_major_dev(lines, assignments.get("root"), devices_by_name, "rootdev", True, dump_handler)
    _emit_major_dev(lines, assignments.get("pipe"), devices_by_name, "pipedev", True, dump_handler)
    _emit_major_dev(lines, assignments.get("dump"), devices_by_name, "dumpdev", True, dump_handler)
    _emit_major_dev(lines, assignments.get("swap"), devices_by_name, "swapdev", True, dump_handler)
    if dump_handler:
        lines.append(f"extern {dump_handler[-1]}dump();")
    swap_name = assignments.get("swap").pathname if assignments.get("swap") is not None else "/dev/swap"
    lines.append(f'struct bootobj swapfile = {{"", "{swap_name}", 0, 0, 0, 0}};')
    lines.append("")

    for array_name, mask in [
        ("io_init", "I"),
        ("io_start", "s"),
        ("io_poll", "p"),
        ("io_halt", "h"),
        ("io_kenter", "E"),
        ("io_kexit", "X"),
    ]:
        lines.append(f"int\t(*{array_name}[])() = ")
        lines.append("{")
        for device in configured_devices:
            if _has_mask(device, mask):
                suffix = {
                    "I": "init",
                    "s": "start",
                    "p": "poll",
                    "h": "halt",
                    "E": "kenter",
                    "X": "kexit",
                }[mask]
                lines.append(f"\t{device.handler}{suffix},")
        lines.append("\t(int (*)())0")
        lines.append("};")
        lines.append("")

    lines.append("extern void\tsys_init();")
    dispatch_devices = [device for device in configured_devices if _has_type(device, "d")]
    for device in dispatch_devices:
        lines.append(f"extern void\t{device.handler}_init();")
    lines.append("class_t class[] = {")
    lines.append('\t\t"SYS", sys_init, NULL,')
    for device in dispatch_devices:
        lines.append(f'\t\t"{_uppermap(device.handler)}", {device.handler}_init, NULL,')
    lines.append("};")
    lines.append(f"int\tnclass = {len(dispatch_devices) + 1};")
    lines.append("")

    exec_devices = sorted(
        [device for device in configured_devices if _has_type(device, "e")],
        key=lambda device: max((controller.ipl for controller in controller_groups.get(device.name, []) if controller.configured), default=0),
        reverse=True,
    )
    lines.append("struct execsw execsw[] = {")
    exec_count = 0
    if exec_devices:
        entries: list[str] = []
        for device in exec_devices:
            for index in range(max(device.maximum_units, 0)):
                entries.append(f"\t{{ {device.handler}magic+{index}, {device.handler}exec, {device.handler}core }}")
                exec_count += 1
            for controller in controller_groups.get(device.name, []):
                if controller.configured and controller.units == 0:
                    entries.append(f"\t{{ NULL, {device.handler}exec, {device.handler}core }}")
                    exec_count += 1
                    break
        for index, entry in enumerate(entries):
            trailer = "," if index + 1 < len(entries) else ""
            lines.append(entry + trailer)
    else:
        lines.append("\t{ 0, 0, 0 }")
    lines.append("};")
    lines.append(f"int nexectype = {exec_count};")

    output_path.write_text("\n".join(lines) + "\n")


def _write_fsconf_c(output_path: Path, filesystems: list[FileSystemSpec]) -> None:
    configured_filesystems = [filesystem for filesystem in filesystems if filesystem.configured]
    lines: list[str] = [
        "/* generated by uts_idconfig.py */",
        '#include\t"config.h"',
        '#include\t"sys/types.h"',
        '#include\t"sys/vfs.h"',
        "",
    ]

    for filesystem in configured_filesystems:
        lines.append(f"extern int {filesystem.prefix}init();")

    lines.append(f"int nfstype = {len(configured_filesystems) + 1};")
    lines.append("")
    lines.append("struct vfssw vfssw[] = {")
    lines.append('\t"EMPTY", 0x0, 0x0, 0x0')
    for filesystem in configured_filesystems:
        lines.append(f',\n"{filesystem.name}", {filesystem.prefix}init, 0x0, 0x0')
    lines.append("};")
    output_path.write_text("\n".join(lines) + "\n")


def _write_vector_c(output_path: Path, devices: list[DeviceSpec], controllers: list[ControllerSpec]) -> None:
    vector_entries = _interrupt_entries(devices, controllers)
    lines: list[str] = [
        "/* generated by uts_idconfig.py */",
        "/* Table of Interrupt Vectors */",
        "",
        "extern int intnull();",
        "extern clock();",
    ]

    declared_handlers: set[str] = set()
    for vector in sorted(vector_entries):
        for device, _controller in vector_entries[vector]:
            if device.handler in declared_handlers:
                continue
            lines.append(f"extern {device.handler}intr();")
            declared_handlers.add(device.handler)

    for vector in sorted(vector_entries):
        shared_entries = vector_entries[vector]
        if len(shared_entries) < 2:
            continue
        first_controller = shared_entries[0][1]
        if first_controller.interrupt_type < 3 or first_controller.interrupt_type == 1:
            continue
        lines.append("")
        lines.append(f"shrint{vector}() {{")
        for device, _controller in shared_entries:
            lines.append(f"\t{device.handler}intr({vector});")
        lines.append("}")

    lines.append("")
    lines.append("int\t(*ivect[])() = {")
    lines.append("\tclock\t\t/* 0\t*/")
    highest_vector = 0
    for vector in range(1, 256):
        lines.append(",")
        shared_entries = vector_entries.get(vector, [])
        if shared_entries:
            first_device, first_controller = shared_entries[0]
            if len(shared_entries) >= 2 and first_controller.interrupt_type >= 3 and first_controller.interrupt_type != 1:
                lines.append(f"\tshrint{vector}\t\t/* {vector}\t*/")
            else:
                lines.append(f"\t{first_device.handler}intr\t\t/* {vector}\t*/")
            highest_vector = vector
        else:
            lines.append(f"\tintnull\t\t/* {vector}\t*/")
    lines.append("};")
    lines.append(f"int nintr = {highest_vector + 1};")
    lines.append("/* Table of ipl values for interrupt handlers. */")
    lines.append("")
    lines.append("unsigned char intpri[] = {")
    lines.append("\t8")
    for vector in range(1, 256):
        lines.append(f"\t/* {vector - 1} */,\n\t{vector_entries[vector][0][1].ipl if vector in vector_entries else 0}")
    lines.append(f"\t/* {255} */")
    lines.append("};")
    level_intr_mask = 0
    for vector in range(0, 32):
        shared_entries = vector_entries.get(vector, [])
        if shared_entries and shared_entries[0][1].interrupt_type == 4:
            level_intr_mask |= 1 if vector == 0 else 1 << (vector - 1)
    lines.append(f"unsigned long level_intr_mask = 0x{level_intr_mask:x};")
    output_path.write_text("\n".join(lines) + "\n")


def _write_direct(output_path: Path, conf_root: Path, devices: list[DeviceSpec], filesystems: list[FileSystemSpec], controllers: list[ControllerSpec]) -> None:
    configured_names = _configured_names(controllers, filesystems)
    lines: list[str] = []

    for device in devices:
        pack_dir = conf_root / "pack.d" / device.name
        if device.name in configured_names:
            lines.append(str(pack_dir / "Driver.o"))
            space_c = pack_dir / "space.c"
            if space_c.exists():
                lines.append(str(space_c))
            continue
        stubs_c = pack_dir / "stubs.c"
        if stubs_c.exists():
            lines.append(str(stubs_c))

    for filesystem in filesystems:
        pack_dir = conf_root / "pack.d" / filesystem.name
        if filesystem.configured:
            lines.append(str(pack_dir / "Driver.o"))
            space_c = pack_dir / "space.c"
            if space_c.exists():
                lines.append(str(space_c))
            continue
        stubs_c = pack_dir / "stubs.c"
        if stubs_c.exists():
            lines.append(str(stubs_c))

    output_path.write_text("\n".join(lines) + ("\n" if lines else ""))


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _object_path_from_source(obj_root: Path, source_root: Path, output_root: str, source_path: Path) -> Path:
    relative_source = source_path.relative_to(source_root)
    return obj_root / output_root / relative_source.with_suffix(".o")


def _expand_rule(obj_root: Path, source_root_text: str, output_root: str, patterns: list[str]) -> tuple[list[str], list[str]]:
    source_root = WORKSPACE_ROOT / source_root_text
    if not source_root.exists():
        return [], []

    sources: list[str] = []
    objects: list[str] = []
    seen_sources: set[Path] = set()
    for pattern in patterns:
        for source_path in sorted(source_root.glob(pattern)):
            if not source_path.is_file():
                continue
            canonical = source_path.resolve()
            if canonical in seen_sources:
                continue
            seen_sources.add(canonical)
            sources.append(str(canonical))
            objects.append(str(_object_path_from_source(obj_root, source_root, output_root, canonical).resolve()))
    return sources, objects


def _single_source_mapping(obj_root: Path, module_name: str, handler_name: str) -> tuple[list[str], list[str], str | None]:
    candidates = _unique_strings([module_name, handler_name])
    for source_root_text, output_root in SINGLE_SOURCE_FALLBACKS:
        source_root = WORKSPACE_ROOT / source_root_text
        if not source_root.exists():
            continue
        for candidate in candidates:
            source_path = source_root / f"{candidate}.c"
            if not source_path.is_file():
                continue
            return [str(source_path.resolve())], [str(_object_path_from_source(obj_root, source_root, output_root, source_path.resolve()).resolve())], "single-source"
    return [], [], None


def _resolve_package_implementation(obj_root: Path, module_name: str, handler_name: str) -> tuple[list[str], list[str], str]:
    rules = PACKAGE_SOURCE_RULES.get(module_name, [])
    if rules:
        sources: list[str] = []
        objects: list[str] = []
        for rule in rules:
            rule_sources, rule_objects = _expand_rule(
                obj_root=obj_root,
                source_root_text=str(rule["source_root"]),
                output_root=str(rule["output_root"]),
                patterns=[str(pattern) for pattern in rule["patterns"]],
            )
            sources.extend(rule_sources)
            objects.extend(rule_objects)
        return _unique_strings(sources), _unique_strings(objects), "explicit"

    sources, objects, strategy = _single_source_mapping(obj_root, module_name, handler_name)
    if strategy is not None:
        return sources, objects, strategy
    return [], [], "unmapped"


def _build_core_link_objects(obj_root: Path, driver_packages: list[dict[str, object]]) -> list[str]:
    packaged_objects: set[Path] = set()
    for package in driver_packages:
        for object_path in package.get("implementation_objects", []):
            packaged_objects.add(Path(str(object_path)).resolve())

    core_objects: list[str] = []
    for candidate in sorted(obj_root.rglob("*.o")):
        resolved = candidate.resolve()
        if resolved in packaged_objects:
            continue
        if obj_root / "ml" in resolved.parents:
            continue
        core_objects.append(str(resolved))
    return core_objects


def _build_manifest(
    conf_root: Path,
    output_dir: Path,
    obj_root: Path,
    devices: list[DeviceSpec],
    controllers: list[ControllerSpec],
    tunables: dict[str, int],
    filesystems: list[FileSystemSpec],
    assignments: dict[str, SystemAssignment],
) -> dict[str, object]:
    controller_groups = _controller_groups(controllers)
    configured_names = _configured_names(controllers, filesystems)
    filesystem_lookup = {filesystem.name: filesystem for filesystem in filesystems}

    device_entries: list[dict[str, object]] = []
    driver_packages: list[dict[str, object]] = []
    seen_packages: set[str] = set()
    for device in devices:
        pack_dir = conf_root / "pack.d" / device.name
        configured = device.name in configured_names
        implementation_sources, resolved_objects, mapping_strategy = _resolve_package_implementation(obj_root, device.name, device.handler)
        controller_entries = [asdict(controller) for controller in controller_groups.get(device.name, []) if controller.configured]
        device_entries.append(
            {
                "name": device.name,
                "handler": device.handler,
                "symbol": _uppermap(device.handler),
                "configured": configured,
                "mask": device.mask,
                "type_flags": device.type_flags,
                "channel": device.channel,
                "block_major_start": device.block_major_start,
                "block_major_end": device.block_major_end,
                "char_major_start": device.char_major_start,
                "char_major_end": device.char_major_end,
                "controllers": controller_entries,
                "pack_dir": str(pack_dir),
                "driver_object": str(pack_dir / "Driver.o"),
                "space_c": str(pack_dir / "space.c") if (pack_dir / "space.c").exists() else None,
                "stubs_c": str(pack_dir / "stubs.c") if (pack_dir / "stubs.c").exists() else None,
                "implementation_sources": implementation_sources,
                "implementation_objects": resolved_objects,
                "mapping_strategy": mapping_strategy,
            }
        )
        driver_packages.append(
            {
                "name": device.name,
                "configured": configured,
                "kind": "filesystem" if filesystem_lookup.get(device.name, None) is not None else "device",
                "handler": device.handler,
                "pack_dir": str(pack_dir),
                "driver_object": str(pack_dir / "Driver.o"),
                "space_c": str(pack_dir / "space.c") if (pack_dir / "space.c").exists() else None,
                "stubs_c": str(pack_dir / "stubs.c") if (pack_dir / "stubs.c").exists() else None,
                "implementation_sources": implementation_sources,
                "implementation_objects": resolved_objects,
                "mapping_strategy": mapping_strategy,
            }
        )
        seen_packages.add(device.name)

    for filesystem in filesystems:
        if filesystem.name in seen_packages:
            continue
        pack_dir = conf_root / "pack.d" / filesystem.name
        implementation_sources, implementation_objects, mapping_strategy = _resolve_package_implementation(obj_root, filesystem.name, filesystem.prefix)
        driver_packages.append(
            {
                "name": filesystem.name,
                "configured": filesystem.configured,
                "kind": "filesystem",
                "handler": filesystem.prefix,
                "pack_dir": str(pack_dir),
                "driver_object": str(pack_dir / "Driver.o"),
                "space_c": str(pack_dir / "space.c") if (pack_dir / "space.c").exists() else None,
                "stubs_c": str(pack_dir / "stubs.c") if (pack_dir / "stubs.c").exists() else None,
                "implementation_sources": implementation_sources,
                "implementation_objects": implementation_objects,
                "mapping_strategy": mapping_strategy,
            }
        )

    return {
        "conf_root": str(conf_root),
        "cf_dir": str(output_dir),
        "pack_root": str(conf_root / "pack.d"),
        "obj_root": str(obj_root),
        "generated_files": {
            "config_h": str(output_dir / "config.h"),
            "conf_c": str(output_dir / "conf.c"),
            "fsconf_c": str(output_dir / "fsconf.c"),
            "vector_c": str(output_dir / "vector.c"),
            "direct": str(output_dir / "direct"),
        },
        "devices": device_entries,
        "driver_packages": driver_packages,
        "core_link_objects": _build_core_link_objects(obj_root, driver_packages),
        "tunables": tunables,
        "filesystems": [asdict(filesystem) for filesystem in filesystems],
        "assignments": {name: asdict(assignment) for name, assignment in sorted(assignments.items())},
    }


def _stage_static_cf_files(conf_root: Path, output_dir: Path) -> None:
    source_vuifile = conf_root / "cf.d" / "vuifile"
    destination_vuifile = output_dir / "vuifile"
    if source_vuifile.exists() and source_vuifile != destination_vuifile:
        shutil.copyfile(source_vuifile, destination_vuifile)


def main() -> int:
    args = _parse_args()
    conf_root = Path(args.conf_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    obj_root = Path(args.obj_root).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    devices = _parse_mdevice(conf_root / "cf.d" / "mdevice")
    controllers = _parse_sdevice_dir(conf_root / "sdevice.d")
    tunables = _parse_mtune(conf_root / "cf.d" / "mtune")
    tunables.update(_parse_stune(conf_root / "cf.d" / "stune"))
    filesystems = _parse_mfsys_dir(conf_root / "mfsys.d")
    configured_filesystems = _parse_sfsys_dir(conf_root / "sfsys.d")
    filesystems = [
        FileSystemSpec(name=filesystem.name, prefix=filesystem.prefix, configured=configured_filesystems.get(filesystem.name, False))
        for filesystem in filesystems
    ]
    assignments = _parse_sassign(conf_root / "cf.d" / "sassign")

    enabled_modules = {_normalize_module_name(name) for name in args.enable_module}
    excluded_modules = {_normalize_module_name(name) for name in args.exclude_module}

    if enabled_modules or excluded_modules:
        controllers = [
            replace(
                controller,
                configured=(
                    True
                    if _normalize_module_name(controller.name) in enabled_modules
                    else False
                    if _normalize_module_name(controller.name) in excluded_modules
                    else controller.configured
                ),
            )
            for controller in controllers
        ]
        filesystems = [
            replace(
                filesystem,
                configured=(
                    True
                    if _normalize_module_name(filesystem.name) in enabled_modules
                    else False
                    if _normalize_module_name(filesystem.name) in excluded_modules
                    else filesystem.configured
                ),
            )
            for filesystem in filesystems
        ]

    _write_config_header(output_dir / "config.h", devices, controllers, tunables)
    _write_conf_c(output_dir / "conf.c", devices, controllers, filesystems, assignments)
    _write_fsconf_c(output_dir / "fsconf.c", filesystems)
    _write_vector_c(output_dir / "vector.c", devices, controllers)
    _write_direct(output_dir / "direct", conf_root, devices, filesystems, controllers)
    _stage_static_cf_files(conf_root, output_dir)
    manifest = _build_manifest(conf_root, output_dir, obj_root, devices, controllers, tunables, filesystems, assignments)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())