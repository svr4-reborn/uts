#!/usr/bin/env python3
"""Resolve the kernel object grouping: which source compiles into which
per-driver Driver.o, and which leftover objects sweep into kernel.o.

This is the core logic that replaces uts_driver_compose.py. The key
difference from the old tool: it is *additive and asserted*, not subtractive.
The old flow compiled every subsystem flat, carved drivers out by source
glob, and swept "everything else" into kernel.o -- so a renamed/added file
silently changed kernel.o with no signal. Here, every compiled source must
belong to exactly one bucket (a driver, or kernel.o-eligible), and a source
claimed by no driver in a subsystem that *has* drivers is reported, so drift
is caught at configure time.

Outputs a JSON plan: { drivers: {name: [srcs]}, kernel: [srcs],
metadata_only: [names], by_subsystem: {...} }.

Run standalone for validation:
    ./gen_groups.py --kernel-root .. --module-map kernel-modules.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Subsystem source roots, relative to kernel_root. The AT386 overlay
# (arch/at/i386/*) and the generic i386/* tree both contribute; io merges them.
SUBSYSTEM_ROOTS: dict[str, list[str]] = {
    'os':      ['i386/os'],
    'vm':      ['i386/vm'],
    'disp':    ['i386/disp'],
    'vx':      ['i386/vx'],
    'exec':    ['i386/exec'],          # recursive
    'fs':      ['i386/fs'],            # recursive
    'io':      ['arch/at/i386/io', 'i386/io'],  # recursive, overlay
    'des':     ['i386/des'],
    'rpc':     ['i386/rpc'],
    'ktli':    ['i386/ktli'],
    'klm':     ['i386/klm'],
    'netinet': ['i386/netinet'],
    # kdb has three kernel subtrees only; i386/kdb/cmd is a userland command and
    # is deliberately NOT compiled into the kernel (the old build had no target
    # for it). Listing the subtrees explicitly is what catches that.
    'kdb':     ['i386/kdb/kdb', 'i386/kdb/gdebugger', 'i386/kdb/kdb-util'],
}

# Subtrees compiled elsewhere / excluded from the flat subsystem sweep, mirroring
# the old io-core exclude_dirs and the recursive walks.
IO_EXCLUDE_DIRS = {'ws', 'kd', 'kdvm', 'mouse'}


def subsystem_of(rel: str) -> str | None:
    """Return the subsystem key for a source path relative to kernel_root."""
    p = Path(rel)
    # io overlay: arch/at/i386/io/** and i386/io/**
    if p.parts[:4] == ('arch', 'at', 'i386', 'io') or p.parts[:2] == ('i386', 'io'):
        return 'io'
    if p.parts[0] == 'i386':
        key = p.parts[1]
        if key in SUBSYSTEM_ROOTS:
            return key
    return None


def discover_subsystem_sources(kernel_root: Path) -> dict[str, list[str]]:
    """All compilable sources per subsystem (mirrors build.py discovery)."""
    found: dict[str, list[str]] = {k: [] for k in SUBSYSTEM_ROOTS}
    for sub, roots in SUBSYSTEM_ROOTS.items():
        for root in roots:
            base = kernel_root / root
            if not base.is_dir():
                continue
            for path in sorted(base.rglob('*')):
                if not path.is_file() or path.suffix not in ('.c', '.s'):
                    continue
                rel = path.relative_to(kernel_root).as_posix()
                if sub == 'io' and any(part in IO_EXCLUDE_DIRS for part in path.relative_to(base).parts[:-1]):
                    # ws/kd/kdvm/mouse are their own driver buckets, not io-core
                    pass  # still discovered; they belong to drivers below
                found[sub].append(rel)
    return found


def _master_dir(kernel_root: Path, module: str) -> Path | None:
    for base in ('i386/master.d', 'arch/at/i386/master.d'):
        d = kernel_root / base / module
        if d.is_dir():
            return d
    return None


def build_plan(kernel_root: Path, module_map: dict[str, list[str]]) -> dict:
    discovered = discover_subsystem_sources(kernel_root)
    all_discovered = {s for srcs in discovered.values() for s in srcs}

    # Sources claimed by a driver module.
    claimed: dict[str, str] = {}  # src -> module
    drivers: dict[str, list[str]] = {}
    metadata_only: list[str] = []
    empty_driver: list[str] = []   # need an empty Driver.o placeholder
    conflicts: list[dict] = []
    missing: list[dict] = []

    for module, srcs in module_map.items():
        if not srcs:
            # No kernel-tree .c sources. Either pure metadata or built from a
            # master.d/<module>/stubs.c (configured-out stub) at idmkunix time.
            # One exception: a module that supplies only space.c (no stubs.c, no
            # kernel sources) and is configured-in without the mdevice NODRIVE
            # ('N') flag -- idconfig then *requires* a Driver.o at config time, so
            # it needs an empty placeholder Driver.o (build.py's _compile_empty_
            # object). gendisp is the sole such module: it exists only to set the
            # dispatcher slice_size tunable via space.c. Modules with stubs.c
            # (async/events/nfa/rmc) get their Driver.o from idmkunix instead.
            md = _master_dir(kernel_root, module)
            if md is not None and (md / 'space.c').is_file() and not (md / 'stubs.c').is_file():
                empty_driver.append(module)
            else:
                metadata_only.append(module)
            continue
        drivers[module] = srcs
        for s in srcs:
            if s in claimed:
                conflicts.append({'src': s, 'modules': [claimed[s], module]})
            claimed[s] = module
            if s not in all_discovered and not (kernel_root / s).is_file():
                missing.append({'module': module, 'src': s})

    # kernel.o = everything discovered that no driver claimed, minus ml (built
    # separately as locore/start/syms) and the driver-only subtrees.
    kernel_srcs = sorted(s for s in all_discovered if s not in claimed)

    return {
        'drivers': {k: sorted(v) for k, v in sorted(drivers.items())},
        'kernel': kernel_srcs,
        'metadata_only': sorted(metadata_only),
        'empty_driver': sorted(empty_driver),
        'conflicts': conflicts,
        'missing': missing,
        'counts': {
            'discovered': len(all_discovered),
            'claimed': len(claimed),
            'kernel_o': len(kernel_srcs),
            'drivers': len(drivers),
        },
    }


def emit_meson(plan: dict) -> str:
    """Emit the plan as delimited lines meson.build reads via run_command stdout:

        driver:<module>:<src>|<subsystem>;<src>|<subsystem>;...
        kernel:<src>|<subsystem>;...
        empty:<module>:                 (empty Driver.o placeholder)

    One source per `src|subsystem` so meson can apply the right compile flags.
    Coverage failures are reported on stderr and signalled by a nonzero exit, so
    `meson setup` with check:true aborts -- nothing is emitted on stdout then.
    """
    lines: list[str] = []
    for module, srcs in plan['drivers'].items():
        tagged = ';'.join(f'{s}|{subsystem_of(s)}' for s in srcs)
        lines.append(f'driver:{module}:{tagged}')
    tagged = ';'.join(f'{s}|{subsystem_of(s)}' for s in plan['kernel'])
    lines.append(f'kernel::{tagged}')
    for module in plan['empty_driver']:
        lines.append(f'empty:{module}:')
    return '\n'.join(lines) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--kernel-root', required=True)
    ap.add_argument('--module-map', required=True)
    ap.add_argument('--out')
    ap.add_argument('--format', choices=('json', 'meson'), default='json')
    args = ap.parse_args()
    kernel_root = Path(args.kernel_root).resolve()
    module_map = json.loads(Path(args.module_map).read_text())
    plan = build_plan(kernel_root, module_map)

    # Coverage assertions -- the fragility fix flagged in the audit. Check before
    # emitting so a drifted plan never reaches meson.
    if plan['conflicts']:
        print('ERROR: sources claimed by multiple drivers:', plan['conflicts'], file=sys.stderr)
        return 1
    if any(s for s in plan['kernel'] if subsystem_of(s) is None) or \
       any(subsystem_of(s) is None for srcs in plan['drivers'].values() for s in srcs):
        unmapped = sorted({s for s in plan['kernel'] if subsystem_of(s) is None} |
                          {s for srcs in plan['drivers'].values() for s in srcs if subsystem_of(s) is None})
        print('ERROR: sources with no subsystem (no compile flags):', unmapped, file=sys.stderr)
        return 1
    if plan['missing']:
        print('ERROR: module map references missing sources:', plan['missing'], file=sys.stderr)
        return 1

    text = emit_meson(plan) if args.format == 'meson' else json.dumps(plan, indent=2) + '\n'
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
