#!/usr/bin/env python3
"""Aggregate staged .d fragments into a single cf.d input file.

Plain concatenation of the fragment files in sorted order -- the cf.d/{mdevice,
mfsys,sdevice,sfsys} inputs idconfig reads. (The old build appended a trailing
blank line per fragment for mfsys/sdevice/sfsys but not mdevice; that was a shell
artifact with no parser meaning -- idconfig skips blanks -- so all four are plain
concat here.) Inputs are the already-cpp'd stage_fragment.py outputs, passed
explicitly so Meson tracks the dependency, sorted by final basename (module name)
to match the old sorted(dir.glob('*')) order.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', dest='output', required=True)
    ap.add_argument('inputs', nargs='*')
    args = ap.parse_args()

    chunks = [Path(p).read_text() for p in sorted(args.inputs, key=lambda x: Path(x).name)]
    Path(args.output).write_text(''.join(chunks))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
