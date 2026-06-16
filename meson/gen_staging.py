#!/usr/bin/env python3
"""Emit the master.d staging plan for meson.build to foreach over.

Ports the discovery half of uts_stage_master_at386.py: which module dirs exist,
which metadata fragments each carries, and where each stages to. meson.build
turns each emitted line into a stage_fragment.py custom_target (for cpp'd
fragments) or an install_data (for space.c/stubs.c), and the aggregate lines into
stage_aggregate.py custom_targets. Keeps the same module lists (COMMODS +
AT386MODS) and fragment->dest mapping as the old tool so the staged tree is
identical.

Output lines (one per item), tab-separated:
  frag\t<srcrelpath>\t<destdir>\t<destname>\t<mode>
  copy\t<srcrelpath>\t<destdir>\t<destname>
  agg\t<cfname>\t<srcdotdir>
  cf\t<srcrelpath>\t<destname>          (top-level CFFILES, mode=cf)

Paths are relative to kernel_root (frag/copy/cf src) or are conf-tree-relative
dest dirs (destdir, srcdotdir). meson resolves them against kernel_root / outdir.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Module lists, verbatim from uts_stage_master_at386.py.
COMMODS = [
    "nfs", "fp", "gentty", "kernel", "weitek", "mem", "merge", "osm", "async",
    "ldterm", "ansi", "char", "sad", "events", "nmi", "shm", "sem", "ipc", "msg",
    "pic", "specfs", "fifofs", "fdfs", "kma", "kmacct", "hrt", "nfa", "prf",
    "sxt", "nsxt", "xt", "nxt", "cpyrt", "pipemod", "ttcompat", "s5", "ufs",
    "xnamfs", "RFS", "namefs", "bfs", "elf", "coff", "xout", "intp", "i286x",
    "dosx", "rt", "ts", "clist", "connld", "gendisp", "proc", "rmc", "xque",
    "ws", "sysmsg", "vx", "raio", "app", "arp", "clone", "des", "icmp", "ip",
    "klm", "krpc", "ktli", "llcloop", "log", "pckt", "ptem", "ptm", "pts",
    "ramd", "rawip", "sockmod", "tcp", "ticlts", "ticots", "ticotsor", "timod",
    "tirdwr", "udp", "gdebugger", "kdb", "kdb-util",
]
AT386MODS = ["asy", "dma", "rtc", "cram", "hd", "fd", "lp", "kd", "kdvm", "cmux", "gvid", "m320"]

# fragment filename -> conf .d subdir, per module class.
COMMON_FRAGS = {"mfsys": "mfsys.d", "sfsys": "sfsys.d", "node": "node.d",
                "rc": "rc.d", "sd": "sd.d", "init": "init.d",
                "mdev": "mdevice.d", "sdev": "sdevice.d"}
AT386_FRAGS = {"mfsys": "mfsys.d", "sfsys": "sfsys.d", "node": "node.d",
               "init": "init.d", "mdev": "mdevice.d", "sdev": "sdevice.d"}

# Top-level cf.d input files (mode=cf). mdevice is NOT here: it is purely the
# aggregate of mdevice.d/*.
CFFILES = ["sassign", "stune", "mtune", "init.base"]

# cf.d aggregates: <cfname> = concat(sorted(<dotdir>/*)).
AGGREGATES = [("mdevice", "mdevice.d"), ("mfsys", "mfsys.d"),
              ("sdevice", "sdevice.d"), ("sfsys", "sfsys.d")]


def emit(kernel_root: Path) -> str:
    master = kernel_root / "i386/master.d"
    overlay = kernel_root / "arch/at/i386/master.d"
    lines: list[str] = []

    def do_module(base: Path, mod: str, frags: dict[str, str]) -> None:
        d = base / mod
        if not d.is_dir():
            return
        rel = d.relative_to(kernel_root).as_posix()
        for c in sorted(d.glob("*.c")):
            lines.append(f"copy\t{rel}/{c.name}\tpack.d/{mod}\t{c.name}")
        for frag, dotdir in frags.items():
            if (d / frag).is_file():
                lines.append(f"frag\t{rel}/{frag}\t{dotdir}\t{mod}\tfrag")

    for mod in COMMODS:
        do_module(master, mod, COMMON_FRAGS)
    for mod in AT386MODS:
        do_module(overlay, mod, AT386_FRAGS)

    for name in CFFILES:
        p = master / name
        if p.is_file():
            lines.append(f"cf\t{p.relative_to(kernel_root).as_posix()}\t{name}\tcf")

    for cfname, dotdir in AGGREGATES:
        lines.append(f"agg\t{cfname}\t{dotdir}")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel-root", required=True)
    args = ap.parse_args()
    sys.stdout.write(emit(Path(args.kernel_root).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
